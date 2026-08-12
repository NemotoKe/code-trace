from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from .. import parallel
from ..config import Config
from ..store import db
from . import scan, symbols


@dataclass
class PipelineResult:
    db_path: str
    files_scanned: int
    files_analyzed: int
    symbols_found: int
    timings: Dict[str, float]
    skipped: Dict[str, int]
    parallel_jobs: int


def run(root: str, out_dir: str, config: Optional[Config] = None,
        jobs: Optional[int] = None, progress: Optional[Callable] = None,
        timings: Optional[Dict[str, float]] = None) -> PipelineResult:
    root = os.path.abspath(root)
    out_dir = os.path.abspath(out_dir)
    config = config or Config()
    timings = timings if timings is not None else {}
    emit = progress or (lambda *_args: None)
    started = time.perf_counter()
    previous = started

    emit("scan", "scanning files")
    records, _skipped = scan.scan(root, config)
    analyzable = scan.analyzable(records)
    now = time.perf_counter()
    timings["scan"] = round(now - previous, 3)
    previous = now

    emit("symbols", "extracting symbols")
    with parallel.Mapper(parallel.resolve_jobs(jobs), len(analyzable)) as mapper:
        extracted = symbols.extract_all(root, analyzable, scan.read_text, mapper)
        parallel_jobs = mapper.jobs
    packages = {}
    for record in records:
        if record.language != "java":
            continue
        try:
            packages[record.path] = symbols.package_of(scan.read_text(root, record.path))
        except OSError:
            packages[record.path] = None
    for record in records:
        record.package = packages.get(record.path)
    extracted = sorted(extracted, key=lambda item: (
        item.path, item.line, item.name, item.kind, item.fqn, item.signature
    ))
    now = time.perf_counter()
    timings["symbols"] = round(now - previous, 3)
    previous = now

    emit("persist", "writing sqlite")
    db_path = os.path.join(out_dir, "index.sqlite3")
    db.write_index(
        db_path, root, records, extracted,
        skipped=_skipped, parallel_jobs=parallel_jobs,
    )
    now = time.perf_counter()
    timings["persist"] = round(now - previous, 3)
    timings["total"] = round(now - started, 3)
    emit("total", "index complete")
    return PipelineResult(
        db_path, len(records), len(analyzable), len(extracted), timings,
        _skipped, parallel_jobs,
    )
