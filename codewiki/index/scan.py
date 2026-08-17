from __future__ import annotations

import fnmatch
import hashlib
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from ..config import Config, GENERATED_MARKERS, GENERATED_WEAK_MARKERS, TEST_DIR_NAMES


@dataclass
class FileRecord:
    path: str
    language: str
    lines: int
    sha256: str
    is_test: bool
    is_generated: bool
    package: str = ""


def _is_test_path(rel_path: str) -> bool:
    parts = rel_path.replace(os.sep, "/").split("/")
    if any(part.lower() in TEST_DIR_NAMES for part in parts[:-1]):
        return True
    stem = parts[-1].rsplit(".", 1)[0].lower()
    return stem.startswith("test_") or stem.endswith("_test") or ".test." in parts[-1].lower()


def _looks_generated(head: str) -> bool:
    prefixes = ("//", "/*", "*", "#", ";")
    for lineno, line in enumerate(head.splitlines()[:120], start=1):
        stripped = line.strip()
        if not stripped or not stripped.startswith(prefixes):
            continue
        lowered = stripped.lower()
        if any(marker in lowered for marker in GENERATED_MARKERS):
            return True
        if lineno <= 25 and any(marker in lowered for marker in GENERATED_WEAK_MARKERS):
            return True
    return False


def scan(root: str, config: Config) -> Tuple[List[FileRecord], Dict[str, int]]:
    root = os.path.abspath(root)
    excluded = set(config.exclude_dirs)
    records = []
    skipped = {"dir_excluded": 0, "glob_excluded": 0, "unknown_language": 0,
               "too_large": 0, "unreadable": 0}
    for dirpath, dirnames, filenames in os.walk(root):
        kept = [name for name in dirnames if name not in excluded and not name.startswith(".")]
        skipped["dir_excluded"] += len(dirnames) - len(kept)
        dirnames[:] = sorted(kept)
        for filename in sorted(filenames):
            if filename.startswith(".") or any(fnmatch.fnmatch(filename, glob) for glob in config.exclude_globs):
                if not filename.startswith("."):
                    skipped["glob_excluded"] += 1
                continue
            language = config.languages.get(os.path.splitext(filename)[1].lower())
            if language is None:
                skipped["unknown_language"] += 1
                continue
            path = os.path.join(dirpath, filename)
            try:
                if os.path.getsize(path) > config.max_file_bytes:
                    skipped["too_large"] += 1
                    continue
                with open(path, "rb") as stream:
                    raw = stream.read()
            except OSError:
                skipped["unreadable"] += 1
                continue
            if b"\x00" in raw[:2048]:
                skipped["unreadable"] += 1
                continue
            text = raw.decode("utf-8", errors="replace")
            generated = _looks_generated(text[:8192])
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            records.append(FileRecord(
                path=rel, language=language,
                lines=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
                sha256=hashlib.sha256(raw).hexdigest(), is_test=_is_test_path(rel),
                is_generated=generated,
            ))
    records.sort(key=lambda item: item.path)
    return records, skipped


def analyzable(records: List[FileRecord]) -> List[FileRecord]:
    return [record for record in records if record.language == "java"]


def read_text(root: str, rel_path: str) -> str:
    with open(os.path.join(root, rel_path), "rb") as stream:
        return stream.read().decode("utf-8", errors="replace")
