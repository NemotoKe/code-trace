from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional

from .symbols import Symbol, _mask_annotations, strip_noise


@dataclass(frozen=True)
class CallSite:
    path: str
    enclosing_fqn: str
    enclosing_kind: str
    line: int
    form: str
    receiver: Optional[str]
    name: str


_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
_TYPE_ARGS = r"<[^(){};]*>"
_RECV_CALL = re.compile(
    r"(?<![.\w$])\b(?P<recv>" + _IDENT + r")\s*\.\s*"
    r"(?:(?P<type_args>" + _TYPE_ARGS + r"))?\s*"
    r"(?P<name>" + _IDENT + r")\s*\("
)
_BARE_CALL = re.compile(
    r"(?<![.\w$])(?P<name>" + _IDENT + r")\s*\("
)
_CHAIN_CALL = re.compile(
    r"\.\s*(?:(?P<type_args>" + _TYPE_ARGS + r"))?\s*"
    r"(?P<name>" + _IDENT + r")\s*\("
)
_METHOD_REF = re.compile(
    r"(?P<receiver>" + _IDENT + r")\s*::\s*(?P<name>" + _IDENT + r")"
)
_NEW = re.compile(
    r"\bnew\s+(?P<type>" + _IDENT + r"(?:\s*\.\s*" + _IDENT + r")*)"
    r"\s*(?:<[^(){};]*>)?\s*\("
)


_KEYWORDS = {
    "if", "while", "for", "switch", "catch", "synchronized", "return",
    "assert", "throw", "do", "else", "try", "case", "instanceof", "yield",
    "new", "this", "super", "throws", "break", "continue", "record", "var",
}

_TYPE_KINDS = {"class", "interface", "enum", "record", "annotation"}
_TYPE_KEYWORDS = {
    "class": "class",
    "interface": "interface",
    "enum": "enum",
    "record": "record",
    "annotation": "@interface",
}
_DECLARATION_WORDS = {
    "abstract", "default", "final", "native", "private", "protected", "public",
    "static", "strictfp", "synchronized", "transient", "volatile", "sealed",
    "non-sealed",
}
_NON_DECLARATION_WORDS = {
    "assert", "break", "case", "catch", "continue", "do", "else", "for", "if",
    "instanceof", "new", "return", "switch", "synchronized", "throw", "try",
    "while", "yield",
}


@dataclass(frozen=True)
class _Range:
    start: int
    end: int
    symbol: Symbol
    role: str


@dataclass(frozen=True)
class _MethodCandidate:
    position: int
    opening_paren: int
    body_opening: Optional[int]


class _RangeCursor:
    """Find containing ranges while positions advance through source order."""

    def __init__(self, ranges: List[_Range]):
        self.ranges = sorted(ranges, key=lambda item: (item.start, item.end))
        self.index = 0
        self.active = []

    def matches(self, position: int) -> List[_Range]:
        while self.index < len(self.ranges):
            item = self.ranges[self.index]
            if item.start > position:
                break
            self.active.append(item)
            self.index += 1
        self.active = [item for item in self.active if item.end > position]
        return [item for item in self.active if item.start <= position]


def _line_starts(lines: List[str]) -> List[int]:
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    return starts


def _clean_lines(text: str) -> List[str]:
    clean = []
    noise_state = False
    for line in text.splitlines():
        line, noise_state = strip_noise(line, noise_state)
        clean.append(line)
    return clean


def _brace_structure(source: str):
    pairs = {}
    stack = []
    depths = [0] * (len(source) + 1)
    for index, char in enumerate(source):
        depths[index] = len(stack)
        if char == "{":
            stack.append(index)
        elif char == "}" and stack:
            pairs[stack.pop()] = index
        depths[index + 1] = len(stack)
    return pairs, depths


