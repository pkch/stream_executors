## Enhanced Executors

This library provides several classes extending the functionality of the
standard library `concurrent.futures.Executor`.

# StreamExecutor

`StreamExecutor.map` acquires only a part of the inputs in advance (as
specified by the client in the parameter `buffer_size`), and does it in
the background.

The standard library `ThreadPoolExecutor.map` and `ProcessPoolExecutor.map`
acquire all of the inputs in advance, synchronously. This has several
limitations:

1. The entire input is stored in memory. This makes `Executor.map`
incompatible with the builtin `map` that uses iterators to support processing
arbitrarily large or infinite inputs.

2. A call to `Executor.map` blocks until the entire input is acquired. This
is unfortunate given that the entire point of `concurrent.futures` is to
avoid blocking.

3. The entire input is produced and processed regardless of whether it is
necessary. This may result in wasted computational and memory resources.

A naive implementation of `Executor.map` that precisely imitates the regular
`map` would solve all these problems. However, it would submit each task to
the worker pool only when the client requests the corresponding result,
rather than in advance - defeating the main reason to use executors.

A better implementation may pre-process a part of the input in advance, and
then give the control back to the client. This solves problems 1 and 3.
`Executor.map` will still block, but only for the time it takes to acquire
(not process) the specified amount of input. However, if the client wants to
consume all the output faster than it can be produced, they will want to
pre-process as much as they can fit into memory. This means `Executor.map`
may block for a long time.

This implementation acquires the inputs in the background, and therefore does
not block at all.

Setting `buffer_size` parameter to `None` (which means no limit)
results in the same behavior as `concurrent.futures.Executor.map` except
without blocking at the call site. Setting it to 0 would have resulted in the
same behavior as the builtin `map` (without any benefit of using the worker
pool; therefore it is not supported).

If the output will be consumed slower than it can be produced, a small value
of `buffer_size` is reasonable (still it should probably be greater
than 1 to allow for some random variation in resource availability). If the
output will be consumed faster than it can be produced, `buffer_size`
should be set to the highest value that memory allows. Of course, if less
than the entire output will be consumed, a large value of `buffer_size`
may needlessly perform extra work. Ideally, client should explicitly set this
argument, but a default value of 10000 is provided because it's unlikely to
exert pressure on the memory while still performing much of the work in
advance.

Comparison with other map functions:

    def process(i):
        time.sleep(0.1)
        return i

    is_odd = lambda x: x%2

    n = 10 # will need 20 numbers to get 10 odd ones

    # built-in map takes 0.1 * 20 + 0.5 = 2.5 sec
    m = map(process, count())
    g = islice(filter(is_odd, m), n)
    time.sleep(0.5)
    # only starts processing here
    assert list(g) == list(range(1, 2*n, 2))

    # ThreadPoolExecutor.map hangs
    executor = ThreadPoolExecutor(max_workers=10)
    m = executor.map(process, count())

    # StreamExecutor.map takes 0.1 * 20 / 2 = 1 sec
    # starts processing here, without waiting for iteration
    executor = StreamExecutor(max_workers=2)
    m = executor.map(process, count())
    g = islice(filter(is_odd, m), n)
    time.sleep(0.5)
    assert list(g) == list(range(1, 2*n, 2))
