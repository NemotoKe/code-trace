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
class TableAccess:
    table: str
    access: str


@dataclass(frozen=True)
class ColumnWrite:
    table: str
    column: str


@dataclass(frozen=True)
class ColumnRead:
    table: str
    column: str


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


_TABLE_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
_TABLE_IDENTIFIER_PATTERN = re.compile(_TABLE_IDENTIFIER)
_DOUBLE_QUOTED_TABLE_IDENTIFIER_PATTERN = re.compile(
    rf'"({_TABLE_IDENTIFIER})"',
)
_BACKTICK_QUOTED_TABLE_IDENTIFIER_PATTERN = re.compile(
    rf'`({_TABLE_IDENTIFIER})`',
)
_BRACKET_QUOTED_TABLE_IDENTIFIER_PATTERN = re.compile(
    rf'\[({_TABLE_IDENTIFIER})\]',
)
_FROM_WORD = re.compile(
    r"(?<![A-Za-z0-9_$])FROM(?![A-Za-z0-9_$])", re.IGNORECASE,
)
_SELECT_WORD = re.compile(
    r"SELECT(?![A-Za-z0-9_$])", re.IGNORECASE,
)
_INTO_WORD = re.compile(
    r"(?<![A-Za-z0-9_$])INTO(?![A-Za-z0-9_$])", re.IGNORECASE,
)
_SET_WORD = re.compile(
    r"(?<![A-Za-z0-9_$])SET(?![A-Za-z0-9_$])", re.IGNORECASE,
)
_WHERE_WORD = re.compile(
    r"(?<![A-Za-z0-9_$])WHERE(?![A-Za-z0-9_$])", re.IGNORECASE,
)
_ASSIGNMENT_EQUALS = re.compile(r"(?<![<>=!])=(?!=)")
_USING_WORD = re.compile(
    r"(?<![A-Za-z0-9_$])USING(?![A-Za-z0-9_$])", re.IGNORECASE,
)
_SOURCE_CONTROL = re.compile(
    r",|(?<![A-Za-z0-9_$])(?:JOIN|ON|WHERE|GROUP|ORDER|HAVING|LIMIT|"
    r"UNION|EXCEPT|INTERSECT|RETURNING)(?![A-Za-z0-9_$])",
    re.IGNORECASE,
)
_SOURCE_CLAUSES = frozenset({
    "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "UNION",
    "EXCEPT", "INTERSECT", "RETURNING",
})
_SQL_TABLE_KEYWORDS = frozenset({
    "ALL", "ALTER", "AND", "ANY", "AS", "ASC", "BEGIN", "BETWEEN",
    "BY", "CASE", "CHECK", "COMMIT", "CONSTRAINT", "CREATE", "CROSS",
    "CURRENT", "CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP",
    "DATABASE", "DEFAULT", "DELETE", "DESC", "DISTINCT", "DROP", "ELSE",
    "DUAL", "END", "EXCEPT", "EXISTS", "FETCH", "FOR", "FOREIGN", "FROM",
    "FULL", "GROUP", "HAVING", "IN", "INDEX", "INNER", "INSERT",
    "INTERSECT", "INTO", "IS", "JOIN", "KEY", "LEFT", "LIKE", "LIMIT",
    "MERGE", "NOT", "NULL", "OFFSET", "ON", "OR", "ORDER", "OUTER",
    "OVER", "PARTITION", "PRIMARY", "REFERENCES", "RETURNING", "RIGHT",
    "ROLLBACK", "SELECT", "SET", "TABLE", "THEN", "TRUNCATE", "UNION",
    "UNIQUE", "UPDATE", "USING", "VALUE", "VALUES", "WHEN", "WHERE",
    "WITH", "NATURAL",
})


def _statement_start(statement: str, verb: str) -> Optional[int]:
    match = re.match(
        rf"^\s*{re.escape(verb)}(?![A-Za-z0-9_$])",
        statement,
        re.IGNORECASE,
    )
    return None if match is None else match.end()


def _table_segment_after(statement: str, position: int
                         ) -> Optional[Tuple[str, int]]:
    match = _TABLE_IDENTIFIER_PATTERN.match(statement, position)
    if match is not None:
        name = match.group(0)
        if name.startswith("$") and len(name) > 1 and name[1].isdigit():
            return None
    else:
        match = _DOUBLE_QUOTED_TABLE_IDENTIFIER_PATTERN.match(
            statement, position,
        )
        if match is None:
            match = _BACKTICK_QUOTED_TABLE_IDENTIFIER_PATTERN.match(
                statement, position,
            )
        if match is None:
            match = _BRACKET_QUOTED_TABLE_IDENTIFIER_PATTERN.match(
                statement, position,
            )
        if match is None:
            return None
        name = match.group(1)
    if name.upper() in _SQL_TABLE_KEYWORDS:
        return None
    return name, match.end()


