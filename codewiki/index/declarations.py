from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .symbols import Symbol, _mask_annotations, strip_noise
from .supertypes import _name_without_type_arguments


@dataclass(frozen=True)
class Declaration:
    path: str
    scope_fqn: str
    scope_kind: str
    name: str
    type_name: str
    line: int
    kind: str


_IDENT = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_TOKEN = re.compile(r"\.\.\.|[A-Za-z_$][A-Za-z0-9_$]*|\S")
_METHOD_KINDS = {"method", "constructor"}
_TYPE_KINDS = {"class", "interface", "enum", "record", "annotation"}

_MODIFIERS = {
    "abstract", "default", "final", "native", "private", "protected",
    "public", "sealed", "static", "strictfp", "synchronized", "transient",
    "volatile",
}

# These words cannot be the first word of a written variable type.  In
# particular, keeping `return` and `new` out prevents ordinary expressions from
# looking like `return Value name;` or `new Value name;` declarations.
_NOT_TYPE_WORDS = {
    "assert", "break", "case", "catch", "class", "continue", "do", "else",
    "enum", "extends", "for", "if", "implements", "import", "instanceof",
    "interface", "new", "package", "record", "return", "super", "switch",
    "this", "throw", "throws", "try", "var", "while", "yield",
}

_DECLARATION_BOUNDARIES = {"(", ")", ":", ";", "{", "}"}
_DECLARATION_ENDS = {",", ")", ";", ":", "="}


def _clean_lines(text: str) -> List[str]:
    lines = []
    noise_state = False
    for original in text.splitlines():
        cleaned, noise_state = strip_noise(original, noise_state)
        lines.append(cleaned)
    return lines


def _line_starts(lines: List[str]) -> List[int]:
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    return starts


def _tokens(source: str) -> List[Tuple[str, int, int]]:
    return [
        (match.group(0), match.start(), match.end())
        for match in _TOKEN.finditer(source)
    ]


def _is_identifier(token: str) -> bool:
    return _IDENT.fullmatch(token) is not None


def _matching_angle(tokens: List[Tuple[str, int, int]], start: int) -> int:
    depth = 0
    for index in range(start, len(tokens)):
        token = tokens[index][0]
        if token == "<":
            depth += 1
        elif token == ">":
            if depth == 0:
                return -1
            depth -= 1
            if depth == 0:
                return index
    return -1


def _type_end(
    tokens: List[Tuple[str, int, int]], start: int, allow_varargs: bool = True
) -> Optional[int]:
    """Return the token after a simple Java written type."""
    if start >= len(tokens) or not _is_identifier(tokens[start][0]):
        return None
    if tokens[start][0] in _NOT_TYPE_WORDS or tokens[start][0] in _MODIFIERS:
        return None

    index = start + 1
    while index < len(tokens):
        if tokens[index][0] == ".":
            if index + 1 >= len(tokens) or not _is_identifier(tokens[index + 1][0]):
                return None
            index += 2
            continue
        if tokens[index][0] == "<":
            close = _matching_angle(tokens, index)
            if close < 0:
                return None
            index = close + 1
            continue
        break

    while index + 1 < len(tokens) and tokens[index][0] == "[":
        if tokens[index + 1][0] != "]":
            return None
        index += 2
    if allow_varargs and index < len(tokens) and tokens[index][0] == "...":
        index += 1
    return index


