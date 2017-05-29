[![Build Status](https://travis-ci.org/pkch/stream_executors.svg)](https://travis-ci.org/pkch/stream_executors)
[![Coverage Status](https://coveralls.io/repos/github/pkch/stream_executors/badge.svg?branch=master)](https://coveralls.io/github/pkch/stream_executors?branch=master)
[![MIT licensed](https://img.shields.io/badge/license-MIT-blue.svg)](https://raw.githubusercontent.com/pkch/stream_executors/LICENSE)

# Stream Executor

Drop-in replacements for the `concurrent.futures` executors with non-blocking
`map`.

## Background

The standard library `Executor.map` has several limitations:

1. The entire input is stored in memory. This makes `Executor.map` unusable
for large or infinite inputs.

2. A call to `Executor.map` blocks until the entire input is acquired. This
is unfortunate given that `concurrent.futures` is created specifically for
non-blocking computation.

3. The entire input is acquired and processed even if most the output is
never needed. This may result in wasted computational and memory resources.

This library provides classes `StreamThreadPoolExecutor` and
`StreamProcessPoolExecutor` (subclasses of the respective stdlib classes)
that address those limitations by acquiring inputs in a background thread. To
avoid memory overflow, it acquires only a part of the inputs in advance, as
specified by the client in the `buffer_size` argument. Then, as each input is
processed, a new one is acquired.


## Examples

### Infinite input, instantaneous production

    import time
    from concurrent.futures import ThreadPoolExecutor
    from itertools import count, islice

    from streamexecutors import StreamThreadPoolExecutor

    def square(x):
        time.sleep(0.1)
        return x ** 2

    # Parallelizes and doesn't block.
    squares = StreamThreadPoolExecutor().map(square, count())

    # Compare to builtin and concurrent.futures map

    # Doesn't block, but also doesn't parallelize.
    squares = map(square, count())

    # Hangs
    squares = ThreadPoolExecutor().map(square, count())



### Finite input, slow production

    def produce():
        for i in range(100):
            time.sleep(0.02)
            yield i

    def print10(iterable):
        print(list(islice(iterable, 10)))

    # Doesn't block.
    # Total time to completion 10 x 0.02 + 0.1 (parallel) = 0.3 sec.
    squares = StreamThreadPoolExecutor().map(square, produce())
    print10(squares)

    # Compare to builtin and concurrent.futures map

    # Doesn't block.
    # Total time to completion 10 x (0.1 + 0.02) = 1.2 sec (sequential).
    squares = map(square, produce())
    print10(squares)

    # Blocks for 100 x 0.02 = 2 sec.
    # Total time to completion 2 + 0.1 (parallel) = 2.1 sec.
    squares = ThreadPoolExecutor().map(square, produce())
    print10(squares)


### Pipeline

In the [Word Count
example](https://github.com/pkch/stream_executors/blob/master/examples/wordcount.py),
this implementation is used to create a simple pipeline, where each stage
consumes the output of the previous stage:

    # Generator of urls of recently updated Github repos.
    def get_url(): ...

    # Download a url and produce `requests.Response` object.
    pages = ex.map(download, get_urls(), buffer_size=1)

    # Read page, produce a `dict` with page url and word count of 'python'.
    counts = ex.map(partial(count_word, 'python'), pages, buffer_size=1)

    # Upload count dict to an echo server, produce server response (as json).
    upload_results = ex.map(upload, counts, buffer_size=1)

    # Lazily produce the first two upload_results.
    first_2 = islice(upload_results, 2)

    # Do some other work in the main thread for a while.
    ...

    # Greedily consume everything.
    result = list(first2)

With `buffer_size` set to 1, at most 2 items will be waiting for processing
by `map`: one will be in the queue, and one will be in the local variable
waiting on `queue.put`. This means that if enough time was spent on other
work earlier, there will be 2 echo server responses waiting to be consumed by
`list` at the time `list` is called, so `list` won't block. This implies
`count_word` has processed 4 pages: 2 were already processed by `upload`, and
2 more are waiting to be uploaded. Similarly, `download` has processed 6
pages: 4 were processed by `count_word`, and 2 more are waiting to be
consumed by `count_word`.

Right after `list` is invoked, `upload` will see that its buffer is no longer
full, and so it will start processing again. This immediately causes the rest
of the pipeline to also start working. However, as the interpreter exits and
all the pipeline objects are garbage collected, no new processing will be
allowed, and so the pipeline will stop after existing tasks are completed.
Depending on the timing of gc, this will result in the downloading of 0-2
additional pages, counting the words in them, and uploading them to the
server.

## Buffer size

If `buffer_size` argument is set to `None`, inputs are acquired without
limit, replicating `concurrent.futures.Executor.map` behavior only without
blocking. On a large or infinite input, it will run out of memory and
possibly hog CPU unless the consumer gets garbage collected quickly (input
retrieval stops when consumer goes out of scope).

If the output will be consumed slower than it can be produced, a small value
of `buffer_size` is reasonable (still it should probably be greater
than 1 to allow for some random variation in resource availability).

If the output will be consumed faster than it can be produced, and the entire
output is needed, then `buffer_size` should be set to the highest value that
memory allows.

If the output will be consumed faser than it can be produced, but only a part
of the output will be needed, the choice of `buffer_size` should be based on
the trade-off between performing extra work and causing a delay.

Note that `buffer_size` defines the size of the `queue.Queue` used to
communicate between threads. Therefore, the maximum number of items stored at
any one time is actually `buffer_size + 1`, since one additional item may be
stored in the local variable of the thread waiting on `Queue.put`.

The default value of `buffer_size` is set to 10000, as a trade-off between
protection against memory overflow, and avoiding processing delay. In some
cases, this default value may result in less efficient behavior of this
implementation compared to the concurrent.futures.Executor. This would
happen, for example, if the input of size 100,000 is produced slowly, the
entire output will be needed at once much later, and the entire input and
output can fit in memory. If the client was not sure if 100,000 items will
fit in memory, they might have kept the default value for `buffer_size`, and
suffered an unnecessary delay.

Setting `buffer_size` to 0 is not supported at present: it would increase
code complexity for no obvious use case. If it was supported, it would behave
the same as the built-in `map`, and eliminate the benefit of the worker pool.


## Implementation choices

A naive implementation of `Executor.map` that precisely imitates the regular
`map` would not be useful because it would submit each task to the worker
pool only when the client requests the corresponding result - defeating the
main reason to use executors.

An implementation that pre-processes a part of the input in advance, and then
gives the control back to the client, would be better: it would solve
problems 1 and 3. However, it would still block while it is acquiring the
specified number of inputs; this can take arbitrarily long time if the client
wants to pre-acquire many inputs and the input production is slow. Of course,
in the common case where the input is all in memory, this implementation is
good enough (since input production is instantaneous).

This implementation acquires the inputs in the background, and therefore does
not block at all.