def _plain_table_span_after(statement: str, position: int,
                            allow_parenthesis: bool = False
                            ) -> Optional[Tuple[str, int]]:
    while position < len(statement) and statement[position].isspace():
        position += 1

    first = _table_segment_after(statement, position)
    if first is None:
        return None

    names = [first[0]]
    after_name = first[1]
    while after_name < len(statement) and statement[after_name] == ".":
        next_segment = _table_segment_after(statement, after_name + 1)
        if next_segment is None:
            return None
        names.append(next_segment[0])
        after_name = next_segment[1]

    next_position = after_name
    while next_position < len(statement) and statement[next_position].isspace():
        next_position += 1
    if next_position < len(statement) and statement[next_position] == ".":
        return None
    if (not allow_parenthesis and next_position < len(statement)
            and statement[next_position] == "("):
        return None
    return ".".join(names), after_name


def _plain_table_after(statement: str, position: int,
                       allow_parenthesis: bool = False) -> Optional[str]:
    parsed = _plain_table_span_after(
        statement, position, allow_parenthesis,
    )
    return None if parsed is None else parsed[0]


def _table_alias_after(statement: str, position: int) -> Optional[str]:
    parsed = _table_alias_span_after(statement, position)
    return None if parsed is None else parsed[0]


def _table_alias_span_after(
        statement: str, position: int
        ) -> Optional[Tuple[str, int]]:
    position = _skip_sql_noise(statement, position, len(statement))

    as_match = re.match(
        r"AS(?![A-Za-z0-9_$])", statement[position:], re.IGNORECASE,
    )
    if as_match is not None:
        position += as_match.end()
        position = _skip_sql_noise(statement, position, len(statement))

    alias = _TABLE_IDENTIFIER_PATTERN.match(statement, position)
    if alias is None:
        return None
    name = alias.group(0)
    return (name, alias.end()) \
        if name.upper() not in _SQL_TABLE_KEYWORDS else None


def _source_suffix_is_complete(statement: str, end: int,
                               allow_parenthesis: bool) -> bool:
    position = _skip_sql_noise(statement, end, len(statement))
    if position < len(statement) and position == end:
        return (allow_parenthesis and statement[end] == "(") \
            or statement[end] in ",);"

    if position >= len(statement) or statement[position] in ",);":
        return True
    if statement[position] == "(":
        return allow_parenthesis

    token = _TABLE_IDENTIFIER_PATTERN.match(statement, position)
    if token is None:
        return False
    if token.group(0).upper() in _SQL_TABLE_KEYWORDS:
        return True

    alias_end = token.end()
    after_alias = alias_end
    while (after_alias < len(statement)
           and statement[after_alias].isspace()):
        after_alias += 1
    if after_alias >= len(statement) or statement[after_alias] in ",);":
        return True
    next_token = _TABLE_IDENTIFIER_PATTERN.match(statement, after_alias)
    return next_token is not None


def _table_candidate_after(
        statement: str, position: int, allow_parenthesis: bool = False
        ) -> Optional[Tuple[str, int, int]]:
    source_position = _skip_sql_noise(statement, position, len(statement))
    parsed = _plain_table_span_after(
        statement, source_position, allow_parenthesis,
    )
    if parsed is None:
        return None
    if not _source_suffix_is_complete(
            statement, parsed[1], allow_parenthesis,
    ):
        return None
    return parsed[0], source_position, parsed[1]


def _tables_without_alias_paths(
        statement: str, candidates: List[Tuple[str, int, int]]) -> Tuple[str, ...]:
    aliases = set()
    aliases.update(_nested_select_aliases(statement, 0, len(statement)))
    for _name, _start, end in candidates:
        alias = _table_alias_after(statement, end)
        if alias is not None:
            aliases.add(alias.casefold())

    names = []
    for name, _start, _end in candidates:
        first_segment, separator, _rest = name.partition(".")
        if (separator and first_segment.casefold() in aliases):
            continue
        names.append(name)
    return _unique_tables(names)


def _unique_tables(names: List[str]) -> Tuple[str, ...]:
    seen = set()
    result = []
    for name in names:
        key = name
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return tuple(result)


def _skip_sql_comment(statement: str, position: int, limit: int) -> int:
    if statement.startswith("--", position):
        end = statement.find("\n", position + 2, limit)
        return limit if end < 0 else end
    if statement.startswith("/*", position):
        end = statement.find("*/", position + 2, limit)
        return limit if end < 0 else end + 2
    return position


def _skip_sql_noise(statement: str, position: int, limit: int) -> int:
    while position < limit:
        if statement[position].isspace():
            position += 1
            continue
        next_position = _skip_sql_comment(statement, position, limit)
        if next_position != position:
            position = next_position
            continue
        break
    return position


def _skip_sql_quoted(statement: str, position: int, limit: int) -> int:
    quote = statement[position]
    closing = "]" if quote == "[" else quote
    position += 1
    while position < limit:
        if statement[position] == closing:
            if (closing != "]" and position + 1 < limit
                    and statement[position + 1] == closing):
                position += 2
                continue
            return position + 1
        if statement[position] == "\\" and closing != "]":
            position += 2
        else:
            position += 1
    return limit


