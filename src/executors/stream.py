import time
from queue import Queue
from concurrent.futures import Executor, ThreadPoolExecutor, ProcessPoolExecutor
from concurrent.futures.process import _get_chunks, _process_chunk
from traceback import print_stack
from functools import partial
from collections import deque
import sys
import threading
import itertools

class CancelledError(Exception):
    pass


class StreamExecutor(Executor):
    def map(self, fn, *iterables, timeout=None, chunksize=1, buffer_size=10000):
        """Returns an iterator equivalent to map(fn, iter).

        Args:
            fn: A callable that will take as many arguments as there are
                passed iterables.
            timeout: The maximum number of seconds to wait. If None, then there
                is no limit on the wait time.
            chunksize: The size of the chunks the iterable will be broken into
                before being passed to a child process. This argument is only
                used by ProcessPoolExecutor; it is ignored by
                ThreadPoolExecutor.
            buffer_size: The maximum number of input items that may be
                stored at once; default is a small buffer; 0 for no limit. The
                drawback of using a large buffer is the possibility of wasted
                computation and memory (in case not all input is needed), as
                well as higher peak memory usage.
        Returns:
            An iterator equivalent to: map(func, *iterables) but the calls may
            be evaluated out-of-order.

        Raises:
            TimeoutError: If the entire result iterator could not be generated
                before the given timeout.
            Exception: If fn(*args) raises for any values.
        """
        if timeout is None:
            end_time = None
        else:
            end_time = timeout + time.time()

        if buffer_size is None:
            buffer_size = -1

        iterators = [iter(iterable) for iterable in iterables]

        # Set to True to gracefully terminate all producers
        cancel = False

        # Deadlocks on the two queues are avoided using the following rule.
        # The writer guarantees to place a sentinel value into the buffer
        # before exiting, and to write nothing after that; the reader
        # guarantees to read the queue until it encounters a sentinel value
        # and to stop reading after that. Any value of type BaseException is
        # treated as a sentinel.
        future_buffer = Queue(maxsize=buffer_size)

        # This function will run in a separate thread.
        def consume_inputs():
            while True:
                if cancel:
                    future_buffer.put(CancelledError())
                    return
                try:
                    args = [next(iterator) for iterator in iterators]
                except BaseException as e:
                    # StopIteration represents exhausted input; any other
                    # exception is due to an error in the input generator. We
                    # forward the exception downstream so it can be raised
                    # when client iterates through the result of map.
                    future_buffer.put(e)
                    return
                try:
                    future = self.submit(fn, *args)
                except BaseException as e:
                    # E.g., RuntimeError from shut down executor.
                    # Forward the new exception downstream.
                    future_buffer.put(e)
                    return
                future_buffer.put(future)

        # This function will run in the main thread.
        def produce_results():
            def cleanup():
                nonlocal cancel
                cancel = True
                while True:
                    future = future_buffer.get()
                    if isinstance(future, BaseException):
                        break
                    else:
                        future.cancel()
                raise exc

            # Ensure cleanup happens even if client never starts this generator.
            try:
                yield None
            except GeneratorExit as exc:
                cleanup()
            while True:
                future = future_buffer.get()
                if isinstance(future, BaseException):
                    # Reraise upstream exceptions at the map call site.
                    raise future
                if end_time is None:
                    remaining_timeout = None
                else:
                    remaining_timeout = end_time - time.time()
                # Reraise new exceptions (errors in the callable fn, TimeOut,
                # GeneratorExit) at map call site, but also cancel upstream.
                try:
                    yield future.result(remaining_timeout)
                except BaseException as exc:
                    cleanup()

        thread = threading.Thread(target=consume_inputs)
        thread.start()
        # After map returns, admin_executor will be collected and shut down;
        # we don't care when since we never need to submit more tasks to it.
        result = produce_results()
        # Consume the dummy `None` result
        next(result)
        return result

class StreamThreadPoolExecutor(StreamExecutor, ThreadPoolExecutor): ...

class StreamProcessPoolExecutor(StreamExecutor, ProcessPoolExecutor):
    def map(self, fn, *iterables, timeout=None, chunksize=1, buffer_size=10000):
        if buffer_size is not None:
            buffer_size //= max(1, chunksize)
        if chunksize < 1:
            raise ValueError("chunksize must be >= 1.")
        results = super().map(partial(_process_chunk, fn),
                              _get_chunks(*iterables, chunksize=chunksize),
                              timeout=timeout, buffer_size=buffer_size)
        return itertools.chain.from_iterable(results)
