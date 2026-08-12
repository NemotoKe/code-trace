from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


MAX_SIGNATURE = 200
# HAPI's largest observed Java file is 8078 lines.  Keep a finite upper bound
# for corrupt or unterminated input while leaving comfortable room for valid
# large type bodies.
MAX_BODY_SCAN_LINES = 10000


@dataclass
class Symbol:
    path: str
    name: str
    kind: str
    fqn: str
    owner_fqn: Optional[str]
    package: Optional[str]
    params: Optional[List[str]]
    param_count: Optional[int]
    signature: str
    line: int
    end_line: Optional[int]
    confidence: str


_QUALIFIED_NAME = r"[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*"
_ANNOTATION = r"@" + _QUALIFIED_NAME + r"(?:\s*\([^)]*\))?"
_JAVA_TYPES = [
    (re.compile(r"^\s*(?:" + _ANNOTATION + r"\s+)*(?:public|protected|private|abstract|final|static|sealed|non-sealed|strictfp|\s)*class\s+(?P<name>[A-Za-z_$][\w$]*)"), "class"),
    (re.compile(r"^\s*(?:" + _ANNOTATION + r"\s+)*(?:public|protected|private|abstract|sealed|\s)*interface\s+(?P<name>[A-Za-z_$][\w$]*)"), "interface"),
    (re.compile(r"^\s*(?:" + _ANNOTATION + r"\s+)*(?:public|protected|private|\s)*enum\s+(?P<name>[A-Za-z_$][\w$]*)"), "enum"),
    (re.compile(r"^\s*(?:" + _ANNOTATION + r"\s+)*(?:public|protected|private|final|sealed|\s)*record\s+(?P<name>[A-Za-z_$][\w$]*)"), "record"),
    (re.compile(r"^\s*(?:" + _ANNOTATION + r"\s+)*(?:public|protected|private|abstract|\s)*@interface\s+(?P<name>[A-Za-z_$][\w$]*)"), "annotation"),
]


# The reference implementation deliberately keeps JVM matching conservative.  In
# particular, a type-like token before a call can otherwise turn `return foo()`
# into a declaration.  Keep these guards beside the adapted Java pattern because
# that regex trap is easy to reintroduce during future parser changes.
_JAVA_DECLARATION_KEYWORDS = (
    "return|throw|new|assert|yield|else|case|break|continue|if|while|for|"
    "switch|do|try|catch|import|package"
)

_JVM_LIKE = [
    # Measured failure: the continuation in
    # `retVal.putIfAbsent(..., new SpringBeanContainer(factory));` resembles
    # `Type Name(...);`. Keep the leading keyword exclusion and [ \t] whitespace
    # here: widening it to `\s` risks swallowing a preceding return/throw while
    # backtracking. The helper below handles arbitrary horizontal whitespace
    # after `new`, including spaces left when a block comment is stripped.
    (re.compile(
        r"^[ \t]*(?:(?:" + _ANNOTATION + r"|"
        r"public|protected|private|static|final|abstract|synchronized|native|"
        r"default|strictfp)[ \t]+)*"
        r"(?:<[^{}()]*>[ \t]+)?"
        r"(?!(?:" + _JAVA_DECLARATION_KEYWORDS + r")\b)"
        r"[A-Za-z_$][\w$<>\[\],.?]*(?:[ \t]+[\w$<>\[\],.?]+)*"
        r"[ \t]+(?<!new )(?P<name>[A-Za-z_$][\w$]*)[ \t]*\("
    ), "method"),
]


def _jvm_match(text: str):
    """Match a declaration after removing annotations with balanced arguments."""
    candidate = _remove_annotations(text)
    match = _JVM_LIKE[0][0].match(candidate)
    if match is not None and re.search(
            r"\bnew[ \t]+$", candidate[:match.start("name")]):
        return None
    return match


