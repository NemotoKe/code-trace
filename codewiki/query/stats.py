from __future__ import annotations

import json
import math
import sqlite3
from typing import Dict, Iterable, Sequence

from .types import TypeQueryError, _readonly


_ERROR_MESSAGE = "index database missing or stale; rerun index"
_FILE_LANGUAGES = ("java", "xml", "sql", "properties")
_CONFIDENCES = ("CONFIRMED", "POSSIBLE", "UNRESOLVED")
_SYMBOL_KINDS = (
    "class", "interface", "enum", "record", "annotation", "method",
    "constructor",
)
_IMPORT_FORMS = ("single", "wildcard", "static_single", "static_wildcard")
_OUTCOMES = ("resolved", "external", "unresolved", "excluded")
_CALL_FORMS = ("receiver", "bare", "chained", "method_ref", "constructor")
_SQL_VERBS = ("select", "insert", "update", "delete", "merge")
_SQL_ACCESSES = ("READ", "WRITE")
_ENTRYPOINT_KINDS = ("main", "servlet", "jaxrs")
_META_KEYS = (
    "schema_version", "generated_at", "import_forms", "import_outcomes",
    "internal_resolution_rate", "type_resolution_outcomes",
)


def _group_counts(connection: sqlite3.Connection, statement: str,
                  keys: Sequence[str]) -> Dict[str, int]:
    known = set(keys)
    counts = {key: 0 for key in keys}
    counts["other"] = 0
    for key, count in connection.execute(statement):
        if key in known:
            counts[key] = int(count)
        else:
            counts["other"] += int(count)
    return counts


def _composite_counts(connection: sqlite3.Connection, statement: str,
                      left_keys: Sequence[str],
                      right_keys: Sequence[str]) -> Dict[str, int]:
    counts = {
        left + "|" + right: 0
        for left in left_keys
        for right in right_keys
    }
    for left, right, count in connection.execute(statement):
        key = str(left) + "|" + str(right)
        if key in counts:
            counts[key] = int(count)
    return counts


def _scalar(connection: sqlite3.Connection, statement: str) -> int:
    row = connection.execute(statement).fetchone()
    return int(row[0])


def _read_meta(connection: sqlite3.Connection) -> Dict[str, str]:
    placeholders = ",".join("?" for _key in _META_KEYS)
    rows = connection.execute(
        "SELECT key, value FROM meta WHERE key IN (" + placeholders + ")",
        _META_KEYS,
    ).fetchall()
    values = {key: value for key, value in rows}
    if any(key not in values for key in _META_KEYS):
        raise ValueError("required stats metadata is missing")
    return values