def _normalise_type(raw: str, suffix: str = "") -> Optional[str]:
    raw = re.sub(
        r"^(?:\s*(?:final|volatile|transient)\s+)+", "", raw,
    )
    raw = raw.strip() + suffix
    if not raw.strip():
        return None

    # The project has one rule for removing written type arguments.  Keep the
    # small amount of surrounding whitespace cleanup here so array markers stay
    # in the form the source uses semantically (`String[]`).
    value = _name_without_type_arguments(raw)
    value = re.sub(r"\s*\[\s*\]", "[]", value)
    value = re.sub(r"\s*\.\s*\.\s*\.\s*", "...", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value or value == "var":
        return None
    if value.startswith("?") or "=" in value:
        return None
    return value


class _ScopeCursor:
    """Answer line-range scope queries while source positions advance."""

    def __init__(self, symbols: List[Symbol]):
        self._symbols = sorted(
            (symbol for symbol in symbols
             if symbol.kind in _METHOD_KINDS | _TYPE_KINDS),
            key=lambda symbol: (symbol.line, symbol.fqn, symbol.kind),
        )
        self._index = 0
        self._active = []
        self._line = 0

    def at(self, line: int):
        if line < self._line:
            # The extractor asks in source order, but retain a correct fallback
            # if a caller ever supplies a non-monotone symbol stream.
            self._index = 0
            self._active = []
        self._line = line
        while (self._index < len(self._symbols)
               and self._symbols[self._index].line <= line):
            self._active.append(self._symbols[self._index])
            self._index += 1
        self._active = [
            symbol for symbol in self._active
            if symbol.end_line is None or line <= symbol.end_line
        ]
        methods = [
            symbol for symbol in self._active if symbol.kind in _METHOD_KINDS
        ]
        if methods:
            return min(
                methods,
                key=lambda symbol: (
                    (symbol.end_line if symbol.end_line is not None else 10 ** 9)
                    - symbol.line,
                    -symbol.line,
                    symbol.fqn,
                ),
            ), "method"
        types = [symbol for symbol in self._active if symbol.kind in _TYPE_KINDS]
        if types:
            return min(
                types,
                key=lambda symbol: (
                    (symbol.end_line if symbol.end_line is not None else 10 ** 9)
                    - symbol.line,
                    -symbol.line,
                    symbol.fqn,
                ),
            ), None
        return None, None


def _method_header_candidate(
    source: str, position: int, symbol: Symbol
) -> bool:
    boundary = max(
        source.rfind("\n", 0, position),
        source.rfind("{", 0, position),
        source.rfind("}", 0, position),
        source.rfind(";", 0, position),
    ) + 1
    prefix = source[boundary:position].strip()
    if not prefix:
        return symbol.kind == "constructor"
    if any(mark in prefix for mark in ("=", "->", ".")):
        return False
    words = _IDENT.findall(prefix)
    if not words:
        return False
    if words[0] in {"if", "for", "while", "switch", "catch", "return", "new"}:
        return False
    if words[-1] == symbol.name and symbol.kind != "constructor":
        return False
    return True


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


def _method_parameter_spans(
    source: str, line_starts: List[int], symbols: List[Symbol]
) -> List[Tuple[Symbol, int, int]]:
    structural = _mask_annotations(source)
    found = []
    grouped = {}
    for symbol in symbols:
        if symbol.kind not in _METHOD_KINDS:
            continue
        if symbol.line < 1 or symbol.line > len(line_starts):
            continue
        grouped.setdefault(
            (symbol.line, symbol.name, symbol.owner_fqn), []
        ).append(symbol)

    for group in grouped.values():
        symbol = group[0]
        start = line_starts[symbol.line - 1]
        line_end = structural.find("\n", start)
        if line_end < 0:
            line_end = len(structural)
        pattern = re.compile(
            r"(?<![\w$])" + re.escape(symbol.name) + r"\s*\("
        )
        candidates = []
        for match in pattern.finditer(structural, start, line_end):
            if not _method_header_candidate(structural, match.start(), symbol):
                continue
            opening = structural.find("(", match.start(), match.end())
            closing = _matching_close(structural, opening, "(", ")")
            if closing < 0:
                continue
            candidates.append((opening, closing))
            # A declaration is always the first header-like occurrence after the
            # symbol's line.  The bounded break also avoids searching a whole
            # method body for a recursive call with the same name.
            if len(candidates) >= len(group):
                break
        for index, item in enumerate(group):
            if index < len(candidates):
                opening, closing = candidates[index]
                found.append((item, opening + 1, closing))
    return found


def _brace_pairs(source: str):
    pairs = {}
    stack = []
    for index, char in enumerate(source):
        if char == "{":
            stack.append(index)
        elif char == "}" and stack:
            pairs[stack.pop()] = index
    return pairs


def _next_body_opening(source: str, start: int) -> Optional[int]:
    opening = source.find("{", start)
    semicolon = source.find(";", start)
    if opening < 0 or (semicolon >= 0 and semicolon < opening):
        return None
    return opening


def _type_declaration_pattern(symbol: Symbol):
    if symbol.kind == "annotation":
        prefix = r"@interface\s+"
    elif symbol.kind in _TYPE_KINDS:
        prefix = r"\b" + re.escape(symbol.kind) + r"\s+"
    else:
        return None
    return re.compile(prefix + re.escape(symbol.name) + r"\b")


def _type_body_ranges(
    source: str, line_starts: List[int], symbols: List[Symbol], pairs
):
    ranges = []
    used = set()
    ordered = sorted(
        (symbol for symbol in symbols if symbol.kind in _TYPE_KINDS),
        key=lambda symbol: (symbol.line, symbol.fqn, symbol.kind),
    )
    for symbol in ordered:
        if symbol.line < 1 or symbol.line > len(line_starts):
            continue
        pattern = _type_declaration_pattern(symbol)
        if pattern is None:
            continue
        start = line_starts[symbol.line - 1]
        line_end = source.find("\n", start)
        if line_end < 0:
            line_end = len(source)
        match = None
        for candidate in pattern.finditer(source, start, line_end):
            if candidate.start() not in used:
                match = candidate
                break
        if match is None:
            continue
        used.add(match.start())
        opening = _next_body_opening(source, match.end())
        closing = pairs.get(opening)
        if opening is not None and closing is not None:
            ranges.append((opening + 1, closing, symbol, symbol.kind))
    return ranges


def _method_body_ranges(source: str, method_spans, pairs):
    ranges = []
    for symbol, _parameter_start, parameter_close in method_spans:
        opening = _next_body_opening(source, parameter_close + 1)
        closing = pairs.get(opening)
        if opening is not None and closing is not None:
            ranges.append((opening + 1, closing, symbol, "method"))
    return ranges


class _PositionRangeCursor:
    def __init__(self, ranges):
        self._ranges = sorted(ranges, key=lambda item: (item[0], item[1]))
        self._index = 0
        self._active = []
        self._position = -1

    def containing(self, position: int):
        if position < self._position:
            self._index = 0
            self._active = []
        self._position = position
        while (self._index < len(self._ranges)
               and self._ranges[self._index][0] <= position):
            self._active.append(self._ranges[self._index])
            self._index += 1
        self._active = [
            item for item in self._active if position < item[1]
        ]
        if not self._active:
            return None
        return min(self._active, key=lambda item: (item[1] - item[0], -item[0]))


class _ScopeIndex:
    def __init__(self, source: str, line_starts: List[int],
                 symbols: List[Symbol], method_spans):
        pairs = _brace_pairs(source)
        self._method_cursor = _PositionRangeCursor(
            _method_body_ranges(source, method_spans, pairs)
        )
        self._type_cursor = _PositionRangeCursor(
            _type_body_ranges(source, line_starts, symbols, pairs)
        )
        self._line_cursor = _ScopeCursor(symbols)

    def at(self, position: int, line: int):
        item = self._method_cursor.containing(position)
        if item is not None:
            return item[2], item[3]
        item = self._type_cursor.containing(position)
        if item is not None:
            return item[2], item[3]
        return self._line_cursor.at(line)


def _split_top_level(
    source: str, start: int, end: int
) -> List[Tuple[int, int]]:
    spans = []
    item_start = start
    angle = paren = bracket = brace = 0
    index = start
    while index < end:
        char = source[index]
        if char == "<":
            angle += 1
        elif char == ">" and angle:
            angle -= 1
        elif char == "(":
            paren += 1
        elif char == ")" and paren:
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]" and bracket:
            bracket -= 1
        elif char == "{":
            brace += 1
        elif char == "}" and brace:
            brace -= 1
        elif char == "," and not (angle or paren or bracket or brace):
            spans.append((item_start, index))
            item_start = index + 1
        index += 1
    spans.append((item_start, end))
    return spans