def strip_noise(line: str, in_block: bool = False) -> Tuple[str, bool]:
    """Remove Java strings/comments so braces in prose cannot close a body."""
    if not in_block and not any(token in line for token in ("/", '"', "'")):
        return line, False
    out = []
    index = 0
    while index < len(line):
        if in_block:
            end = line.find("*/", index)
            if end < 0:
                return "".join(out), True
            index = end + 2
            in_block = False
            continue
        if line.startswith("//", index):
            break
        if line.startswith("/*", index):
            in_block = True
            index += 2
            continue
        if line[index] in ('"', "'"):
            quote = line[index]
            index += 1
            while index < len(line):
                if line[index] == "\\":
                    index += 2
                elif line[index] == quote:
                    index += 1
                    break
                else:
                    index += 1
            out.append(" ")
            continue
        out.append(line[index])
        index += 1
    return "".join(out), in_block


def _mask_annotations(text: str) -> str:
    """Blank annotation text without changing offsets used by brace scans."""
    chars = list(text)
    index = 0
    while index < len(text):
        if text[index] == "@":
            end = _annotation_end(text, index)
            if end >= 0:
                for position in range(index, end):
                    if chars[position] != "\n":
                        chars[position] = " "
                index = end
                continue
        index += 1
    return "".join(chars)


def _brace_body_end(lines: List[str], start_index: int, memo=None) -> Optional[int]:
    depth = 0
    found = False
    in_block = False
    for index in range(start_index, min(len(lines), start_index + MAX_BODY_SCAN_LINES)):
        text, in_block = strip_noise(lines[index], in_block)
        text = _mask_annotations(text)
        for char in text:
            if char == "{":
                depth += 1
                found = True
            elif char == "}" and found:
                depth -= 1
                if depth == 0:
                    return index + 1
        if not found and ";" in text:
            return index + 1
    return None


def _brace_body_span(lines: List[str], start_index: int, start_offset: int,
                     allow_semicolon: bool = True):
    """Return the closing line/offset for a declaration body.

    This is the character-aware companion to `_brace_body_end`; it is needed for
    multiple declarations that legally share one physical Java source line.
    """
    depth = 0
    seen_brace = False
    for index in range(start_index, min(len(lines), start_index + MAX_BODY_SCAN_LINES)):
        text = _mask_annotations(lines[index])
        offset = start_offset if index == start_index else 0
        for position in range(offset, len(text)):
            char = text[position]
            if char == "{":
                depth += 1
                seen_brace = True
            elif char == "}" and seen_brace:
                depth -= 1
                if depth == 0:
                    return index + 1, position
        if allow_semicolon and not seen_brace and ";" in text[offset:]:
            return index + 1, len(text)
    return None, None


def _contains_type(item, lineno: int, offset: int) -> bool:
    if lineno < item[2]:
        return False
    if lineno == item[2] and offset <= item[6]:
        return False
    if item[3] is None:
        return True
    if lineno > item[3]:
        return False
    return not (lineno == item[3] and offset > item[7])


def _containing_types(types, lineno: int, offset: int):
    return [item for item in types if _contains_type(item, lineno, offset)]


def _method_header(header: str, type_names) -> bool:
    header = _remove_annotations(header)
    match = re.search(
        r"([A-Za-z_$][\w$]*)\s*\([^{};]*\)\s*"
        r"(?:throws\s+[A-Za-z_$][\w$.,\s<>\[\]?]*)?$",
        header,
        re.S,
    )
    if match is None:
        return False
    name = match.group(1)
    if name in {"if", "for", "while", "switch", "catch", "synchronized", "new"}:
        return False
    prefix = header[:match.start(1)].strip()
    return bool(prefix) or name in type_names


def _method_body_ranges(lines: List[str], type_names):
    source = "\n".join(lines)
    pairs = _brace_pairs(source)
    ranges = []
    for opening, closing in pairs:
        start = max(
            source.rfind("{", 0, opening),
            source.rfind("}", 0, opening),
            source.rfind(";", 0, opening),
        ) + 1
        if _method_header(source[start:opening].strip(), type_names):
            ranges.append((opening + 1, closing))
    return ranges