def _matching_close(source: str, opening: int, left: str, right: str) -> int:
    depth = 0
    for index in range(opening, len(source)):
        char = source[index]
        if char == left:
            depth += 1
        elif char == right:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _matching_open(source: str, closing: int, left: str, right: str) -> int:
    depth = 0
    for index in range(closing, -1, -1):
        char = source[index]
        if char == right:
            depth += 1
        elif char == left:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _skip_type_args_before(source: str, position: int) -> int:
    index = position
    while index >= 0 and source[index].isspace():
        index -= 1
    if index < 0 or source[index] != ">":
        return index
    opening = _matching_open(source, index, "<", ">")
    if opening < 0:
        return index
    index = opening - 1
    while index >= 0 and source[index].isspace():
        index -= 1
    return index


def _chained_receiver(source: str, position: int) -> Optional[str]:
    index = _skip_type_args_before(source, position - 1)
    if index < 0 or source[index] != ".":
        return None

    index -= 1
    while index >= 0 and source[index].isspace():
        index -= 1
    if index < 0 or source[index] != ")":
        return None

    opening = _matching_open(source, index, "(", ")")
    if opening < 0:
        return None

    index = _skip_type_args_before(source, opening - 1)
    end = index + 1
    while index >= 0 and (source[index].isalnum()
                          or source[index] in "_$"):
        index -= 1
    start = index + 1
    if start == end or not (source[start].isalpha()
                            or source[start] in "_$"):
        return None
    if _after_new_qualified(source, start):
        return None
    return source[start:end]


def _next_body_opening(source: str, start: int) -> Optional[int]:
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            return index
        if char == ";":
            return None
    return None


def _line_end(source: str, line_start: int) -> int:
    end = source.find("\n", line_start)
    return len(source) if end < 0 else end


def _type_declaration_pattern(symbol: Symbol):
    keyword = _TYPE_KEYWORDS.get(symbol.kind)
    if keyword is None:
        return None
    prefix = (r"@interface\s+" if symbol.kind == "annotation"
              else r"\b" + re.escape(keyword) + r"\s+")
    return re.compile(r"(?:" + prefix + re.escape(symbol.name) + r"\b)")


def _type_ranges(source: str, structural: str, line_starts: List[int],
                 symbols: List[Symbol], pairs):
    ranges = []
    headers = []
    used = set()
    ordered = sorted(
        (symbol for symbol in symbols if symbol.kind in _TYPE_KINDS),
        key=lambda symbol: (symbol.line, symbol.fqn, symbol.kind),
    )
    for symbol in ordered:
        if symbol.line < 1 or symbol.line > len(line_starts):
            continue
        line_start = line_starts[symbol.line - 1]
        line_end = _line_end(source, line_start)
        pattern = _type_declaration_pattern(symbol)
        if pattern is None:
            continue
        match = None
        for candidate in pattern.finditer(source, line_start, line_end):
            if candidate.start() not in used:
                match = candidate
                break
        if match is None:
            continue
        declaration_start = match.start()
        used.add(declaration_start)
        opening = _next_body_opening(structural, match.end())
        if opening is None:
            continue
        closing = pairs.get(opening)
        if closing is None:
            closing = len(source)
        headers.append(_Range(declaration_start, opening + 1, symbol, "header"))
        ranges.append(_Range(opening + 1, closing, symbol, "body"))
    return ranges, headers


def _member_prefix(source: str, position: int) -> str:
    start = position
    while start > 0 and source[start - 1] not in "{};\n":
        start -= 1
    return source[start:position].strip()


def _looks_like_declaration(source: str, position: int, name: str,
                            owner: Symbol) -> bool:
    prefix = _member_prefix(source, position)
    if not prefix:
        return name == owner.name
    if "=" in prefix or "->" in prefix or "." in prefix:
        return False
    words = re.findall(_IDENT, prefix)
    if not words:
        return name == owner.name
    if words[-1] in _NON_DECLARATION_WORDS:
        return False
    if name == owner.name:
        return True
    return any(word not in _DECLARATION_WORDS for word in words)