def _balanced_parenthesis_end(statement: str, opening: int,
                              limit: Optional[int] = None
                              ) -> Optional[int]:
    end = len(statement) if limit is None else min(limit, len(statement))
    depth = 1
    position = opening + 1
    while position < end:
        if statement.startswith("--", position) \
                or statement.startswith("/*", position):
            position = _skip_sql_comment(statement, position, end)
            continue
        if statement[position] in "'\"`[":
            position = _skip_sql_quoted(statement, position, end)
            continue
        if statement[position] == "(":
            depth += 1
        elif statement[position] == ")":
            depth -= 1
            if depth == 0:
                return position
        position += 1
    return None


def _top_level_match(pattern: re.Pattern, statement: str, start: int,
                     limit: int) -> Optional[re.Match]:
    position = start
    while position < limit:
        if statement.startswith("--", position) \
                or statement.startswith("/*", position):
            position = _skip_sql_comment(statement, position, limit)
            continue
        if statement[position] in "'\"`[":
            position = _skip_sql_quoted(statement, position, limit)
            continue
        if statement[position] == "(":
            closing = _balanced_parenthesis_end(statement, position, limit)
            if closing is None:
                return None
            position = closing + 1
            continue
        match = pattern.match(statement, position)
        if match is not None:
            return match
        position += 1
    return None


def _nested_select_start(statement: str, opening: int,
                         closing: int) -> Optional[int]:
    position = _skip_sql_noise(statement, opening + 1, closing)
    match = _SELECT_WORD.match(statement, position)
    return None if match is None or match.end() > closing else match.end()


def _nested_select_candidates(statement: str, start: int,
                               limit: int
                               ) -> Tuple[Tuple[str, int, int], ...]:
    candidates = []
    position = start
    while position < limit:
        if statement.startswith("--", position) \
                or statement.startswith("/*", position):
            position = _skip_sql_comment(statement, position, limit)
            continue
        if statement[position] in "'\"`[":
            position = _skip_sql_quoted(statement, position, limit)
            continue
        if statement[position] != "(":
            position += 1
            continue
        closing = _balanced_parenthesis_end(statement, position, limit)
        if closing is None:
            break
        nested_start = _nested_select_start(statement, position, closing)
        if nested_start is not None:
            from_match = _top_level_match(
                _FROM_WORD, statement, nested_start, closing,
            )
            if from_match is not None:
                nested_candidates = _from_table_candidates(
                    statement, from_match.end(), closing,
                )
                if nested_candidates is not None:
                    candidates.extend(nested_candidates)
        candidates.extend(_nested_select_candidates(
            statement, position + 1, closing,
        ))
        position = closing + 1
    return tuple(candidates)


def _nested_select_aliases(statement: str, start: int,
                           limit: int) -> Tuple[str, ...]:
    aliases = []
    position = start
    while position < limit:
        if statement.startswith("--", position) \
                or statement.startswith("/*", position):
            position = _skip_sql_comment(statement, position, limit)
            continue
        if statement[position] in "'\"`[":
            position = _skip_sql_quoted(statement, position, limit)
            continue
        if statement[position] != "(":
            position += 1
            continue
        closing = _balanced_parenthesis_end(statement, position, limit)
        if closing is None:
            break
        nested_start = _nested_select_start(statement, position, closing)
        if nested_start is not None:
            alias = _table_alias_after(statement, closing + 1)
            if alias is not None:
                aliases.append(alias.casefold())
        aliases.extend(_nested_select_aliases(
            statement, position + 1, closing,
        ))
        position = closing + 1
    return tuple(aliases)


def _from_table_candidates(statement: str, position: int,
                           limit: Optional[int] = None
                           ) -> Optional[Tuple[Tuple[str, int, int], ...]]:
    scan_end = len(statement) if limit is None else min(limit, len(statement))
    first_position = _skip_sql_noise(statement, position, scan_end)

    candidates = []
    if (first_position < scan_end
            and statement[first_position] == "("):
        closing = _balanced_parenthesis_end(
            statement, first_position, scan_end,
        )
        if closing is None:
            return None
        if (_nested_select_start(statement, first_position, closing) is None
                and not _nested_select_candidates(
                    statement, first_position + 1, closing,
                )):
            return None
        position = closing + 1
    else:
        first = _table_candidate_after(statement, first_position)
        if first is None:
            return None
        candidates.append(first)
        position = first[2]

    in_join_condition = False
    while position < scan_end:
        if statement.startswith("--", position) \
                or statement.startswith("/*", position):
            position = _skip_sql_comment(statement, position, scan_end)
            continue
        if statement[position] in "'\"`[":
            position = _skip_sql_quoted(statement, position, scan_end)
            continue
        if statement[position] == "(":
            closing = _balanced_parenthesis_end(statement, position, scan_end)
            if closing is None:
                break
            position = closing + 1
            continue
        if statement[position] == ")":
            break

        control = _SOURCE_CONTROL.match(statement, position)
        if control is None:
            position += 1
            continue
        word = control.group(0).upper()
        position = control.end()
        if in_join_condition:
            if word in _SOURCE_CLAUSES:
                break
            if word not in {"JOIN", ","}:
                continue
        elif word == "ON":
            in_join_condition = True
            continue
        elif word in _SOURCE_CLAUSES:
            break

        source_position = _skip_sql_noise(statement, position, scan_end)
        if (source_position < scan_end
                and statement[source_position] == "("):
            closing = _balanced_parenthesis_end(
                statement, source_position, scan_end,
            )
            if closing is None:
                break
            if (_nested_select_start(statement, source_position, closing)
                    is None
                    and not _nested_select_candidates(
                        statement, source_position + 1, closing,
                    )):
                break
            position = closing + 1
            in_join_condition = False
            continue

        next_source = _table_candidate_after(statement, source_position)
        if next_source is None:
            break
        candidates.append(next_source)
        position = next_source[2]
        in_join_condition = False

    return tuple(candidates)


