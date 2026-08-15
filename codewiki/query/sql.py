from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional

from .types import TypeQueryError, _readonly


@dataclass(frozen=True)
class TableAccessResult:
    method_fqn: str
    method_kind: str
    path: str
    line: int
    verb: str
    table_name: str
    access: str
    statement: str

    def as_dict(self) -> Dict:
        return {
            "method_fqn": self.method_fqn,
            "method_kind": self.method_kind,
            "path": self.path,
            "line": self.line,
            "verb": self.verb,
            "table_name": self.table_name,
            "access": self.access,
            "statement": self.statement,
        }


@dataclass(frozen=True)
class ColumnAccessResult:
    method_fqn: str
    method_kind: str
    path: str
    line: int
    verb: str
    table_name: str
    column_name: str
    access: str
    statement: str

    def as_dict(self) -> Dict:
        return {
            "method_fqn": self.method_fqn,
            "method_kind": self.method_kind,
            "path": self.path,
            "line": self.line,
            "verb": self.verb,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "access": self.access,
            "statement": self.statement,
        }


def accesses(path: str, table: str,
             access: Optional[str] = None) -> List[TableAccessResult]:
    """Return indexed SQL accesses to a table, in deterministic source order."""
    connection = _readonly(path)
    try:
        sql = (
            "SELECT s.method_fqn, s.method_kind, f.path, s.line, s.verb, "
            "s.table_name, s.access, s.statement "
            "FROM sql_accesses AS s JOIN files AS f ON f.file_id = s.file_id "
            "WHERE s.table_key = ?"
        )
        parameters = [table.casefold()]
        if access is not None:
            sql += " AND s.access = ?"
            parameters.append(access)
        sql += " ORDER BY f.path, s.line, s.method_fqn, s.access_id"
        rows = connection.execute(sql, parameters).fetchall()
        return [TableAccessResult(*row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()


def column_accesses(path: str, table: str, column: str,
                    access: Optional[str] = None) -> List[ColumnAccessResult]:
    """Return indexed SQL accesses to a table column, in source order."""
    connection = _readonly(path)
    try:
        sql = (
            "SELECT s.method_fqn, s.method_kind, f.path, s.line, s.verb, "
            "s.table_name, s.column_name, s.access, s.statement "
            "FROM sql_column_accesses AS s JOIN files AS f ON f.file_id = s.file_id "
            "WHERE s.table_key = ? AND s.column_key = ?"
        )
        parameters = [table.casefold(), column.casefold()]
        if access is not None:
            sql += " AND s.access = ?"
            parameters.append(access)
        sql += " ORDER BY f.path, s.line, s.method_fqn, s.column_access_id"
        rows = connection.execute(sql, parameters).fetchall()
        return [ColumnAccessResult(*row) for row in rows]
    except sqlite3.DatabaseError as exc:
        raise TypeQueryError("index database missing or stale; rerun index") from exc
    finally:
        connection.close()
