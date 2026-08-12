from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


IMPORT_FORMS = (
    "single",
    "wildcard",
    "static_single",
    "static_wildcard",
)


@dataclass(frozen=True)
class ImportRecord:
    """One Java import statement in repository source order.

    ``name`` is the normalized import name without a trailing ``.*``.  The
    stable ``form`` values are ``single``, ``wildcard``, ``static_single``,
    and ``static_wildcard``.
    """

    path: str
    line: int
    column: int
    raw: str
    name: str
    form: str
    is_static: bool
    is_wildcard: bool


def _mask_java_noise(source: str) -> str:
    """Blank comments and string/character literals while preserving offsets."""
    chars = list(source)
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char == "/" and index + 1 < length:
            next_char = source[index + 1]
            if next_char == "/":
                end = source.find("\n", index)
                end = length if end < 0 else end
                for position in range(index, end):
                    chars[position] = " "
                index = end
                continue
            if next_char == "*":
                end = source.find("*/", index + 2)
                end = length if end < 0 else end + 2
                for position in range(index, end):
                    if source[position] != "\n":
                        chars[position] = " "
                index = end
                continue
        if char == '"' and source.startswith('"""', index):
            end = source.find('"""', index + 3)
            end = length if end < 0 else end + 3
            for position in range(index, end):
                if source[position] != "\n":
                    chars[position] = " "
            index = end
            continue
        if char in ('"', "'"):
            quote = char
            position = index + 1
            while position < length:
                if source[position] == "\\":
                    position += 2
                    continue
                if source[position] == quote:
                    position += 1
                    break
                position += 1
            for cursor in range(index, min(position, length)):
                if source[cursor] != "\n":
                    chars[cursor] = " "
            index = position
            continue
        index += 1
    return "".join(chars)


_IMPORT = re.compile(
    r"(?<![A-Za-z0-9_$])import\s+(?P<static>static\s+)?"
    r"(?P<name>[A-Za-z_$][\w$]*(?:\s*\.\s*"
    r"(?:[A-Za-z_$][\w$]*|\*))*)[ \t]*(?:;[ \t]*|(?=\r?$))",
    re.MULTILINE,
)


def parse_imports(path: str, text: str) -> List[ImportRecord]:
    """Parse Java imports without interpreting comments or literals."""
    masked = _mask_java_noise(text)
    records = []
    for match in _IMPORT.finditer(masked):
        line_start = masked.rfind("\n", 0, match.start()) + 1
        prefix = masked[line_start:match.start()].rstrip()
        if prefix and not prefix.endswith(";"):
            continue
        static = match.group("static") is not None
        normalized = re.sub(r"\s*\.\s*", ".", match.group("name"))
        wildcard = normalized.endswith(".*")
        if wildcard:
            normalized = normalized[:-2]
        form = ("static_" if static else "") + ("wildcard" if wildcard else "single")
        start = match.start()
        import_start = start
        semicolon = masked.find(";", start, match.end())
        raw_end = semicolon + 1 if semicolon >= 0 else match.end()
        records.append(ImportRecord(
            path=path,
            line=text.count("\n", 0, import_start) + 1,
            column=import_start - text.rfind("\n", 0, import_start),
            raw=text[import_start:raw_end].strip(),
            name=normalized,
            form=form,
            is_static=static,
            is_wildcard=wildcard,
        ))
    return records


def _job(item):
    root, rel_path, reader = item
    try:
        return parse_imports(rel_path, reader(root, rel_path))
    except OSError:
        return []


def parse_all(root: str, files, reader, mapper=None):
    """Parse imports in file order, optionally using a shared Mapper."""
    files = list(files)
    items = [(root, record.path, reader) for record in files]
    if mapper is not None:
        batches = mapper.map(_job, items)
    else:
        batches = [_job(item) for item in items]
    return [(record.path, parsed) for record, parsed in zip(files, batches)]


parse = parse_imports