def _typed_span(
    source: str, start: int, end: int
) -> Optional[Tuple[int, str, str]]:
    tokens = _tokens(source[start:end])
    if not tokens:
        return None
    identifiers = [
        token for token in tokens
        if _is_identifier(token[0]) and token[0] not in _MODIFIERS
    ]
    if not identifiers:
        return None
    variable = identifiers[-1]
    if variable[0] in _NOT_TYPE_WORDS:
        return None
    absolute_variable_start = start + variable[1]
    absolute_variable_end = start + variable[2]
    suffix = source[absolute_variable_end:end]
    if not re.fullmatch(r"\s*(?:\[\s*\]\s*)*", suffix):
        return None
    raw_type = source[start:absolute_variable_start]
    type_name = _normalise_type(raw_type, suffix)
    if type_name is None:
        return None
    return absolute_variable_start, variable[0], type_name


def _skip_initializer(
    tokens: List[Tuple[str, int, int]], start: int
) -> int:
    paren = bracket = brace = angle = 0
    index = start
    while index < len(tokens):
        token = tokens[index][0]
        if token == "(":
            paren += 1
        elif token == ")":
            if paren:
                paren -= 1
            elif not (bracket or brace or angle):
                return index
        elif token == "[":
            bracket += 1
        elif token == "]" and bracket:
            bracket -= 1
        elif token == "{":
            brace += 1
        elif token == "}" and brace:
            brace -= 1
        elif token == "<":
            angle += 1
        elif token == ">" and angle:
            angle -= 1
        elif token == ";" and not (paren or bracket or brace or angle):
            return index
        elif token == "," and not (paren or bracket or brace or angle):
            return index
        index += 1
    return index


