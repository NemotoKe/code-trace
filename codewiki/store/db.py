from __future__ import annotations

import os
import sqlite3
import json
import tempfile
from datetime import datetime, timezone
from typing import List, Optional

SCHEMA_VERSION = "1"
_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
_IMPORT_FORMS = ("single", "wildcard", "static_single", "static_wildcard")
_IMPORT_OUTCOMES = ("resolved", "external", "unresolved", "excluded")
_TYPE_RESOLUTION_OUTCOMES = ("resolved", "external", "unresolved", "excluded")
_INDEX_DEFINITIONS = (
    ("idx_symbols_name", "symbols(name)"),
    ("idx_symbols_fqn", "symbols(fqn)"),
    ("idx_symbols_owner_fqn", "symbols(owner_fqn)"),
    ("idx_imports_file", "imports(file_id)"),
    ("idx_imports_form", "imports(form)"),
    ("idx_imports_outcome", "imports(outcome)"),
    ("idx_type_resolutions_file_name", "type_resolutions(file_id, name)"),
)


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
                parallel_jobs: Optional[int] = None, imports=None,
                resolutions=None) -> None:
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
        # The database is fresh, so maintaining secondary indexes row by row is
        # more expensive than building them once after the bulk inserts.
        for index_name, _definition in _INDEX_DEFINITIONS:
            connection.execute("DROP INDEX IF EXISTS " + index_name)
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
        imports = list(imports or [])
        resolutions = list(resolutions or [])
        import_forms = {form: 0 for form in _IMPORT_FORMS}
        import_outcomes = {outcome: 0 for outcome in _IMPORT_OUTCOMES}
        for record, resolution in imports:
            import_forms[record.form] = import_forms.get(record.form, 0) + 1
            import_outcomes[resolution.outcome] = import_outcomes.get(resolution.outcome, 0) + 1
        resolved = import_outcomes.get("resolved", 0)
        unresolved = import_outcomes.get("unresolved", 0)
        denominator = resolved + unresolved
        rate = (float(resolved) / denominator) if denominator else 0.0
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('import_count', ?)",
            (str(len(imports)),),
        )
        for form in sorted(import_forms):
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("import_form_" + form, str(import_forms[form])),
            )
        for outcome in sorted(import_outcomes):
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                ("import_outcome_" + outcome, str(import_outcomes[outcome])),
            )
        type_resolution_outcomes = {
            outcome: 0 for outcome in _TYPE_RESOLUTION_OUTCOMES
        }
        for resolution in resolutions:
            type_resolution_outcomes[resolution.outcome] = (
                type_resolution_outcomes.get(resolution.outcome, 0) + 1
            )
        for outcome in sorted(type_resolution_outcomes):
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                (
                    "type_resolution_outcome_" + outcome,
                    str(type_resolution_outcomes[outcome]),
                ),
            )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('type_resolution_outcomes', ?)",
            (
                json.dumps(
                    type_resolution_outcomes,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('internal_resolution_rate', ?)",
            ("%.6f" % rate,),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('import_forms', ?)",
            (json.dumps(import_forms, sort_keys=True, separators=(",", ":")),),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('import_outcomes', ?)",
            (json.dumps(import_outcomes, sort_keys=True, separators=(",", ":")),),
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
        def symbol_row(symbol):
            encoded_params = None
            if symbol.params is not None:
                encoded_params = json.dumps(
                    symbol.params, ensure_ascii=False, separators=(",", ":")
                )
            return (
                file_ids[symbol.path], symbol.name, symbol.kind, symbol.fqn,
                symbol.owner_fqn, encoded_params, symbol.param_count, symbol.signature,
                symbol.line, symbol.end_line, symbol.confidence,
            )

        connection.executemany(
            "INSERT INTO symbols(file_id, name, kind, fqn, owner_fqn, params, "
            "param_count, signature, line, end_line, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                symbol_row(symbol)
                for symbol in sorted(
                    symbols,
                    key=lambda item: (item.path, item.line, item.name, item.kind,
                                      item.fqn, item.signature)
                )
            )
        )

        def import_row(item):
            record, resolution = item
            return (
                file_ids[record.path], record.line, record.column, record.raw, record.form,
                record.name, resolution.target_fqn, resolution.internal_target,
                resolution.outcome,
                json.dumps(sorted(resolution.candidates), ensure_ascii=False,
                           separators=(",", ":")),
            )

        connection.executemany(
            "INSERT INTO imports(file_id, line, column, raw, form, name, target_fqn, "
            "internal_target, outcome, candidates) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                import_row(item)
                for item in sorted(
                    imports,
                    key=lambda item: (item[0].path, item[0].line, item[0].column,
                                      item[0].raw, item[0].form)
                )
            )
        )

        def resolution_row(resolution):
            return (
                file_ids[resolution.file], resolution.name, resolution.resolved_fqn,
                resolution.rule, resolution.outcome,
                json.dumps(sorted(resolution.candidates), ensure_ascii=False,
                           separators=(",", ":")),
            )

        connection.executemany(
            "INSERT INTO type_resolutions(file_id, name, resolved_fqn, rule, "
            "outcome, candidates) VALUES (?, ?, ?, ?, ?, ?)",
            (
                resolution_row(resolution)
                for resolution in sorted(resolutions, key=lambda item: (item.file, item.name))
            )
        )
        for index_name, definition in _INDEX_DEFINITIONS:
            connection.execute(
                "CREATE INDEX IF NOT EXISTS " + index_name + " ON " + definition
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