def _brace_pairs(source: str):
    source = _mask_annotations(source)
    pairs = []
    stack = []
    for index, char in enumerate(source):
        if char == "{":
            stack.append(index)
        elif char == "}" and stack:
            pairs.append((stack.pop(), index))
    return pairs


def _type_body_ranges(lines: List[str], types, line_starts=None):
    source = "\n".join(lines)
    structural = _mask_annotations(source)
    pairs = dict(_brace_pairs(source))
    if line_starts is None:
        line_starts = _line_starts(lines)
    ranges = []
    for item in types:
        if item[3] is None:
            continue
        start = _absolute_offset(lines, item[2], item[4], line_starts)
        opening = structural.find("{", start)
        closing = pairs.get(opening)
        if opening >= 0 and closing is not None:
            ranges.append((opening + 1, closing))
    return ranges


def _non_member_block_ranges(lines: List[str], types, method_ranges,
                             line_starts=None):
    """Find initializer/control bodies that cannot contain member types."""
    source = "\n".join(lines)
    structural = _mask_annotations(source)
    type_openings = set()
    if line_starts is None:
        line_starts = _line_starts(lines)
    for item in types:
        start = _absolute_offset(lines, item[2], item[4], line_starts)
        opening = structural.find("{", start)
        if opening >= 0:
            type_openings.add(opening)
    method_openings = {start - 1 for start, _end in method_ranges}
    ranges = []
    for opening, closing in _brace_pairs(source):
        if opening not in type_openings and opening not in method_openings:
            ranges.append((opening + 1, closing))
    return ranges


def _line_starts(lines: List[str]) -> List[int]:
    starts = [0]
    for line in lines[:-1]:
        starts.append(starts[-1] + len(line) + 1)
    return starts


def _absolute_offset(lines: List[str], lineno: int, offset: int,
                     line_starts=None) -> int:
    if line_starts is None:
        return sum(len(line) + 1 for line in lines[:lineno - 1]) + offset
    return line_starts[lineno - 1] + offset


_DELIMITER_PAIRS = {"(": ")", "[": "]", "{": "}", "<": ">"}


def _balanced_delimiter_end(text: str, open_index: int) -> int:
    """Return the exclusive end of a balanced delimiter expression."""
    stack = []
    quote = None
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char in _DELIMITER_PAIRS:
            stack.append(char)
        elif char in _DELIMITER_PAIRS.values():
            if not stack or _DELIMITER_PAIRS[stack[-1]] != char:
                return -1
            stack.pop()
            if not stack:
                return index + 1
    return -1


def _split_parameters(body: str) -> Optional[List[str]]:
    """Split parameters while validating all nested Java delimiters."""
    items = []
    start = 0
    stack = []
    quote = None
    escaped = False
    for index, char in enumerate(body):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char in _DELIMITER_PAIRS:
            stack.append(char)
        elif char in _DELIMITER_PAIRS.values():
            if not stack or _DELIMITER_PAIRS[stack[-1]] != char:
                return None
            stack.pop()
        elif char == "," and not stack:
            items.append(body[start:index])
            start = index + 1
    if quote is not None or stack:
        return None
    items.append(body[start:])
    return items


def _annotation_end(text: str, start: int) -> int:
    match = re.match(
        r"@[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*)*", text[start:]
    )
    if match is None:
        return -1
    end = start + match.end()
    while end < len(text) and text[end].isspace():
        end += 1
    if end < len(text) and text[end] == "(":
        return _balanced_delimiter_end(text, end)
    return end


def _remove_annotations(text: str) -> str:
    """Remove qualified annotations, including balanced argument lists."""
    out = []
    index = 0
    while index < len(text):
        if text[index] == "@":
            end = _annotation_end(text, index)
            if end >= 0:
                index = end
                continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _strip_parameter_annotations(item: str) -> Optional[str]:
    out = []
    index = 0
    quote = None
    escaped = False
    while index < len(item):
        char = item[index]
        if quote is not None:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in ('"', "'"):
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "@":
            end = _annotation_end(item, index)
            if end < 0:
                return None
            index = end
            continue
        out.append(char)
        index += 1
    if quote is not None:
        return None
    return "".join(out)