def _declaration_start(
    tokens: List[Tuple[str, int, int]], index: int
) -> bool:
    if index == 0:
        return True
    previous = index - 1
    while previous >= 0 and tokens[previous][0] in _MODIFIERS:
        previous -= 1
    return previous < 0 or tokens[previous][0] in _DECLARATION_BOUNDARIES


def _parse_regular_declaration(
    source: str, tokens: List[Tuple[str, int, int]], index: int
) -> List[Tuple[int, str, str]]:
    if not _declaration_start(tokens, index):
        return []
    type_end = _type_end(tokens, index, allow_varargs=False)
    if type_end is None or type_end >= len(tokens):
        return []
    variable_index = type_end
    if not _is_identifier(tokens[variable_index][0]):
        return []
    if tokens[variable_index][0] in _NOT_TYPE_WORDS:
        return []

    after = variable_index + 1
    array_end = after
    while array_end + 1 < len(tokens):
        if tokens[array_end][0] != "[" or tokens[array_end + 1][0] != "]":
            break
        array_end += 2
    if array_end >= len(tokens):
        return []
    if tokens[array_end][0] not in _DECLARATION_ENDS:
        return []

    raw_type = source[tokens[index][1]:tokens[type_end - 1][2]]
    suffix = source[tokens[variable_index][2]:tokens[array_end][1]]
    type_name = _normalise_type(raw_type, suffix)
    if type_name is None:
        return []

    result = [
        (tokens[variable_index][1], tokens[variable_index][0], type_name)
    ]
    cursor = array_end
    while cursor < len(tokens):
        token = tokens[cursor][0]
        if token == "=":
            cursor = _skip_initializer(tokens, cursor + 1)
            if cursor >= len(tokens) or tokens[cursor][0] != ",":
                break
        elif token != ",":
            break
        cursor += 1
        if cursor >= len(tokens) or not _is_identifier(tokens[cursor][0]):
            break
        variable = tokens[cursor]
        if variable[0] in _NOT_TYPE_WORDS:
            break
        after_variable = cursor + 1
        array_after = after_variable
        while array_after + 1 < len(tokens):
            if (tokens[array_after][0] != "["
                    or tokens[array_after + 1][0] != "]"):
                break
            array_after += 2
        if array_after >= len(tokens):
            break
        if tokens[array_after][0] not in _DECLARATION_ENDS:
            break
        variable_suffix = source[variable[2]:tokens[array_after][1]]
        variable_type = _normalise_type(raw_type, variable_suffix)
        if variable_type is None:
            break
        result.append((variable[1], variable[0], variable_type))
        cursor = array_after
    return result


def _in_span(position: int, spans: List[Tuple[int, int]],
             starts: List[int]) -> bool:
    index = bisect_right(starts, position) - 1
    return index >= 0 and position < spans[index][1]


def extract(rel_path: str, language: str, text: str,
            symbols: List[Symbol]) -> List[Declaration]:
    if language != "java":
        return []
    lines = _clean_lines(text)
    if not lines:
        return []

    line_starts = _line_starts(lines)
    source = _mask_annotations("\n".join(lines))
    token_list = _tokens(source)

    found = []
    parameter_spans = []
    method_spans = _method_parameter_spans(source, line_starts, symbols)
    for symbol, start, end in method_spans:
        parameter_spans.append((start, end))
        for item_start, item_end in _split_top_level(source, start, end):
            parsed = _typed_span(source, item_start, item_end)
            if parsed is None:
                continue
            position, name, type_name = parsed
            line = bisect_right(line_starts, position)
            found.append((
                position,
                0,
                Declaration(
                    rel_path, symbol.fqn, "method", name, type_name,
                    line, "parameter",
                ),
            ))

    parameter_spans.sort()
    parameter_starts = [item[0] for item in parameter_spans]
    scope_index = _ScopeIndex(source, line_starts, symbols, method_spans)
    for index in range(len(token_list)):
        parsed = _parse_regular_declaration(source, token_list, index)
        if not parsed:
            continue
        for position, name, type_name in parsed:
            if _in_span(position, parameter_spans, parameter_starts):
                continue
            line = bisect_right(line_starts, position)
            scope, scope_kind = scope_index.at(position, line)
            if scope is None:
                continue
            kind = "local" if scope_kind == "method" else "field"
            found.append((
                position,
                1,
                Declaration(
                    rel_path, scope.fqn, scope_kind or scope.kind,
                    name, type_name, line, kind,
                ),
            ))

    found.sort(key=lambda item: (item[0], item[1], item[2].name,
                                 item[2].type_name, item[2].kind))
    return [item[2] for item in found]
