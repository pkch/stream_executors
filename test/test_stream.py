from concurrent.futures import ThreadPoolExecutor
from  itertools import islice, count
from functools import partial
import time

import pytest

from executors import StreamExecutor

approx = partial(pytest.approx, abs=0.5)

class Timer:
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def elapsed(self):
        return time.perf_counter() - self.start

    def print(self):
        print('{:.2f} sec'.format(self.elapsed()))

    def __exit__(self, *args):
        self.print()

def produce(n=None, error=None):
    for i in count():
        if i == n:
            break
        if i == error:
            raise ValueError
        time.sleep(0.2)
        yield i

def process(i):
    s = time.perf_counter()
    time.sleep(0.1)
    # This will be in multiple threads.
    return i + 1


# Testing for deadlocks observed earlier
def test_unused_generator():
    executor = StreamExecutor(max_workers=2)
    gen = produce()
    executor.map(process, gen, buffer_size=10)
    # Delay to reproduce deadlock observed earlier
    # and to allow gc to collect result of map
    time.sleep(0.2)

    last_processed = None
    gen = produce()
    executor.map(process, gen, buffer_size=10)

    last_processed = None
    gen = produce()
    executor.map(process, gen, buffer_size=1)
    last_processed = None
    gen = produce()
    with StreamExecutor(max_workers=2) as executor:
        executor.map(process, gen, buffer_size=10)

def test_error():
    with StreamExecutor(max_workers=2) as executor:
        g = executor.map(process, produce(error=2))
        with pytest.raises(ValueError):
            list(g)

def test_timing():
    input_size = 10
    is_odd = lambda x: x%2

    #with Timer() as t:
        ## built-in map takes 0.1 * 40 + 0.5 = 4.5 sec
        #m = map(process, count())
        #g = islice(filter(is_odd, m), input_size)
        #time.sleep(0.5)
        ## only starts processing here
        #assert list(g) == list(range(1, 20, 2))
        #t.elapsed() == approx(4.5)

    #with Timer() as t:
        ## ThreadPoolExecutor.map hangs
        #executor = ThreadPoolExecutor(max_workers=10)
        #m = executor.map(process, count())

    with Timer() as t:
        # StreamExecutor.map takes 0.1 * 20 / 2 = 1 sec
        # starts processing here, without waiting for iteration
        executor = StreamExecutor(max_workers=2)
        m = executor.map(process, count())
        g = islice(filter(is_odd, m), input_size)
        assert t.elapsed() == approx(0)
        time.sleep(0.5)
        assert list(g) == list(range(1, 2*input_size, 2))
        assert t.elapsed() == approx(1)

    executor = StreamExecutor()
    with Timer() as t:
        print(list(islice(filter(None, executor.map(process, count())), input_size)))
        assert t.elapsed() == approx(0.1)

    with Timer() as t:
        it = islice(filter(None, executor.map(process, produce())), input_size)
        for x in it:
            t.elapsed() == approx(0.3)
            break
        for x in it:
            pass
        assert t.elapsed() == approx(2.2)

    with Timer() as t:
        it = islice(filter(None, executor.map(process, produce())), input_size)
        time.sleep(3)
        for x in it:
            break
        for x in it:
            pass
        assert t.elapsed() == approx(3)

