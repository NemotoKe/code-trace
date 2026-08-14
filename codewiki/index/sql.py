from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .symbols import Symbol, strip_noise


@dataclass(frozen=True)
class SqlLiteral:
    path: str
    enclosing_fqn: str
    enclosing_kind: str
    line: int
    statement: str
    verb: str


@dataclass(frozen=True)
class _StringLiteral:
    start: int
    end: int
    content: str


_SQL_START = re.compile(
    r"^\s*(?P<verb>SELECT|INSERT|UPDATE|DELETE|MERGE)(?=\s)",
    re.IGNORECASE,
)
_REQUIRED_WORD = {
    "select": re.compile(r"(?<![A-Za-z0-9_$])FROM(?![A-Za-z0-9_$])",
                          re.IGNORECASE),
    "delete": re.compile(r"(?<![A-Za-z0-9_$])FROM(?![A-Za-z0-9_$])",
                          re.IGNORECASE),
    "update": re.compile(r"(?<![A-Za-z0-9_$])SET(?![A-Za-z0-9_$])",
                          re.IGNORECASE),
}
_INTO_SHAPE = re.compile(
    r"^\s*(?:INSERT|MERGE)\s+INTO(?![A-Za-z0-9_$])",
    re.IGNORECASE,
)
_METHOD_KINDS = {"method", "constructor"}
_TYPE_KINDS = {"class", "interface", "enum", "record", "annotation"}


def _is_escaped(text: str, position: int) -> bool:
    backslashes = 0
    position -= 1
    while position >= 0 and text[position] == "\\":
        backslashes += 1
        position -= 1
    return backslashes % 2 == 1


def _line_end(text: str, position: int) -> int:
    end = text.find("\n", position)
    return len(text) if end < 0 else end


def _is_text_block_opening(text: str, position: int) -> bool:
    if not text.startswith('"""', position) or _is_escaped(text, position):
        return False
    return not text[position + 3:_line_end(text, position)].strip()


def _text_block_end(text: str, start: int) -> int:
    position = text.find('"""', start)
    while position >= 0:
        if not _is_escaped(text, position):
            return position
        position = text.find('"""', position + 1)
    return -1


def _quoted_end(text: str, start: int, quote: str) -> int:
    position = start + 1
    while position < len(text):
        if text[position] == "\\":
            position += 2
        elif text[position] == quote:
            return position
        else:
            position += 1
    return -1


def _skip_comment(text: str, position: int) -> int:
    if text.startswith("//", position):
        end = text.find("\n", position + 2)
        return len(text) if end < 0 else end
    if text.startswith("/*", position):
        end = text.find("*/", position + 2)
        return len(text) if end < 0 else end + 2
    return position


def _comment_states(text: str) -> Dict[int, int]:
    """Record shared noise state at each physical line start."""
    states = {}
    noise_state = False
    offset = 0
    for raw_line in text.splitlines(True):
        line = raw_line.rstrip("\r\n")
        states[offset] = int(noise_state)
        _cleaned, noise_state = strip_noise(line, noise_state)
        offset += len(raw_line)
    return states


def _scan_literals(text: str) -> List[_StringLiteral]:
    """Scan Java strings while skipping comments, chars, and text block bodies."""
    literals = []
    comment_states = _comment_states(text)
    position = 0
    while position < len(text):
        if comment_states.get(position) == 1:
            end = text.find("*/", position)
            position = len(text) if end < 0 else end + 2
            continue
        if text.startswith("//", position) or text.startswith("/*", position):
            position = _skip_comment(text, position)
            continue

        char = text[position]
        if char == "'":
            end = _quoted_end(text, position, "'")
            position = len(text) if end < 0 else end + 1
            continue
        if char != '"':
            position += 1
            continue

        if _is_text_block_opening(text, position):
            end = _text_block_end(text, position + 3)
            if end < 0:
                break
            literals.append(_StringLiteral(
                position, end + 3, text[position + 3:end],
            ))
            position = end + 3
            continue

        end = _quoted_end(text, position, '"')
        if end < 0:
            break
        literals.append(_StringLiteral(position, end + 1,
                                       text[position + 1:end]))
        position = end + 1
    return literals


def _skip_gap(text: str, position: int) -> int:
    """Skip whitespace and comments between Java expression tokens."""
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        if text.startswith("//", position) or text.startswith("/*", position):
            next_position = _skip_comment(text, position)
            if next_position == position:
                break
            position = next_position
            continue
        break
    return position


def _joined_end(text: str, literals: List[_StringLiteral], start: int,
                by_start: Dict[int, int]) -> int:
    last = start
    position = literals[start].end
    while True:
        position = _skip_gap(text, position)
        if position >= len(text) or text[position] != "+":
            return last
        position = _skip_gap(text, position + 1)
        next_index = by_start.get(position)
        if next_index is None:
            return last
        last = next_index
        position = literals[last].end


def _enclosing(line: int, symbols: List[Symbol]) -> Tuple[str, str]:
    containing = [
        symbol for symbol in symbols
        if symbol.line <= line
        and (symbol.end_line is None or line <= symbol.end_line)
    ]

    methods = [symbol for symbol in containing
               if symbol.kind in _METHOD_KINDS]
    if methods:
        symbol = min(methods, key=_innermost_key)
        return symbol.fqn, "method"

    types = [symbol for symbol in containing
             if symbol.kind in _TYPE_KINDS]
    if types:
        symbol = min(types, key=_innermost_key)
        return symbol.fqn, symbol.kind
    return "", ""


def _innermost_key(symbol: Symbol):
    if symbol.end_line is None:
        span = float("inf")
    else:
        span = max(symbol.end_line - symbol.line, 0)
    return (span, -symbol.line, -len(symbol.fqn), symbol.fqn)


def _verb(statement: str) -> Optional[str]:
    match = _SQL_START.match(statement)
    return None if match is None else match.group("verb").lower()


def _has_sql_shape(statement: str, verb: str) -> bool:
    # Deliberately drop a known prefix that stops before FROM, SET, or INTO.
    # The fragment names no table/target, and dynamically assembled SQL is out
    # of scope; do not restore it merely because a later literal may complete it.
    if verb in ("insert", "merge"):
        return _INTO_SHAPE.match(statement) is not None
    required = _REQUIRED_WORD.get(verb)
    return required is not None and required.search(statement) is not None


def extract(rel_path: str, language: str, text: str,
            symbols: List[Symbol]) -> List[SqlLiteral]:
    if language != "java":
        return []

    literals = _scan_literals(text)
    by_start = {literal.start: index for index, literal in enumerate(literals)}
    consumed = set()
    result = []
    for index, literal in enumerate(literals):
        if index in consumed:
            continue
        verb = _verb(literal.content)
        if verb is None:
            continue

        last = _joined_end(text, literals, index, by_start)
        consumed.update(range(index, last + 1))
        statement = "".join(item.content for item in literals[index:last + 1])
        if not _has_sql_shape(statement, verb):
            continue
        line = text.count("\n", 0, literal.start) + 1
        enclosing_fqn, enclosing_kind = _enclosing(line, symbols)
        result.append(SqlLiteral(
            rel_path, enclosing_fqn, enclosing_kind, line, statement, verb,
        ))
    return result
