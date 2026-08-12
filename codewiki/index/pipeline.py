from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from .. import parallel
from ..config import Config
from ..store import db
from . import imports as java_imports
from . import resolution, scan, symbols


@dataclass
class PipelineResult:
    db_path: str
    files_scanned: int
    files_analyzed: int
    symbols_found: int
    timings: Dict[str, float]
    skipped: Dict[str, int]
    parallel_jobs: int
    imports_found: int = 0
    import_forms: Dict[str, int] = None
    import_outcomes: Dict[str, int] = None
    internal_resolution_rate: float = 0.0


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

        emit("imports", "parsing Java imports")
        parsed_imports = java_imports.parse_all(
            root, analyzable, scan.read_text, mapper
        )
        parallel_jobs = mapper.jobs

    imports_by_file = dict(parsed_imports)
    import_rows = []
    type_infos = resolution.type_infos(extracted)
    package_names = [record.package for record in records if record.package]
    analyzable_package_names = [
        record.package for record in analyzable if record.package
    ]
    lookup = resolution.build_lookup(
        type_infos, package_names, analyzable_packages=analyzable_package_names
    )
    for record in analyzable:
        for item in imports_by_file[record.path]:
            import_rows.append((item, resolution.resolve_import(
                item, type_infos, package_names, lookup=lookup
            )))
    resolution_rows = resolution.build_resolutions(
        records, extracted, imports_by_file, lookup=lookup
    )
    import_forms = {form: 0 for form in java_imports.IMPORT_FORMS}
    import_outcomes = {outcome: 0 for outcome in resolution.IMPORT_OUTCOMES}
    for item, item_resolution in import_rows:
        import_forms[item.form] = import_forms.get(item.form, 0) + 1
        import_outcomes[item_resolution.outcome] = (
            import_outcomes.get(item_resolution.outcome, 0) + 1
        )
    resolved = import_outcomes.get("resolved", 0)
    unresolved = import_outcomes.get("unresolved", 0)
    internal_rate = float(resolved) / (resolved + unresolved) if resolved + unresolved else 0.0
    now = time.perf_counter()
    timings["imports"] = round(now - previous, 3)
    previous = now

    emit("persist", "writing sqlite")
    db_path = os.path.join(out_dir, "index.sqlite3")
    db.write_index(
        db_path, root, records, extracted,
        skipped=_skipped, parallel_jobs=parallel_jobs,
        imports=import_rows, resolutions=resolution_rows,
    )
    now = time.perf_counter()
    timings["persist"] = round(now - previous, 3)
    timings["total"] = round(now - started, 3)
    emit("total", "index complete")
    return PipelineResult(
        db_path, len(records), len(analyzable), len(extracted), timings,
        _skipped, parallel_jobs, len(import_rows), import_forms,
        import_outcomes, internal_rate,
    )
