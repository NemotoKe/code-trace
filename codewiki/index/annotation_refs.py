from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import List, Optional

from .supertypes import _mask_line
from .symbols import Symbol, _annotation_end, _mask_annotations, strip_noise


@dataclass(frozen=True)
class AnnotationRef:
    path: str
    owner_fqn: str
    owner_kind: str
    name: str
    line: int
    raw: str


_TYPE_KINDS = {"class", "interface", "enum", "record", "annotation"}
_METHOD_KINDS = {"method", "constructor"}
_ANNOTATION_NAME = re.compile(
    r"@[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*"
)


@dataclass(frozen=True)
class _Occurrence:
    start: int
    end: int
    name: str
    line: int
    raw: str


def _line_starts(lines: List[str]) -> List[int]:
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    return starts


def _clean_lines(lines: List[str]) -> List[str]:
    """Mask comments and literals while retaining source offsets."""
    clean = []
    noise_state = False
    for original in lines:
        stripped, next_noise_state = strip_noise(original, noise_state)
        if stripped == original and not noise_state:
            clean.append(stripped)
        else:
            masked, _ = _mask_line(original, noise_state)
            clean.append(masked)
        noise_state = next_noise_state
    return clean


def _raw_annotation(text: str, start: int, end: int,
                    name_end: int) -> str:
    """Return the source annotation, normalizing only multiline whitespace."""
    raw_end = end
    argument_start = name_end
    while argument_start < len(text) and text[argument_start].isspace():
        argument_start += 1
    if argument_start >= len(text) or text[argument_start] != "(":
        raw_end = name_end
    raw = text[start:raw_end]
    if "\n" in raw or "\r" in raw:
        return " ".join(raw.split())
    return raw


def _find_annotations(text: str, structural: str,
                      line_starts: List[int]) -> List[_Occurrence]:
    occurrences = []
    position = 0
    while True:
        start = structural.find("@", position)
        if start < 0:
            break
        match = _ANNOTATION_NAME.match(structural, start)
        if match is None:
            position = start + 1
            continue
        end = _annotation_end(structural, start)
        if end < 0:
            position = start + 1
            continue
        name = match.group(0)[1:]
        position = end
        # @interface is Java's annotation-type declaration syntax, not an
        # annotation written on that declaration.
        if name == "interface":
            continue
        occurrences.append(_Occurrence(
            start=start,
            end=end,
            name=name,
            line=bisect_right(line_starts, start),
            raw=_raw_annotation(text, start, end, match.end()),
        ))
    return occurrences


def _type_anchor(line: str, symbol: Symbol) -> Optional[int]:
    if symbol.kind == "annotation":
        pattern = r"@interface\s+" + re.escape(symbol.name) + r"\b"
    else:
        pattern = (r"\b" + re.escape(symbol.kind) + r"\s+"
                   + re.escape(symbol.name) + r"\b")
    match = re.search(pattern, line)
    return match.start() if match is not None else None


def _method_anchor(line: str, symbol: Symbol) -> Optional[int]:
    # Keep offsets intact while hiding annotations, so a method name in an
    # annotation argument cannot be mistaken for the declaration name.
    declaration = _mask_annotations(line)
    pattern = re.compile(
        r"(?<![A-Za-z0-9_$])" + re.escape(symbol.name) + r"\s*\("
    )
    match = pattern.search(declaration)
    return match.start() if match is not None else None


def _declaration_anchor(lines: List[str], line_starts: List[int],
                        symbol: Symbol) -> Optional[int]:
    if symbol.line < 1 or symbol.line > len(lines):
        return None
    line = lines[symbol.line - 1]
    if symbol.kind in _TYPE_KINDS:
        offset = _type_anchor(line, symbol)
    elif symbol.kind in _METHOD_KINDS:
        offset = _method_anchor(line, symbol)
    else:
        return None
    if offset is None:
        return None
    return line_starts[symbol.line - 1] + offset


def _segment_start(masked_source: str, anchor: int) -> int:
    boundary = max(
        masked_source.rfind(";", 0, anchor),
        masked_source.rfind("{", 0, anchor),
        masked_source.rfind("}", 0, anchor),
    )
    return boundary + 1


def extract(rel_path: str, language: str, text: str,
            symbols: List[Symbol]) -> List[AnnotationRef]:
    if language != "java":
        return []
    lines = text.splitlines()
    if not lines:
        return []

    line_starts = _line_starts(lines)
    clean_lines = _clean_lines(lines)
    structural = "\n".join(clean_lines)
    occurrences = _find_annotations(text, structural, line_starts)
    if not occurrences:
        return []

    # Mask annotation spans before looking for declaration boundaries; braces
    # or semicolons in annotation arguments are not source-level boundaries.
    boundary_source = _mask_annotations(structural)
    ordered_symbols = []
    for symbol in symbols:
        anchor = _declaration_anchor(clean_lines, line_starts, symbol)
        if anchor is not None:
            ordered_symbols.append((anchor, symbol))
    ordered_symbols.sort(key=lambda item: (
        item[0], item[1].fqn, item[1].kind, item[1].name,
    ))

    occurrence_starts = [occurrence.start for occurrence in occurrences]
    found = []
    for symbol_order, (anchor, symbol) in enumerate(ordered_symbols):
        segment_start = _segment_start(boundary_source, anchor)
        first = bisect_left(occurrence_starts, segment_start)
        last = bisect_left(occurrence_starts, anchor)
        for occurrence in occurrences[first:last]:
            if occurrence.end > anchor:
                continue
            found.append((occurrence.start, symbol_order, AnnotationRef(
                path=rel_path,
                owner_fqn=symbol.fqn,
                owner_kind=symbol.kind,
                name=occurrence.name,
                line=occurrence.line,
                raw=occurrence.raw,
            )))

    found.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in found]
