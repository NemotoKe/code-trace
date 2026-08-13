from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import List

from .symbols import Symbol, strip_noise


@dataclass(frozen=True)
class SupertypeRef:
    path: str
    owner_fqn: str
    line: int
    relation: str
    raw: str
    name: str


_DECLARATION_KEYWORDS = {
    "class": "class",
    "interface": "interface",
    "enum": "enum",
    "record": "record",
}
_WORD = re.compile(r"[A-Za-z_$][\w$]*")


def _mask_line(line: str, in_block: bool):
    """Blank Java noise while retaining every character column."""
    chars = list(line)
    index = 0
    length = len(line)
    while index < length:
        if in_block:
            end = line.find("*/", index)
            end = length if end < 0 else end + 2
            for position in range(index, end):
                chars[position] = " "
            index = end
            if end == length and not line.endswith("*/"):
                return "".join(chars), True
            in_block = False
            continue
        if line.startswith("//", index):
            for position in range(index, length):
                chars[position] = " "
            break
        if line.startswith("/*", index):
            end = line.find("*/", index + 2)
            end = length if end < 0 else end + 2
            for position in range(index, end):
                chars[position] = " "
            index = end
            if end == length and not line.endswith("*/"):
                return "".join(chars), True
            continue
        if line[index] in ('"', "'"):
            quote = line[index]
            position = index + 1
            while position < length:
                if line[position] == "\\":
                    position += 2
                elif line[position] == quote:
                    position += 1
                    break
                else:
                    position += 1
            for cursor in range(index, min(position, length)):
                chars[cursor] = " "
            index = position
            continue
        index += 1
    return "".join(chars), in_block


def _clean_lines(lines):
    """Use the shared noise rules and retain offsets for source slicing."""
    cleaned = []
    in_block = False
    for original in lines:
        stripped, next_in_block = strip_noise(original, in_block)
        if stripped == original and not in_block:
            cleaned.append(stripped)
        else:
            masked, _mask_in_block = _mask_line(original, in_block)
            cleaned.append(masked)
        in_block = next_in_block
    return cleaned


def _line_starts(lines):
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    return starts


def _declaration_position(clean_lines, symbol: Symbol, line_starts):
    keyword = _DECLARATION_KEYWORDS.get(symbol.kind)
    if keyword is None or symbol.line < 1 or symbol.line > len(clean_lines):
        return None
    line = clean_lines[symbol.line - 1]
    match = re.search(
        r"\b" + keyword + r"\s+" + re.escape(symbol.name) + r"\b", line
    )
    if match is None:
        return None
    return line_starts[symbol.line - 1] + match.start(), \
        line_starts[symbol.line - 1] + match.end()


def _next_word(source: str, start: int):
    match = _WORD.match(source, start)
    if match is None:
        return None, start
    return match.group(0), match.end()


def _find_clause(source: str, start: int):
    """Find a top-level extends/implements keyword before the body."""
    angle_depth = 0
    paren_depth = 0
    square_depth = 0
    index = start
    while index < len(source):
        char = source[index]
        if char == "<":
            angle_depth += 1
        elif char == ">" and angle_depth:
            angle_depth -= 1
        elif char == "(":
            paren_depth += 1
        elif char == ")" and paren_depth:
            paren_depth -= 1
        elif char == "[":
            square_depth += 1
        elif char == "]" and square_depth:
            square_depth -= 1
        elif char == "{" and not (angle_depth or paren_depth or square_depth):
            return None
        if not (angle_depth or paren_depth or square_depth):
            word, end = _next_word(source, index)
            if word == "extends":
                return "extends", end
            if word == "implements":
                return "implements", end
            if word is not None:
                index = end
                continue
        index += 1
    return None


def _skip_space(source: str, start: int) -> int:
    while start < len(source) and source[start].isspace():
        start += 1
    return start


def _read_types(source: str, start: int, stop_words):
    """Read comma-separated types and return values plus the stop offset."""
    values = []
    item_start = _skip_space(source, start)
    index = item_start
    angle_depth = 0
    paren_depth = 0
    square_depth = 0
    while index < len(source):
        char = source[index]
        if char == "<":
            angle_depth += 1
        elif char == ">" and angle_depth:
            angle_depth -= 1
        elif char == "(":
            paren_depth += 1
        elif char == ")" and paren_depth:
            paren_depth -= 1
        elif char == "[":
            square_depth += 1
        elif char == "]" and square_depth:
            square_depth -= 1
        elif char == "," and not (angle_depth or paren_depth or square_depth):
            _append_type(source, item_start, index, values)
            index = _skip_space(source, index + 1)
            item_start = index
            continue
        elif char == "{" and not (angle_depth or paren_depth or square_depth):
            break
        elif not (angle_depth or paren_depth or square_depth):
            word, end = _next_word(source, index)
            if word in stop_words:
                break
            if word is not None:
                index = end
                continue
        index += 1
    _append_type(source, item_start, index, values)
    return values, index


def _append_type(source: str, start: int, end: int, values) -> None:
    raw = source[start:end].strip()
    if not raw:
        return
    raw_start = start + len(source[start:end]) - len(source[start:end].lstrip())
    values.append((raw, raw_start))


def _name_without_type_arguments(raw: str) -> str:
    result = []
    angle_depth = 0
    for char in raw:
        if char == "<":
            angle_depth += 1
        elif char == ">" and angle_depth:
            angle_depth -= 1
        elif angle_depth == 0:
            result.append(char)
    return "".join(result).strip()


def extract(rel_path: str, language: str, text: str,
            symbols: List[Symbol]) -> List[SupertypeRef]:
    if language != "java":
        return []
    lines = text.splitlines()
    if not lines:
        return []

    clean_lines = _clean_lines(lines)
    clean_source = "\n".join(clean_lines)
    line_starts = _line_starts(clean_lines)
    ordered_symbols = []
    for symbol in symbols:
        position = _declaration_position(clean_lines, symbol, line_starts)
        if position is not None:
            ordered_symbols.append((position[0], symbol, position[1]))
    ordered_symbols.sort(key=lambda item: (item[0], item[1].fqn, item[1].kind))

    found = []
    sequence = 0
    for _declaration_start, symbol, declaration_end in ordered_symbols:
        scan_start = declaration_end
        while True:
            clause = _find_clause(clean_source, scan_start)
            if clause is None:
                break
            relation, type_start = clause
            stop_words = {"permits"}
            if relation == "extends":
                stop_words.add("implements")
            values, clause_end = _read_types(
                clean_source, type_start, stop_words
            )
            for raw, raw_start in values:
                line = bisect_right(line_starts, raw_start)
                found.append((
                    raw_start,
                    sequence,
                    SupertypeRef(
                        rel_path, symbol.fqn, line, relation, raw,
                        _name_without_type_arguments(raw),
                    ),
                ))
                sequence += 1
            if clause_end <= scan_start:
                break
            scan_start = clause_end

    found.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in found]
