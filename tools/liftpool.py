"""Bounded process pools for NFSU2 lifting in Linux and Codespaces.

Python 3.14 defaults to forkserver on POSIX, which can fail inside constrained
containers. One worker uses no subprocesses; more workers use explicit fork on
Linux rather than depending on the system-wide default.
"""
import multiprocessing as mp
import os


class SerialPool:
    def __init__(self, initializer=None, initargs=()):
        self.initializer = initializer
        self.initargs = initargs

    def __enter__(self):
        if self.initializer is not None:
            self.initializer(*self.initargs)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def map(self, fn, items, chunksize=None):
        return list(map(fn, items))

    def imap_unordered(self, fn, items, chunksize=1):
        return map(fn, items)


def lift_pool(workers, initializer=None, initargs=()):
    """Return a context-managed pool; one worker never forks/spawns."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    if workers == 1:
        return SerialPool(initializer, initargs)
    method = os.environ.get('NFSU2_MP_START_METHOD')
    if method is None:
        method = 'fork' if 'fork' in mp.get_all_start_methods() else mp.get_start_method()
    if method not in mp.get_all_start_methods():
        raise ValueError(f"Unsupported multiprocessing start method: {method}")
    return mp.get_context(method).Pool(
        workers, initializer=initializer, initargs=initargs)
