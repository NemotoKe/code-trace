import re
from typing import Optional, Tuple

from .symbols import Symbol


_MODIFIERS = frozenset({
    "public",
    "protected",
    "private",
    "static",
    "final",
    "abstract",
    "synchronized",
    "native",
    "default",
    "strictfp",
    "transient",
    "volatile",
})
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def _skip_space(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _read_identifier(text: str, position: int) -> Optional[Tuple[str, int]]:
    match = _IDENTIFIER.match(text, position)
    if match is None:
        return None
    return match.group(0), match.end()


def _read_qualified_name(
    text: str, position: int
) -> Optional[Tuple[str, int]]:
    first = _read_identifier(text, position)
    if first is None:
        return None

    parts = [first[0]]
    position = first[1]
    while True:
        after_name = position
        position = _skip_space(text, position)
        if position >= len(text) or text[position] != ".":
            return ".".join(parts), after_name
        position = _skip_space(text, position + 1)
        part = _read_identifier(text, position)
        if part is None:
            return None
        parts.append(part[0])
        position = part[1]


def _skip_balanced(
    text: str, position: int, opening: str, closing: str
) -> Optional[int]:
    depth = 0
    quote = None
    escaped = False

    while position < len(text):
        char = text[position]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            position += 1
            continue
        if char in ("'", '"'):
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1

    return None


def _skip_annotation(text: str, position: int) -> Optional[int]:
    if position >= len(text) or text[position] != "@":
        return None

    name = _read_qualified_name(text, position + 1)
    if name is None:
        return None
    position = _skip_space(text, name[1])
    if position < len(text) and text[position] == "(":
        position = _skip_balanced(text, position, "(", ")")
        if position is None:
            return None
    return position


def _skip_angle_group(text: str, position: int) -> Optional[int]:
    depth = 0
    quote = None
    escaped = False

    while position < len(text):
        char = text[position]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            position += 1
            continue
        if char in ("'", '"'):
            quote = char
        elif char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth == 0:
                return position + 1
        position += 1

    return None


def _read_return_type(
    text: str, position: int
) -> Optional[Tuple[str, int]]:
    qualified_name = _read_qualified_name(text, position)
    if qualified_name is None:
        return None

    type_name, position = qualified_name
    position = _skip_space(text, position)
    if position < len(text) and text[position] == "<":
        position = _skip_angle_group(text, position)
        if position is None:
            return None

    dimensions = []
    while True:
        bracket_start = _skip_space(text, position)
        if bracket_start >= len(text) or text[bracket_start] != "[":
            position = bracket_start
            break
        bracket_end = _skip_space(text, bracket_start + 1)
        if bracket_end >= len(text) or text[bracket_end] != "]":
            return None
        dimensions.append("[]")
        position = bracket_end + 1

    return type_name + "".join(dimensions), position


def return_type(symbol: Symbol) -> Optional[str]:
    """Return the declared return type name, or None when it cannot be read."""
    if symbol.kind != "method":
        return None

    text = symbol.signature
    position = 0
    while True:
        position = _skip_space(text, position)
        if position < len(text) and text[position] == "@":
            position = _skip_annotation(text, position)
            if position is None:
                return None
            continue
        identifier = _read_identifier(text, position)
        if identifier is not None and identifier[0] in _MODIFIERS:
            position = identifier[1]
            continue
        if position < len(text) and text[position] == "<":
            position = _skip_angle_group(text, position)
            if position is None:
                return None
            continue
        break

    position = _skip_space(text, position)
    parsed = _read_return_type(text, position)
    if parsed is None:
        return None
    type_name, position = parsed

    method_name = _read_identifier(text, _skip_space(text, position))
    if method_name is None:
        return None
    position = _skip_space(text, method_name[1])
    if position >= len(text) or text[position] != "(":
        return None
    return type_name
