"""Checks for safe Python 3.14-compatible lifter process scheduling."""
import importlib.util
import multiprocessing as mp
from pathlib import Path
import sys
import unittest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "liftpool.py"
SPEC = importlib.util.spec_from_file_location("liftpool", TOOL)
pool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pool)

calls = []


def _setup(value):
    calls.append(value)


def _square(value):
    return value * value


class TestLiftPool(unittest.TestCase):
    def test_single_worker_has_no_processes(self):
        before = {p.pid for p in mp.active_children()}
        with pool.lift_pool(1, initializer=_setup, initargs=(42,)) as workers:
            self.assertEqual(workers.map(_square, [1, 2, 3], chunksize=2), [1, 4, 9])
            self.assertEqual(list(workers.imap_unordered(_square, [4, 5], chunksize=1)), [16, 25])
            self.assertIn(42, calls)
        after = {p.pid for p in mp.active_children()}
        self.assertEqual(before, after)

    @unittest.skipUnless("fork" in mp.get_all_start_methods(), "Linux fork required")
    def test_multiple_workers_use_explicit_context(self):
        with pool.lift_pool(2) as workers:
            self.assertEqual(sorted(workers.map(_square, [1, 2, 3, 4])), [1, 4, 9, 16])

    def test_zero_workers_rejected(self):
        with self.assertRaises(ValueError):
            pool.lift_pool(0)


if __name__ == "__main__":
    unittest.main()
