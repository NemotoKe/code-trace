from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

from ..store import db


RESULT_KEYS = (
    "fqn", "name", "kind", "package", "owner_fqn", "params", "param_count",
    "signature", "path", "line", "end_line", "confidence",
)


class QueryError(RuntimeError):
    pass


@dataclass
class QueryResult:
    query: str
    count: int
    truncated: bool
    results: List[Dict]

    def as_dict(self) -> Dict:
        return {
            "query": self.query,
            "count": self.count,
            "truncated": self.truncated,
            "results": self.results,
        }


def _readonly(path: str) -> sqlite3.Connection:
    absolute = os.path.abspath(path)
    uri = "file:%s?mode=ro" % quote(absolute, safe="/:")
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA foreign_keys = ON")
        db.validate_schema(connection)
        return connection
    except (OSError, sqlite3.DatabaseError, RuntimeError) as exc:
        raise QueryError("index database missing or stale; rerun index") from exc


def _where(query: str) -> Tuple[str, List[str]]:
    if "." in query:
        suffix = "." + query
        return (
            "(s.fqn COLLATE BINARY = ? OR "
            "substr(s.fqn, -length(?)) COLLATE BINARY = ?)",
            [query, suffix, suffix],
        )
    return "s.name = ?", [query]


def is_indexed(path: str, fqn: str) -> bool:
    connection = _readonly(path)
    try:
        return connection.execute(
            "SELECT 1 FROM symbols WHERE fqn = ? LIMIT 1", (fqn,)
        ).fetchone() is not None
    except sqlite3.DatabaseError as exc:
        raise QueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()


def search(connection: sqlite3.Connection, query: str, limit: Optional[int] = None,
           kind: Optional[str] = None) -> QueryResult:
    where, values = _where(query)
    if kind is not None:
        where += " AND s.kind = ?"
        values.append(kind)
    sql = (
        "SELECT s.fqn, s.name, s.kind, f.package, s.owner_fqn, s.params, s.param_count, "
        "s.signature, f.path, s.line, s.end_line, s.confidence "
        "FROM symbols AS s JOIN files AS f ON f.file_id = s.file_id "
        "WHERE " + where + " ORDER BY s.fqn, f.path, s.line, s.end_line, s.kind, s.name, s.symbol_id"
    )
    parameters = list(values)
    fetch_limit = None
    if limit is not None:
        fetch_limit = max(0, limit) + 1
        sql += " LIMIT ?"
        parameters.append(fetch_limit)
    rows = connection.execute(sql, parameters).fetchall()
    truncated = limit is not None and len(rows) > max(0, limit)
    if limit is not None:
        rows = rows[:max(0, limit)]
    results = []
    for row in rows:
        params = json.loads(row[5]) if row[5] is not None else None
        results.append(dict(zip(RESULT_KEYS, (
            row[0], row[1], row[2], row[3], row[4], params, row[6], row[7],
            row[8], row[9], row[10], row[11],
        ))))
    return QueryResult(query, len(results), truncated, results)


def search_path(path: str, query: str, limit: Optional[int] = None,
                kind: Optional[str] = None) -> QueryResult:
    connection = _readonly(path)
    try:
        return search(connection, query, limit=limit, kind=kind)
    except sqlite3.DatabaseError as exc:
        raise QueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()