def _from_tables(statement: str, position: int,
                 limit: Optional[int] = None,
                 nested_start: int = 0) -> Tuple[str, ...]:
    scan_end = len(statement) if limit is None else min(limit, len(statement))
    candidates = _from_table_candidates(statement, position, scan_end)
    if candidates is None:
        return ()
    candidates = list(candidates)
    candidates.extend(_nested_select_candidates(
        statement, nested_start, scan_end,
    ))
    candidates.sort(key=lambda candidate: candidate[1])
    return _tables_without_alias_paths(statement, candidates)


def tables(statement: str, verb: str) -> Tuple[str, ...]:
    normalized_verb = verb.strip().lower()
    if normalized_verb not in {"select", "delete", "insert", "update", "merge"}:
        return ()

    start = _statement_start(statement, normalized_verb)
    if start is None:
        return ()
    if normalized_verb == "merge":
        match = _top_level_match(_INTO_WORD, statement, start, len(statement))
        if match is None:
            return ()
        target = _table_candidate_after(statement, match.end())
        if target is None:
            return ()
        using = _top_level_match(
            _USING_WORD, statement, match.end(), len(statement),
        )
        if using is None:
            return _tables_without_alias_paths(statement, [target])
        source = _table_candidate_after(statement, using.end())
        candidates = [target] if source is None else [target, source]
        return _tables_without_alias_paths(statement, candidates)
    if normalized_verb == "update":
        candidate = _table_candidate_after(statement, start)
        return () if candidate is None else _tables_without_alias_paths(
            statement, [candidate],
        )
    else:
        required = _FROM_WORD if normalized_verb in {"select", "delete"} \
            else _INTO_WORD
        match = (_top_level_match(required, statement, start, len(statement))
                 if normalized_verb in {"select", "delete", "insert"}
                 else required.search(statement, start))
        if (match is not None
                and normalized_verb in {"select", "delete"}):
            return _from_tables(
                statement, match.end(), nested_start=start,
            )
        if (match is None
                and normalized_verb in {"select", "delete"}):
            candidates = list(_nested_select_candidates(
                statement, start, len(statement),
            ))
            candidates.sort(key=lambda candidate: candidate[1])
            return _tables_without_alias_paths(statement, candidates)
        candidate = None if match is None else _table_candidate_after(
            statement, match.end(), normalized_verb == "insert",
        )
        return () if candidate is None else _tables_without_alias_paths(
            statement, [candidate],
        )


def _table_candidates_without_alias_paths(
        statement: str, candidates: List[Tuple[str, int, int]]
        ) -> Tuple[Tuple[str, int, int], ...]:
    aliases = set(_nested_select_aliases(statement, 0, len(statement)))
    for _name, _start, end in candidates:
        alias = _table_alias_after(statement, end)
        if alias is not None:
            aliases.add(alias.casefold())

    result = []
    for candidate in candidates:
        name = candidate[0]
        first_segment, separator, _rest = name.partition(".")
        if separator and first_segment.casefold() in aliases:
            continue
        result.append(candidate)
    return tuple(result)


