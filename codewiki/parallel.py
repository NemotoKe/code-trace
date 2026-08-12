from __future__ import annotations

import multiprocessing
import os
from typing import Callable, List, Optional, Sequence


MIN_FILES = 400
CHUNK = 32
MAX_JOBS = 8


def resolve_jobs(requested: Optional[int]) -> int:
    if requested is not None:
        return max(1, requested)
    return min(os.cpu_count() or 1, MAX_JOBS)


class Mapper:
    def __init__(self, jobs: int = 1, workload: int = 0):
        self.jobs = jobs if jobs > 1 and workload >= MIN_FILES else 1
        self._pool = None

    def __enter__(self) -> "Mapper":
        if self.jobs > 1:
            try:
                self._pool = multiprocessing.Pool(self.jobs)
            except (OSError, ValueError, ImportError, NotImplementedError):
                self.jobs = 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._pool is not None:
            if exc_type is None:
                self._pool.close()
            else:
                self._pool.terminate()
            self._pool.join()
            self._pool = None
        return False

    def map(self, func: Callable, items: Sequence) -> List:
        values = list(items)
        if self._pool is None or not values:
            return [func(item) for item in values]
        return self._pool.map(func, values, CHUNK)

