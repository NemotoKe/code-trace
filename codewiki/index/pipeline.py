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
from . import resolution, scan, supertypes, symbols


def _analyze_java_file(item):
    root, path, language, is_generated = item
    try:
        text = scan.read_text(root, path)
    except OSError:
        return path, None, [], [], []
    package = symbols.package_of(text)
    if is_generated:
        return path, package, [], [], []
    file_symbols = symbols.extract(path, language, text)
    file_imports = java_imports.parse_imports(path, text)
    file_supertypes = supertypes.extract(path, language, text, file_symbols)
    return path, package, file_symbols, file_imports, file_supertypes


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
    supertypes_found: int = 0
    supertype_outcomes: Dict[str, int] = None
    supertype_resolution_rate: float = 0.0


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
    java_records = [record for record in records if record.language == "java"]
    analysis_items = [
        (root, record.path, record.language, record.is_generated)
        for record in java_records
    ]
    analyzable_paths = {record.path for record in analyzable}
    with parallel.Mapper(parallel.resolve_jobs(jobs), len(java_records)) as mapper:
        analyses = mapper.map(_analyze_java_file, analysis_items)
        extracted = []
        parsed_imports = []
        supertype_refs = {}
        packages = {}
        for path, package, file_symbols, file_imports, file_refs in analyses:
            packages[path] = package
            if file_symbols:
                extracted.extend(file_symbols)
            if path in analyzable_paths:
                parsed_imports.append((path, file_imports))
            supertype_refs[path] = file_refs
        parallel_jobs = mapper.jobs
        del analyses
        del analysis_items
        del java_records
        del analyzable_paths

    for record in records:
        if record.language == "java":
            record.package = packages.get(record.path)
    extracted = sorted(extracted, key=lambda item: (
        item.path, item.line, item.name, item.kind, item.fqn, item.signature
    ))

    now = time.perf_counter()
    timings["symbols"] = round(now - previous, 3)
    previous = now

    emit("imports", "parsing Java imports")

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

    emit("supertypes", "resolving Java supertypes")
    supertype_rows = []
    file_packages = {record.path: record.package for record in records}
    for record in analyzable:
        for ref in supertype_refs.get(record.path, []):
            supertype_rows.append((ref, resolution.resolve_supertype(
                ref, file_packages, type_infos, imports_by_file, lookup=lookup
            )))
    supertype_outcomes = {
        outcome: 0 for outcome in resolution.TYPE_RESOLUTION_OUTCOMES
    }
    for _ref, supertype_resolution in supertype_rows:
        supertype_outcomes[supertype_resolution.outcome] = (
            supertype_outcomes.get(supertype_resolution.outcome, 0) + 1
        )
    supertype_resolved = supertype_outcomes.get("resolved", 0)
    supertype_unresolved = supertype_outcomes.get("unresolved", 0)
    supertype_denominator = supertype_resolved + supertype_unresolved
    supertype_rate = (
        float(supertype_resolved) / supertype_denominator
        if supertype_denominator else 0.0
    )
    now = time.perf_counter()
    timings["supertypes"] = round(now - previous, 3)
    previous = now

    emit("persist", "writing sqlite")
    db_path = os.path.join(out_dir, "index.sqlite3")
    db.write_index(
        db_path, root, records, extracted,
        skipped=_skipped, parallel_jobs=parallel_jobs,
        imports=import_rows, resolutions=resolution_rows,
        supertypes=supertype_rows,
    )
    now = time.perf_counter()
    timings["persist"] = round(now - previous, 3)
    timings["total"] = round(now - started, 3)
    emit("total", "index complete")
    return PipelineResult(
        db_path, len(records), len(analyzable), len(extracted), timings,
        _skipped, parallel_jobs, len(import_rows), import_forms,
        import_outcomes, internal_rate, len(supertype_rows),
        supertype_outcomes, supertype_rate,
    )