def _table_alias_candidates(statement: str, verb: str
                            ) -> Tuple[Tuple[str, int, int], ...]:
    start = _statement_start(statement, verb)
    if start is None:
        return ()

    candidates = []
    if verb in {"select", "delete"}:
        match = _top_level_match(_FROM_WORD, statement, start, len(statement))
        if match is None:
            candidates.extend(_nested_select_candidates(
                statement, start, len(statement),
            ))
        else:
            from_candidates = _from_table_candidates(
                statement, match.end(), len(statement),
            )
            if from_candidates is not None:
                candidates.extend(from_candidates)
                candidates.extend(_nested_select_candidates(
                    statement, start, len(statement),
                ))
    elif verb == "update":
        candidate = _table_candidate_after(statement, start)
        if candidate is not None:
            candidates.append(candidate)
        candidates.extend(_nested_select_candidates(
            statement, start, len(statement),
        ))
    elif verb == "insert":
        match = _top_level_match(_INTO_WORD, statement, start, len(statement))
        if match is not None:
            candidate = _table_candidate_after(
                statement, match.end(), allow_parenthesis=True,
            )
            if candidate is not None:
                candidates.append(candidate)
        candidates.extend(_nested_select_candidates(
            statement, start, len(statement),
        ))
    elif verb == "merge":
        match = _top_level_match(_INTO_WORD, statement, start, len(statement))
        if match is not None:
            target = _table_candidate_after(statement, match.end())
            if target is not None:
                candidates.append(target)
                using = _top_level_match(
                    _USING_WORD, statement, match.end(), len(statement),
                )
                if using is not None:
                    source = _table_candidate_after(
                        statement, using.end(),
                    )
                    if source is not None:
                        candidates.append(source)
        candidates.extend(_nested_select_candidates(
            statement, start, len(statement),
        ))

    candidates.sort(key=lambda candidate: candidate[1])
    return _table_candidates_without_alias_paths(statement, candidates)


def table_aliases(statement: str, verb: str) -> Dict[str, str]:
    normalized_verb = verb.strip().lower()
    if normalized_verb not in {"select", "delete", "insert", "update", "merge"}:
        return {}

    claims: Dict[str, str] = {}
    ambiguous = set()
    for name, _start, end in _table_alias_candidates(
            statement, normalized_verb,
    ):
        alias = _table_alias_after(statement, end)
        keys = [name.casefold()]
        if alias is not None:
            keys.insert(0, alias.casefold())

        for key in dict.fromkeys(keys):
            if key in ambiguous:
                continue
            previous = claims.get(key)
            if previous is None:
                claims[key] = name
            elif previous != name:
                del claims[key]
                ambiguous.add(key)
    return claims


def _write_table_name(statement: str, verb: str) -> Optional[str]:
    start = _statement_start(statement, verb)
    if start is None or verb == "select":
        return None

    if verb == "update":
        candidate = _table_candidate_after(statement, start)
    else:
        required = _FROM_WORD if verb == "delete" else _INTO_WORD
        match = _top_level_match(required, statement, start, len(statement))
        if match is None:
            return None
        candidate = _table_candidate_after(
            statement, match.end(), verb == "insert",
        )
    return None if candidate is None else candidate[0]


def table_accesses(statement: str, verb: str) -> Tuple[TableAccess, ...]:
    names = tables(statement, verb)
    if not names:
        return ()

    normalized_verb = verb.strip().lower()
    write_name = _write_table_name(statement, normalized_verb)
    seen = set()
    result = []
    for name in names:
        access = "WRITE" if name == write_name else "READ"
        pair = (name, access)
        if pair in seen:
            continue
        seen.add(pair)
        result.append(TableAccess(name, access))
    return tuple(result)


def _top_level_segments(statement: str, start: int, limit: int
                        ) -> List[Tuple[int, int]]:
    segments = []
    segment_start = start
    position = start
    while position < limit:
        if statement.startswith("--", position) \
                or statement.startswith("/*", position):
            position = _skip_sql_comment(statement, position, limit)
            continue
        if statement[position] in "'\"`[":
            position = _skip_sql_quoted(statement, position, limit)
            continue
        if statement[position] == "(":
            closing = _balanced_parenthesis_end(statement, position, limit)
            if closing is None:
                segments.append((segment_start, position))
                return segments
            position = closing + 1
            continue
        if statement[position] == ",":
            segments.append((segment_start, position))
            segment_start = position + 1
        position += 1
    segments.append((segment_start, limit))
    return segments


def _column_identifier_at(statement: str, position: int, limit: int
                          ) -> Optional[Tuple[str, int, bool]]:
    position = _skip_sql_noise(statement, position, limit)
    if position >= limit:
        return None

    if statement[position] in "\"`[":
        quote = statement[position]
        closing = "]" if quote == "[" else quote
        end = _skip_sql_quoted(statement, position, limit)
        if end <= position or end > limit or statement[end - 1] != closing:
            return None
        return statement[position + 1:end - 1], end, True

    match = _TABLE_IDENTIFIER_PATTERN.match(statement, position)
    if match is None or match.end() > limit:
        return None
    name = match.group(0)
    if name.startswith("$") and len(name) > 1 and name[1].isdigit():
        return None
    return name, match.end(), False


def _column_name_in_span(statement: str, start: int, limit: int
                         ) -> Optional[str]:
    position = _skip_sql_noise(statement, start, limit)
    segments = []
    while position < limit:
        parsed = _column_identifier_at(statement, position, limit)
        if parsed is None:
            return None
        name, position, quoted = parsed
        if not name:
            return None
        segments.append((name, quoted))
        position = _skip_sql_noise(statement, position, limit)
        if position >= limit or statement[position] != ".":
            break
        position = _skip_sql_noise(statement, position + 1, limit)

    if _skip_sql_noise(statement, position, limit) != limit:
        return None
    column, quoted = segments[-1]
    if not quoted and column.upper() in _SQL_TABLE_KEYWORDS:
        return None
    return column


