from __future__ import annotations

import sqlite3
from typing import Dict

from .types import TypeQueryError, _readonly


_ERROR_MESSAGE = "index database missing or stale; rerun index"

_SAMPLE_QUERIES = {
    "sql": {
        "columns": ("path", "line", "method_fqn", "verb", "access", "table_name"),
        "table": "sql_accesses",
        "alias": "s",
        "primary_key": "s.access_id",
        "from": (
            "SELECT f.path, s.line, s.method_fqn, s.verb, s.access, s.table_name "
            "FROM sql_accesses AS s JOIN files AS f ON f.file_id = s.file_id"
        ),
        "where": "",
    },
    "entrypoints": {
        "columns": ("path", "line", "method_fqn", "kind", "reason"),
        "table": "entrypoints",
        "alias": "e",
        "primary_key": "e.entrypoint_id",
        "from": (
            "SELECT f.path, e.line, e.method_fqn, e.kind, e.reason "
            "FROM entrypoints AS e JOIN files AS f ON f.file_id = e.file_id"
        ),
        "where": "",
    },
    "calls": {
        "columns": ("path", "line", "caller_fqn", "target_fqn", "confidence", "reason"),
        "table": "calls",
        "alias": "c",
        "primary_key": "c.call_id",
        "from": (
            "SELECT f.path, c.line, c.caller_fqn, c.target_fqn, "
            "c.confidence, c.reason "
            "FROM calls AS c JOIN files AS f ON f.file_id = c.file_id"
        ),
        "where": "c.target_fqn IS NOT NULL",
    },
}


def _condition(where: str, primary_key: str) -> str:
    prefix = " WHERE " + where + " AND " if where else " WHERE "
    return prefix + primary_key + " % ? = 0"


def sample(path: str, kind: str, n: int = 20) -> Dict:
    """Return a deterministic, source-locatable sample from an index."""
    if kind not in _SAMPLE_QUERIES:
        raise ValueError("unknown sample kind: %s" % kind)
    if n <= 0:
        raise ValueError("sample size must be positive")

    query = _SAMPLE_QUERIES[kind]
    connection = _readonly(path)
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM " + query["table"] + " AS " + query["alias"]
            + (" WHERE " + query["where"] if query["where"] else "")
        ).fetchone()[0]
        divisor = max(1, total // n)
        rows = connection.execute(
            query["from"]
            + _condition(query["where"], query["primary_key"])
            + " ORDER BY " + query["primary_key"] + " LIMIT ?",
            (divisor, n),
        ).fetchall()
        results = [
            dict(zip(query["columns"], row))
            for row in rows
        ]
        return {
            "kind": kind,
            "n": n,
            "count": len(results),
            "exportable": False,
            "results": results,
        }
    except (sqlite3.DatabaseError, TypeError, ValueError, KeyError) as exc:
        raise TypeQueryError(_ERROR_MESSAGE) from exc
    finally:
        connection.close()


read_sample = sample