def _method_candidates(source: str, line_start: int, name: str,
                       owner: Symbol, owner_range: _Range, depths, pairs):
    line_end = _line_end(source, line_start)
    pattern = re.compile(r"(?<![\w$])" + re.escape(name) + r"\s*\(")
    candidates = []
    owner_depth = depths[owner_range.start]
    for match in pattern.finditer(source, line_start, line_end):
        position = match.start()
        if not (owner_range.start <= position < owner_range.end):
            continue
        if depths[position] != owner_depth:
            continue
        if not _looks_like_declaration(source, position, name, owner):
            continue
        opening_paren = source.find("(", position, match.end())
        close_paren = _matching_close(source, opening_paren, "(", ")")
        if close_paren < 0:
            candidates.append(_MethodCandidate(position, opening_paren, None))
            continue
        body_opening = _next_body_opening(source, close_paren + 1)
        if body_opening is not None and body_opening not in pairs:
            body_opening = None
        candidates.append(_MethodCandidate(position, opening_paren, body_opening))
    return candidates


def _method_ranges(source: str, line_starts: List[int], symbols: List[Symbol],
                   type_ranges: List[_Range], depths, pairs):
    bodies = []
    headers = []
    groups = {}
    type_by_fqn = {item.symbol.fqn: item for item in type_ranges}
    for symbol in symbols:
        if symbol.kind not in ("method", "constructor"):
            continue
        if symbol.line < 1 or symbol.line > len(line_starts):
            continue
        owner_range = type_by_fqn.get(symbol.owner_fqn)
        if owner_range is None:
            continue
        key = (symbol.line, symbol.name, symbol.owner_fqn)
        entry = groups.get(key)
        if entry is None:
            candidates = _method_candidates(
                source, line_starts[symbol.line - 1], symbol.name,
                symbol, owner_range, depths, pairs,
            )
            entry = ([], candidates)
            groups[key] = entry
        entry[0].append(symbol)

    for symbols_group, candidates in groups.values():
        for symbol, candidate in zip(symbols_group, candidates):
            if candidate.body_opening is None:
                close = _matching_close(source, candidate.opening_paren, "(", ")")
                if close >= 0:
                    headers.append(_Range(candidate.position, close + 1,
                                          symbol, "header"))
                continue
            closing = pairs[candidate.body_opening]
            headers.append(_Range(candidate.position, candidate.body_opening + 1,
                                  symbol, "header"))
            bodies.append(_Range(candidate.body_opening + 1, closing,
                                 symbol, "body"))
    return bodies, headers


def _contains(item: _Range, position: int) -> bool:
    return item.start <= position < item.end


def _enclosing(position: int, line: int, methods: List[_Range],
               types: List[_Range], symbols: List[Symbol]):
    if methods:
        item = min(methods, key=lambda value: (value.end - value.start, -value.start))
        return item.symbol.fqn, "method"

    if types:
        item = min(types, key=lambda value: (value.end - value.start, -value.start))
        return item.symbol.fqn, item.symbol.kind

    containing = [
        symbol for symbol in symbols
        if symbol.line <= line
        and (symbol.end_line is None or line <= symbol.end_line)
    ]
    methods = [symbol for symbol in containing
               if symbol.kind in ("method", "constructor")]
    if methods:
        symbol = max(methods, key=lambda value: (value.line, value.fqn))
        return symbol.fqn, "method"
    types = [symbol for symbol in containing if symbol.kind in _TYPE_KINDS]
    if types:
        symbol = max(types, key=lambda value: (value.line, value.fqn))
        return symbol.fqn, symbol.kind
    return "", ""


def _is_chain_call(source: str, dot_position: int) -> bool:
    index = dot_position - 1
    while index >= 0 and source[index].isspace():
        index -= 1
    if index < 0 or not (source[index].isalnum() or source[index] in "_$"):
        return True
    while index >= 0 and (source[index].isalnum() or source[index] in "_$"):
        index -= 1
    return index >= 0 and source[index] == "."