def _parameter_type(item: str) -> Optional[str]:
    cleaned = _strip_parameter_annotations(item)
    if cleaned is None:
        return None
    cleaned = re.sub(r"\b(?:final|volatile|transient)\b", "", cleaned)
    tokens = " ".join(cleaned.split()).split()
    if len(tokens) < 2:
        return None

    name_token = tokens[-1]
    attached = re.fullmatch(
        r"(?P<name>[A-Za-z_$][\w$]*)(?P<arrays>(?:\[\])*)", name_token
    )
    if attached is not None:
        name_index = len(tokens) - 1
        array_count = len(attached.group("arrays")) // 2
        parameter_name = attached.group("name")
    else:
        name_index = len(tokens) - 1
        array_count = 0
        while name_index > 0 and re.fullmatch(r"\[\]", tokens[name_index]):
            array_count += 1
            name_index -= 1
        if name_index == len(tokens) - 1:
            return None
        parameter_name = tokens[name_index]
    if name_index == 0 or not re.fullmatch(r"[A-Za-z_$][\w$]*", parameter_name):
        return None

    parameter_type = " ".join(tokens[:name_index])
    parameter_type = re.sub(r"\s*\[\s*\]", "[]", parameter_type)
    parameter_type = re.sub(r"\s*\.\s*\.\s*\.\s*", "...", parameter_type)
    return parameter_type + "[]" * array_count


def _params(signature: str) -> Tuple[Optional[List[str]], Optional[int], str]:
    declaration = _remove_annotations(signature)
    open_index = declaration.find("(")
    close_index = _matching_close(declaration, open_index, "(", ")")
    if open_index < 0 or close_index < open_index:
        return None, None, "POSSIBLE"
    tail = declaration[close_index + 1:].lstrip()
    if tail.startswith(")"):
        return None, None, "POSSIBLE"
    body = declaration[open_index + 1:close_index].strip()
    if not body:
        return [], 0, "CONFIRMED"
    items = _split_parameters(body)
    if items is None:
        return None, None, "POSSIBLE"
    values = []
    for item in items:
        parameter_type = _parameter_type(item)
        if parameter_type is None:
            return None, None, "POSSIBLE"
        values.append(parameter_type)
    return values, len(values), "CONFIRMED"


def _matching_close(text: str, open_index: int, opening: str, closing: str) -> int:
    if open_index < 0:
        return -1
    depth = 0
    quote = None
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index
    return -1


def _same_line_signature(cleaned: str, start: int, name: str) -> str:
    candidate = _remove_annotations(cleaned[start:].lstrip())
    name_index = candidate.find(name)
    open_index = candidate.find("(", name_index + len(name))
    close_index = _matching_close(candidate, open_index, "(", ")")
    if close_index < 0:
        return candidate.strip()
    end = close_index + 1
    tail = candidate[end:]
    brace_index = tail.find("{")
    semicolon_index = tail.find(";")
    if brace_index >= 0 and (semicolon_index < 0 or brace_index < semicolon_index):
        body_start = end + brace_index
        body_end = _matching_close(candidate, body_start, "{", "}")
        if body_end >= 0:
            end = body_end + 1
    elif semicolon_index >= 0:
        end = semicolon_index + 1
    return candidate[:end].strip()


def _raw_signature(lines: List[str], start_index: int) -> str:
    parts = []
    balance = 0
    seen_parenthesis = False
    in_block = False
    for index in range(start_index, min(len(lines), start_index + MAX_BODY_SCAN_LINES)):
        cleaned, in_block = strip_noise(lines[index], in_block)
        parts.append(cleaned.strip())
        if not seen_parenthesis:
            declaration = _remove_annotations(cleaned)
            open_index = declaration.find("(")
            if open_index < 0:
                continue
            seen_parenthesis = True
            fragment = declaration[open_index:]
        else:
            fragment = cleaned
        balance += fragment.count("(") - fragment.count(")")
        if seen_parenthesis and balance <= 0:
            break
    return " ".join(part for part in parts if part)