def _update_written_columns(statement: str, table: str
                            ) -> Tuple[ColumnWrite, ...]:
    start = _statement_start(statement, "update")
    if start is None:
        return ()
    set_match = _top_level_match(_SET_WORD, statement, start, len(statement))
    if set_match is None:
        return ()

    where_match = _top_level_match(
        _WHERE_WORD, statement, set_match.end(), len(statement),
    )
    limit = len(statement) if where_match is None else where_match.start()
    assignments = _top_level_segments(statement, set_match.end(), limit)

    result = []
    seen = set()
    for assignment_start, assignment_end in assignments:
        equals = _top_level_match(
            _ASSIGNMENT_EQUALS, statement, assignment_start, assignment_end,
        )
        if equals is None:
            continue
        column = _column_name_in_span(
            statement, assignment_start, equals.start(),
        )
        if column is None:
            continue
        pair = (table, column)
        if pair in seen:
            continue
        seen.add(pair)
        result.append(ColumnWrite(table, column))
    return tuple(result)


def _insert_written_columns(statement: str, table: str
                            ) -> Tuple[ColumnWrite, ...]:
    start = _statement_start(statement, "insert")
    if start is None:
        return ()
    into_match = _top_level_match(_INTO_WORD, statement, start, len(statement))
    if into_match is None:
        return ()
    candidate = _table_candidate_after(
        statement, into_match.end(), allow_parenthesis=True,
    )
    if candidate is None or candidate[0] != table:
        return ()

    opening = _skip_sql_noise(statement, candidate[2], len(statement))
    if opening >= len(statement) or statement[opening] != "(":
        return ()
    closing = _balanced_parenthesis_end(statement, opening)
    if closing is None:
        return ()

    column_spans = _top_level_segments(statement, opening + 1, closing)

    columns = []
    seen = set()
    for column_start, column_end in column_spans:
        column = _column_name_in_span(statement, column_start, column_end)
        if column is None:
            return ()
        if column in seen:
            continue
        seen.add(column)
        columns.append(ColumnWrite(table, column))
    return tuple(columns)


def written_columns(statement: str, verb: str) -> Tuple[ColumnWrite, ...]:
    normalized_verb = verb.strip().lower()
    if normalized_verb not in {"insert", "update", "delete", "merge"}:
        return ()

    table = _write_table_name(statement, normalized_verb)
    if table is None:
        return ()
    if normalized_verb == "update":
        return _update_written_columns(statement, table)
    if normalized_verb == "insert":
        return _insert_written_columns(statement, table)
    return ()


@dataclass(frozen=True)
class _ReadToken:
    text: str
    start: int
    end: int
    kind: str
    quoted: bool = False


_READ_NON_COLUMN_WORDS = frozenset({
    "FALSE", "FETCH", "FIRST", "LAST", "LATERAL", "MATCHED", "NEW",
    "NULLS", "ONLY", "RECURSIVE", "ROW", "ROWS", "TIES", "TRUE",
    "UNKNOWN",
})


def _read_tokens(statement: str) -> List[_ReadToken]:
    tokens = []
    position = 0
    limit = len(statement)
    while position < limit:
        if statement.startswith("--", position) \
                or statement.startswith("/*", position):
            position = _skip_sql_comment(statement, position, limit)
            continue

        char = statement[position]
        if char == "'":
            position = _skip_sql_quoted(statement, position, limit)
            continue
        if char in '"`[':
            closing = "]" if char == "[" else char
            end = _skip_sql_quoted(statement, position, limit)
            if end > position and end <= limit \
                    and statement[end - 1] == closing:
                contents = statement[position + 1:end - 1]
                if contents.isdigit() and char == "[":
                    tokens.append(_ReadToken(
                        contents, position, end, "index", True,
                    ))
                elif not contents.isdigit():
                    tokens.append(_ReadToken(
                        contents, position, end, "identifier", True,
                    ))
            position = end
            continue

        identifier = _TABLE_IDENTIFIER_PATTERN.match(statement, position)
        if identifier is not None:
            tokens.append(_ReadToken(
                identifier.group(0), position, identifier.end(),
                "identifier",
            ))
            position = identifier.end()
            continue

        if char in ".:?,()=<>!+-*/%":
            tokens.append(_ReadToken(char, position, position + 1,
                                     "punctuation"))
        position += 1
    return tokens


def _read_tokens_are_adjacent(statement: str, left: _ReadToken,
                               right: _ReadToken) -> bool:
    return _skip_sql_noise(statement, left.end, len(statement)) == right.start


def _read_chain_end(statement: str, tokens: List[_ReadToken], start: int
                    ) -> int:
    end = start
    while end + 2 < len(tokens):
        dot = tokens[end + 1]
        next_token = tokens[end + 2]
        if dot.text != "." or next_token.kind != "identifier":
            break
        if not _read_tokens_are_adjacent(statement, tokens[end], dot) \
                or not _read_tokens_are_adjacent(statement, dot, next_token):
            break
        end += 2
    return end


