import time
from concurrent.futures import ThreadPoolExecutor
from itertools import count, islice

from streamexecutors import StreamThreadPoolExecutor

def produce():
    for i in range(100):
        time.sleep(0.02)
        yield i

def square(x):
    time.sleep(0.1)
    return x ** 2

def print10(iterable):
    print(list(islice(iterable, 10)))

# Doesn't block; time to completion 10 x (0.1 + 0.02) = 1.2 sec (sequential).
squares = map(square, produce())
print10(squares)

# Blocks for 100 x 0.02 = 2 sec; time to completion 2 + 0.1 (parallel) = 2.1 sec.
squares = ThreadPoolExecutor().map(square, produce())
print10(squares)

# Doesn't block; time to completion 10 x 0.02 (sequential) + 0.1 (parallel) = 0.3 sec.
squares = StreamThreadPoolExecutor().map(square, produce())
print10(squares)