def extract(rel_path: str, language: str, text: str) -> List[Symbol]:
    if language != "java":
        return []
    lines = text.splitlines()
    clean_lines = []
    in_block = False
    for original in lines:
        cleaned, in_block = strip_noise(original, in_block)
        clean_lines.append(cleaned)
    line_starts = _line_starts(clean_lines)
    package = None
    for line in clean_lines:
        match = re.match(r"^\s*package\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;", line)
        if match:
            package = match.group(1)
            break
    types = []
    symbols = []
    for lineno, original in enumerate(lines, start=1):
        line = clean_lines[lineno - 1]
        position = 0
        while position < len(line):
            found = False
            for regex, kind in _JAVA_TYPES:
                match = regex.match(line[position:])
                if not match:
                    continue
                name = match.group("name")
                end_line, end_offset = _brace_body_span(
                    clean_lines, lineno - 1, position, allow_semicolon=False
                )
                types.append((name, kind, lineno, end_line, position, end_offset))
                position += max(match.end(), 1)
                found = True
                break
            if not found:
                position += 1
    types.sort(key=lambda item: (item[2], item[4]))
    method_ranges = _method_body_ranges(clean_lines, {item[0] for item in types})
    non_member_ranges = _non_member_block_ranges(
        clean_lines, types, method_ranges, line_starts
    )
    local_types = [
        item for item in types
        if any(
            start <= _absolute_offset(
                clean_lines, item[2], item[4], line_starts
            ) < end
            for start, end in method_ranges + non_member_ranges
        )
    ]
    local_body_ranges = _type_body_ranges(clean_lines, local_types, line_starts)
    types = [
        item for item in types
        if item not in local_types
    ]
    qualified_types = []
    for name, kind, lineno, end_line, start_offset, end_offset in types:
        parents = _containing_types(qualified_types, lineno, start_offset)
        parent = max(parents, key=lambda item: (item[2], item[6])) if parents else None
        prefix = parent[4] if parent else package
        fqn = "%s.%s" % (prefix, name) if prefix else name
        qualified_types.append((name, kind, lineno, end_line, fqn,
                                parent[4] if parent else None, start_offset, end_offset))
    for name, kind, lineno, end_line, fqn, owner_fqn, _start_offset, _end_offset in qualified_types:
        symbols.append(Symbol(rel_path, name, kind, fqn, owner_fqn, package, None, None,
                              lines[lineno - 1].strip()[:MAX_SIGNATURE], lineno,
                              end_line, "CONFIRMED" if end_line is not None else "UNRESOLVED"))
    for lineno, original in enumerate(lines, start=1):
        line = clean_lines[lineno - 1]
        if not line.strip() or "(" not in line:
            continue
        if any(
            start <= _absolute_offset(clean_lines, lineno, 0, line_starts) < end
            for start, end in local_body_ranges
        ):
            continue
        if re.match(
                r"^\s*(?:return|throw|new|assert|yield|else|case|break|continue|"
                r"if|while|for|switch|do|try|catch|import|package)\b", line):
            continue
        containing = _containing_types(qualified_types, lineno, 0)
        if containing:
            owner = sorted(containing, key=lambda item: (item[2], item[6]))[-1]
        else:
            owner = None
        if owner is None:
            continue
        match = _jvm_match(line)
        name = match.group("name") if match else None
        if name is None:
            modifier = r"(?:" + _ANNOTATION + r"|public|protected|private|static|final|abstract|synchronized|strictfp)\s+"
            constructor = re.match(
                r"^\s*(?:" + modifier + r")*(?:<[^{}()]*>\s*)?" + re.escape(owner[0]) + r"\s*\(",
                _remove_annotations(line),
            )
            if constructor is None:
                continue
            name = owner[0]
        if name in {"if", "for", "while", "switch", "catch", "return", "new"}:
            continue
        declaration = _raw_signature(clean_lines, lineno - 1)
        params, count, confidence = _params(declaration)
        signature = declaration[:MAX_SIGNATURE]
        owner_fqn = owner[4]
        kind = "constructor" if name == owner[0] else "method"
        fqn = owner_fqn + "." + name
        symbols.append(Symbol(rel_path, name, kind, fqn, owner_fqn, package, params, count,
                              signature, lineno,
                              _brace_body_end(clean_lines, lineno - 1), confidence))

    # A legal Java declaration may follow a type/body separator on the same
    # physical line: `class A { void m() {} }`.  The line-anchored JVM regex
    # above intentionally avoids calls; this pass keeps that property by only
    # trying declaration candidates after `{`, `}`, `;`, or at line start.
    existing = {(symbol.name, symbol.kind, symbol.line, symbol.owner_fqn)
                for symbol in symbols}
    excluded = {"if", "for", "while", "switch", "catch", "return", "new",
                "throw", "assert", "yield", "else", "case", "break", "continue"}
    for lineno, original in enumerate(lines, start=1):
        line = clean_lines[lineno - 1]
        starts = [0] + [index + 1 for index, char in enumerate(line)
                        if char in "{};"]
        for start in starts:
            candidate = line[start:].lstrip()
            if not candidate or "(" not in candidate:
                continue
            actual_start = start + len(line[start:]) - len(candidate)
            absolute_start = _absolute_offset(
                clean_lines, lineno, actual_start, line_starts
            )
            if any(start <= absolute_start < end for start, end in local_body_ranges):
                continue
            first_word = re.match(r"[A-Za-z_$][\w$]*", candidate)
            if first_word is not None and first_word.group(0) in excluded:
                continue
            containing = _containing_types(qualified_types, lineno, actual_start)
            if not containing:
                continue
            owner = max(containing, key=lambda item: (item[2], item[6]))
            match = _jvm_match(candidate)
            name = match.group("name") if match else None
            if name is None:
                modifier = r"(?:" + _ANNOTATION + r"|public|protected|private|static|final|abstract|synchronized|strictfp)\s+"
                constructor = re.match(
                    r"^\s*(?:" + modifier + r")*(?:<[^{}()]*>\s*)?" + re.escape(owner[0]) + r"\s*\(",
                    _remove_annotations(candidate),
                )
                if constructor is None:
                    continue
                name = owner[0]
            if name in excluded:
                continue
            owner_fqn = owner[4]
            kind = "constructor" if name == owner[0] else "method"
            key = (name, kind, lineno, owner_fqn)
            if key in existing:
                continue
            declaration = _same_line_signature(line, actual_start, name)
            params, count, confidence = _params(declaration)
            signature = declaration[:MAX_SIGNATURE]
            end_line, _end_offset = _brace_body_span(
                clean_lines, lineno - 1, actual_start
            )
            symbols.append(Symbol(
                rel_path, name, kind, owner_fqn + "." + name, owner_fqn, package,
                params, count, signature, lineno, end_line, confidence,
            ))
            existing.add(key)
    symbols.sort(key=lambda item: (item.line, item.name, item.kind))
    return symbols


def _regex_symbols(rel_path: str, language: str, text: str) -> List[Symbol]:
    """Compatibility entry point for the reference regex extraction layer."""
    return extract(rel_path, language, text)


def package_of(text: str) -> Optional[str]:
    in_block = False
    for original in text.splitlines():
        line, in_block = strip_noise(original, in_block)
        match = re.match(r"^\s*package\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;", line)
        if match:
            return match.group(1)
    return None


def _job(item):
    root, rel_path, language, reader = item
    try:
        return extract(rel_path, language, reader(root, rel_path))
    except OSError:
        return []


def extract_all(root: str, files: List, reader, mapper=None) -> List[Symbol]:
    items = [(root, record.path, record.language, reader) for record in files]
    batches = mapper.map(_job, items) if mapper is not None else [_job(item) for item in items]
    result = []
    for batch in batches:
        result.extend(batch)
    return sorted(result, key=lambda item: (item.path, item.line, item.name, item.kind))
