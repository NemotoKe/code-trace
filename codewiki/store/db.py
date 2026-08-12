from __future__ import annotations

import os
import sqlite3
import json
import tempfile
from datetime import datetime, timezone
from typing import List, Optional


SCHEMA_VERSION = "1"
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection, repo_root: str) -> None:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as stream:
        connection.executescript(stream.read())
    connection.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (SCHEMA_VERSION,))
    connection.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('repo_root', ?)", (repo_root,))
    connection.commit()


def validate_schema(connection: sqlite3.Connection) -> None:
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError("schema mismatch; rerun index") from exc
    if row is None or row[0] != SCHEMA_VERSION:
        raise RuntimeError("schema mismatch; rerun index")


def open_index(path: str) -> sqlite3.Connection:
    connection = connect(path)
    validate_schema(connection)
    return connection


def write_index(db_path: str, repo_root: str, files: List, symbols: List,
                generated_at: Optional[str] = None, skipped=None,
                parallel_jobs: Optional[int] = None) -> None:
    """Write a complete fresh index with IDs assigned from sorted input rows."""
    parent = os.path.dirname(os.path.abspath(db_path))
    if not os.path.isdir(parent):
        os.makedirs(parent)
    temporary = tempfile.NamedTemporaryFile(
        prefix=".codewiki-", suffix=".sqlite3", dir=parent, delete=False
    )
    temporary_path = temporary.name
    temporary.close()
    connection = None
    try:
        connection = connect(temporary_path)
        initialize(connection, repo_root)
        if generated_at is None:
            generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('generated_at', ?)",
            (generated_at,),
        )
        if skipped is not None:
            for reason in sorted(skipped):
                connection.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                    ("scan_skipped_" + reason, str(skipped[reason])),
                )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('scan_skipped', ?)",
                (json.dumps(skipped, sort_keys=True, separators=(",", ":")),),
            )
        if parallel_jobs is not None:
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('parallel_jobs', ?)",
                (str(parallel_jobs),),
            )
        file_ids = {}
        for record in sorted(files, key=lambda item: item.path):
            cursor = connection.execute(
                "INSERT INTO files(path, language, package, lines, sha256, is_test, is_generated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.path, record.language, record.package or None, record.lines,
                 record.sha256, int(record.is_test), int(record.is_generated)),
            )
            file_ids[record.path] = cursor.lastrowid
        for symbol in sorted(
                symbols,
                key=lambda item: (item.path, item.line, item.name, item.kind,
                                  item.fqn, item.signature)):
            encoded_params = None
            if symbol.params is not None:
                encoded_params = json.dumps(
                    symbol.params, ensure_ascii=False, separators=(",", ":")
                )
            connection.execute(
                "INSERT INTO symbols(file_id, name, kind, fqn, owner_fqn, params, "
                "param_count, signature, line, end_line, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (file_ids[symbol.path], symbol.name, symbol.kind, symbol.fqn,
                 symbol.owner_fqn, encoded_params, symbol.param_count, symbol.signature,
                 symbol.line, symbol.end_line, symbol.confidence),
            )
        connection.commit()
        connection.close()
        connection = None
        os.replace(temporary_path, db_path)
    finally:
        if connection is not None:
            connection.close()
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