def _read_dotted_chains(statement: str, tokens: List[_ReadToken]
                        ) -> Tuple[Dict[int, int], set]:
    chains = {}
    dotted = set()
    for index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        if index > 0 and tokens[index - 1].text == "." \
                and _read_tokens_are_adjacent(
                    statement, tokens[index - 1], token,
                ):
            continue
        end = _read_chain_end(statement, tokens, index)
        if end == index:
            continue
        chains[index] = end
        dotted.update(range(index, end + 1))
    for index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        if index > 0 and tokens[index - 1].text == "." \
                and _read_tokens_are_adjacent(
                    statement, tokens[index - 1], token,
                ):
            dotted.add(index)
        if index + 1 < len(tokens) and tokens[index + 1].text == "." \
                and _read_tokens_are_adjacent(
                    statement, token, tokens[index + 1],
                ):
            dotted.add(index)
    return chains, dotted


def _read_indexed_paths(statement: str, tokens: List[_ReadToken]) -> set:
    paths = set()
    for index, token in enumerate(tokens):
        if token.kind != "index":
            continue
        if index > 0 and tokens[index - 1].kind == "identifier" \
                and _read_tokens_are_adjacent(
                    statement, tokens[index - 1], token,
                ):
            paths.add(index - 1)
        dot_index = index + 1
        identifier_index = index + 2
        if identifier_index < len(tokens) \
                and tokens[dot_index].text == "." \
                and tokens[identifier_index].kind == "identifier" \
                and _read_tokens_are_adjacent(
                    statement, token, tokens[dot_index],
                ) \
                and _read_tokens_are_adjacent(
                    statement, tokens[dot_index], tokens[identifier_index],
                ):
            paths.add(identifier_index)
    return paths


def _read_chain_source_position(statement: str, tokens: List[_ReadToken],
                                start: int) -> bool:
    if start == 0:
        return False
    previous = tokens[start - 1]
    if previous.kind != "identifier":
        return False
    return previous.text.upper() in {
        "FETCH", "FROM", "INTO", "JOIN", "LATERAL", "UPDATE", "USING",
    }


def _read_source_aliases(statement: str, tokens: List[_ReadToken],
                         chains: Dict[int, int]) -> set:
    aliases = set()
    for start, end in chains.items():
        if not _read_chain_source_position(statement, tokens, start):
            continue
        next_index = end + 1
        if next_index >= len(tokens):
            continue
        previous = tokens[end]
        if tokens[next_index].kind == "identifier" \
                and tokens[next_index].text.upper() == "AS" \
                and _read_tokens_are_adjacent(
                    statement, previous, tokens[next_index],
                ):
            previous = tokens[next_index]
            next_index += 1
        if next_index >= len(tokens) \
                or tokens[next_index].kind != "identifier" \
                or not _read_tokens_are_adjacent(
                    statement, previous, tokens[next_index],
                ):
            continue
        alias = tokens[next_index]
        if not alias.quoted and (
                alias.text.upper() in _SQL_TABLE_KEYWORDS
                or alias.text.upper() in _READ_NON_COLUMN_WORDS
        ):
            continue
        aliases.add(alias.text.casefold())
    return aliases


def _read_assignment_spans(statement: str, verb: str
                           ) -> List[Tuple[int, int]]:
    spans = []
    if verb == "insert":
        start = _statement_start(statement, verb)
        if start is None:
            return spans
        into_match = _top_level_match(_INTO_WORD, statement, start, len(statement))
        if into_match is None:
            return spans
        candidate = _table_candidate_after(
            statement, into_match.end(), allow_parenthesis=True,
        )
        if candidate is None:
            return spans
        opening = _skip_sql_noise(statement, candidate[2], len(statement))
        if opening >= len(statement) or statement[opening] != "(":
            return spans
        closing = _balanced_parenthesis_end(statement, opening)
        if closing is not None:
            spans.append((opening + 1, closing))
        return spans

    if verb not in {"update", "merge"}:
        return spans
    start = _statement_start(statement, verb)
    if start is None:
        return spans
    set_match = _top_level_match(_SET_WORD, statement, start, len(statement))
    if set_match is None:
        return spans
    where_match = _top_level_match(
        _WHERE_WORD, statement, set_match.end(), len(statement),
    )
    limit = len(statement) if where_match is None else where_match.start()
    for assignment_start, assignment_end in _top_level_segments(
            statement, set_match.end(), limit,
    ):
        equals = _top_level_match(
            _ASSIGNMENT_EQUALS, statement, assignment_start, assignment_end,
        )
        if equals is not None:
            spans.append((assignment_start, equals.start()))
    return spans