def _after_new(source: str, position: int) -> bool:
    end = position
    while end > 0 and source[end - 1].isspace():
        end -= 1
    start = end - 3
    if start < 0 or source[start:end] != "new":
        return False
    return start == 0 or not (source[start - 1].isalnum()
                              or source[start - 1] in "_$")


def _after_new_qualified(source: str, position: int) -> bool:
    if _after_new(source, position):
        return True

    index = position - 1
    while True:
        while index >= 0 and source[index].isspace():
            index -= 1
        if index < 0 or source[index] != ".":
            return False
        index -= 1
        while index >= 0 and source[index].isspace():
            index -= 1
        end = index + 1
        while index >= 0 and (source[index].isalnum()
                              or source[index] in "_$"):
            index -= 1
        start = index + 1
        if start == end or not (source[start].isalpha()
                                or source[start] in "_$"):
            return False
        if _after_new(source, start):
            return True


def extract(rel_path: str, language: str, text: str,
            symbols: List[Symbol]) -> List[CallSite]:
    if language != "java":
        return []
    lines = _clean_lines(text)
    if not lines:
        return []

    line_starts = _line_starts(lines)
    clean_source = "\n".join(lines)
    structural = _mask_annotations(clean_source)
    pairs, depths = _brace_structure(structural)
    type_ranges, type_headers = _type_ranges(
        clean_source, structural, line_starts, symbols, pairs,
    )
    method_ranges, method_headers = _method_ranges(
        structural, line_starts, symbols, type_ranges, depths, pairs,
    )
    headers = type_headers + method_headers

    events = []
    qualified_call_positions = set()
    for match in _NEW.finditer(structural):
        type_name = match.group("type").split(".")[-1].strip()
        events.append((match.start(), 0, "constructor", None, type_name))

    for match in _RECV_CALL.finditer(structural):
        position = match.start("name")
        if _after_new(structural, match.start("recv")):
            continue
        name = match.group("name")
        if name in _KEYWORDS:
            continue
        if match.group("type_args") is not None:
            qualified_call_positions.add(position)
        events.append((position, 1, "receiver", match.group("recv"), name))

    for match in _CHAIN_CALL.finditer(structural):
        position = match.start("name")
        if not _is_chain_call(structural, match.start()):
            continue
        name = match.group("name")
        if name in _KEYWORDS:
            continue
        if match.group("type_args") is not None:
            qualified_call_positions.add(position)
        receiver = _chained_receiver(structural, position)
        events.append((position, 3, "chained", receiver, name))

    for match in _BARE_CALL.finditer(structural):
        position = match.start()
        name = match.group("name")
        if (name in _KEYWORDS or position in qualified_call_positions
                or _after_new(structural, position)):
            continue
        events.append((position, 2, "bare", None, name))

    for match in _METHOD_REF.finditer(structural):
        position = match.start("name")
        receiver = match.group("receiver")
        name = match.group("name")
        if name == "new":
            events.append((position, 0, "constructor", None, receiver))
            continue
        if name in _KEYWORDS:
            continue
        events.append((position, 4, "method_ref", receiver, name))

    events.sort(key=lambda event: (event[0], event[1]))
    type_cursor = _RangeCursor(type_ranges)
    header_cursor = _RangeCursor(headers)
    method_cursor = _RangeCursor(method_ranges)
    result = []
    for position, _priority, form, receiver, name in events:
        types = type_cursor.matches(position)
        if not types or header_cursor.matches(position):
            continue
        methods = method_cursor.matches(position)
        line = bisect_right(line_starts, position)
        enclosing_fqn, enclosing_kind = _enclosing(
            position, line, methods, types, symbols,
        )
        result.append(CallSite(
            rel_path, enclosing_fqn, enclosing_kind, line, form, receiver, name,
        ))
    return result