def _metadata_counts(raw: str, keys: Iterable[str]) -> Dict[str, int]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("stats metadata is not an object")
    counts = {}
    for key in keys:
        count = value.get(key, 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("stats metadata contains a non-count value")
        counts[key] = count
    return counts


def _metadata_rate(raw: str) -> float:
    rate = float(raw)
    if not math.isfinite(rate) or rate < 0.0 or rate > 1.0:
        raise ValueError("stats metadata contains an invalid rate")
    return rate


def _by_outcome(connection: sqlite3.Connection, table: str) -> Dict[str, int]:
    return _group_counts(
        connection,
        "SELECT outcome, COUNT(*) FROM " + table + " GROUP BY outcome",
        _OUTCOMES,
    )


def stats(path: str) -> Dict:
    """Read aggregate-only statistics from an existing index database."""
    connection = _readonly(path)
    try:
        meta = _read_meta(connection)
        import_forms = _metadata_counts(meta["import_forms"], _IMPORT_FORMS)
        import_outcomes = _metadata_counts(meta["import_outcomes"], _OUTCOMES)
        type_resolution_outcomes = _metadata_counts(
            meta["type_resolution_outcomes"], _OUTCOMES
        )

        supertypes_outcomes = _by_outcome(connection, "supertypes")
        calls_by_form = _group_counts(
            connection,
            "SELECT form, COUNT(*) FROM calls GROUP BY form",
            _CALL_FORMS,
        )
        calls_by_confidence = _group_counts(
            connection,
            "SELECT confidence, COUNT(*) FROM calls GROUP BY confidence",
            _CONFIDENCES,
        )
        calls_by_form_confidence = _composite_counts(
            connection,
            "SELECT form, confidence, COUNT(*) FROM calls "
            "GROUP BY form, confidence",
            _CALL_FORMS,
            _CONFIDENCES,
        )
        sql_by_verb_access = _composite_counts(
            connection,
            "SELECT verb, access, COUNT(*) FROM sql_accesses "
            "GROUP BY verb, access",
            _SQL_VERBS,
            _SQL_ACCESSES,
        )

        supertypes_resolved = supertypes_outcomes["resolved"]
        supertypes_unresolved = supertypes_outcomes["unresolved"]
        supertypes_denominator = supertypes_resolved + supertypes_unresolved
        supertypes_rate = (
            float(supertypes_resolved) / supertypes_denominator
            if supertypes_denominator else 0.0
        )

        return {
            "schema_version": meta["schema_version"],
            "generated_at": meta["generated_at"],
            "files": _group_counts(
                connection,
                "SELECT language, COUNT(*) FROM files GROUP BY language",
                _FILE_LANGUAGES,
            ),
            "symbols": {
                "total": _scalar(connection, "SELECT COUNT(*) FROM symbols"),
                "by_confidence": _group_counts(
                    connection,
                    "SELECT confidence, COUNT(*) FROM symbols "
                    "GROUP BY confidence",
                    _CONFIDENCES,
                ),
                "by_kind": _group_counts(
                    connection,
                    "SELECT kind, COUNT(*) FROM symbols GROUP BY kind",
                    _SYMBOL_KINDS,
                ),
            },
            "imports": {
                "total": sum(import_forms.values()),
                "by_form": import_forms,
                "by_outcome": import_outcomes,
                "internal_resolution_rate": _metadata_rate(
                    meta["internal_resolution_rate"]
                ),
            },
            "type_resolutions": {
                "by_outcome": type_resolution_outcomes,
            },
            "supertypes": {
                "total": _scalar(connection, "SELECT COUNT(*) FROM supertypes"),
                "by_outcome": supertypes_outcomes,
                "resolution_rate": supertypes_rate,
            },
            "calls": {
                "total": _scalar(connection, "SELECT COUNT(*) FROM calls"),
                "by_form": calls_by_form,
                "by_confidence": calls_by_confidence,
                "by_form_confidence": calls_by_form_confidence,
                "methods": _scalar(
                    connection,
                    "SELECT COUNT(*) FROM symbols WHERE kind='method'",
                ),
                "resolved_targets": _scalar(
                    connection,
                    "SELECT COUNT(DISTINCT target_fqn) FROM calls "
                    "WHERE target_fqn IS NOT NULL",
                ),
            },
            "sql": {
                "accesses": _scalar(connection, "SELECT COUNT(*) FROM sql_accesses"),
                "tables": _scalar(
                    connection,
                    "SELECT COUNT(DISTINCT table_key) FROM sql_accesses",
                ),
                "methods": _scalar(
                    connection,
                    "SELECT COUNT(DISTINCT method_fqn) FROM sql_accesses",
                ),
                "by_verb_access": sql_by_verb_access,
                "column_accesses": _scalar(
                    connection, "SELECT COUNT(*) FROM sql_column_accesses"
                ),
                "columns": _scalar(
                    connection,
                    "SELECT COUNT(DISTINCT table_key||'.'||column_key) "
                    "FROM sql_column_accesses",
                ),
                "column_methods": _scalar(
                    connection,
                    "SELECT COUNT(DISTINCT method_fqn) "
                    "FROM sql_column_accesses",
                ),
                "accesses_without_column": _scalar(
                    connection,
                    "SELECT COUNT(*) FROM sql_accesses a WHERE NOT EXISTS (\n"
                    "  SELECT 1 FROM sql_column_accesses c\n"
                    "   WHERE c.file_id=a.file_id AND c.method_fqn=a.method_fqn\n"
                    "     AND c.line=a.line AND c.table_key=a.table_key);",
                ),
            },
            "entrypoints": {
                "total": _scalar(connection, "SELECT COUNT(*) FROM entrypoints"),
                "by_kind": _group_counts(
                    connection,
                    "SELECT kind, COUNT(*) FROM entrypoints GROUP BY kind",
                    _ENTRYPOINT_KINDS,
                ),
                "methods": _scalar(
                    connection,
                    "SELECT COUNT(DISTINCT method_fqn) FROM entrypoints",
                ),
            },
        }
    except (sqlite3.DatabaseError, TypeError, ValueError, KeyError) as exc:
        raise TypeQueryError(_ERROR_MESSAGE) from exc
    finally:
        connection.close()


read_stats = stats