def _insert_select_aliases(statement: str):
    start = _statement_start(statement, "insert")
    if start is None:
        return None
    into_match = _top_level_match(_INTO_WORD, statement, start, len(statement))
    if into_match is None:
        return None
    candidate = _table_candidate_after(
        statement, into_match.end(), allow_parenthesis=True,
    )
    if candidate is None:
        return None
    select_match = _top_level_match(
        _SELECT_WORD, statement, candidate[2], len(statement),
    )
    if select_match is None:
        return None
    return table_aliases(statement[select_match.start():], "select")


def _read_aliases(statement: str, verb: str) -> Dict[str, str]:
    aliases = table_aliases(statement, verb)
    if verb == "insert":
        source_aliases = _insert_select_aliases(statement)
        if source_aliases is not None:
            return source_aliases
    return aliases


def _read_token_is_parameter(tokens: List[_ReadToken], index: int,
                             statement: str) -> bool:
    token = tokens[index]
    if token.text.startswith("$") and len(token.text) > 1 \
            and token.text[1].isdigit():
        return True
    if index == 0:
        return False
    previous = tokens[index - 1]
    return previous.text in {":", "$"} \
        and _read_tokens_are_adjacent(statement, previous, token)


def _read_token_is_function(tokens: List[_ReadToken], index: int,
                            statement: str) -> bool:
    next_index = index + 1
    if next_index >= len(tokens) or tokens[next_index].text != "(":
        return False
    return _read_tokens_are_adjacent(
        statement, tokens[index], tokens[next_index],
    )


def _read_token_is_after_as(tokens: List[_ReadToken], index: int,
                            statement: str) -> bool:
    if index == 0:
        return False
    previous = tokens[index - 1]
    return previous.kind == "identifier" and previous.text.upper() == "AS" \
        and _read_tokens_are_adjacent(statement, previous, tokens[index])


def _read_token_is_source_name(tokens: List[_ReadToken], index: int,
                               statement: str) -> bool:
    if index == 0:
        return False
    previous = tokens[index - 1]
    if previous.kind != "identifier" \
            or not _read_tokens_are_adjacent(statement, previous, tokens[index]):
        return False
    return previous.text.upper() in {
        "FROM", "INTO", "JOIN", "LATERAL", "UPDATE", "USING",
    }


def read_columns(statement: str, verb: str) -> Tuple[ColumnRead, ...]:
    normalized_verb = verb.strip().lower()
    if normalized_verb not in {"select", "insert", "update", "delete", "merge"}:
        return ()

    aliases = _read_aliases(statement, normalized_verb)
    if not aliases:
        return ()
    tables_seen = []
    for table in aliases.values():
        if table not in tables_seen:
            tables_seen.append(table)
    single_table = tables_seen[0] if len(tables_seen) == 1 else None
    alias_keys = set(aliases)
    alias_keys.update(
        alias.casefold() for alias in _nested_select_aliases(
            statement, 0, len(statement),
        )
    )

    tokens = _read_tokens(statement)
    chains, dotted = _read_dotted_chains(statement, tokens)
    indexed_paths = _read_indexed_paths(statement, tokens)
    alias_keys.update(_read_source_aliases(statement, tokens, chains))
    assignment_spans = _read_assignment_spans(statement, normalized_verb)
    excluded = set()
    for index, token in enumerate(tokens):
        if any(start <= token.start and token.end <= end
               for start, end in assignment_spans):
            excluded.add(index)

    result = []
    seen = set()
    ambiguous_unqualified = False

    def add(table: str, column: str) -> None:
        pair = (table, column)
        if pair in seen:
            return
        seen.add(pair)
        result.append(ColumnRead(table, column))

    for index, token in enumerate(tokens):
        if token.kind != "identifier":
            continue
        if token.start > 0 and statement[token.start - 1] == "%":
            continue

        if index in chains:
            end = chains[index]
            if any(item in excluded for item in range(index, end + 1)):
                continue
            if _read_chain_source_position(statement, tokens, index):
                continue
            parts = [tokens[item].text for item in range(index, end + 1, 2)]
            qualifier = ".".join(part.casefold() for part in parts[:-1])
            table = aliases.get(qualifier)
            if table is not None:
                add(table, parts[-1])
            continue

        if index in dotted:
            continue
        if index in indexed_paths:
            continue
        if index in excluded:
            continue
        if _read_token_is_parameter(tokens, index, statement):
            continue
        if _read_token_is_function(tokens, index, statement):
            continue
        if _read_token_is_after_as(tokens, index, statement):
            continue
        if _read_token_is_source_name(tokens, index, statement):
            continue
        if token.text.casefold() in alias_keys:
            continue
        if not token.quoted and (
                token.text.upper() in _SQL_TABLE_KEYWORDS
                or token.text.upper() in _READ_NON_COLUMN_WORDS
        ):
            continue
        if not token.quoted and token.text.casefold() == "new":
            continue
        if single_table is None:
            ambiguous_unqualified = True
        else:
            add(single_table, token.text)
    if ambiguous_unqualified:
        return ()
    return tuple(result)


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
