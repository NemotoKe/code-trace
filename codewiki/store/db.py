from __future__ import annotations

import os
import sqlite3
import json
import tempfile
from datetime import datetime, timezone
from typing import List, Optional

SCHEMA_VERSION = "5"
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
    ("idx_supertypes_owner", "supertypes(owner_fqn)"),
    ("idx_supertypes_target", "supertypes(target_fqn)"),
    ("idx_calls_caller", "calls(caller_fqn)"),
    ("idx_calls_target", "calls(target_fqn)"),
    ("idx_calls_name", "calls(name)"),
    ("idx_calls_file", "calls(file_id)"),
    ("idx_sql_accesses_table", "sql_accesses(table_key)"),
    ("idx_sql_accesses_method", "sql_accesses(method_fqn)"),
    ("idx_sql_accesses_file", "sql_accesses(file_id)"),
    ("idx_sql_column_accesses_column", "sql_column_accesses(table_key, column_key)"),
    ("idx_sql_column_accesses_method", "sql_column_accesses(method_fqn)"),
    ("idx_sql_column_accesses_file", "sql_column_accesses(file_id)"),
    ("idx_annotations_simple_name", "annotations(simple_name)"),
    ("idx_annotations_owner", "annotations(owner_fqn)"),
    ("idx_annotations_file", "annotations(file_id)"),
    ("idx_entrypoints_method", "entrypoints(method_fqn)"),
    ("idx_entrypoints_kind", "entrypoints(kind)"),
    ("idx_entrypoints_file", "entrypoints(file_id)"),
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
                resolutions=None, supertypes=None, calls=None,
                sql_accesses=None, sql_column_accesses=None,
                annotations=None, entrypoints=None) -> None:
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
        supertypes = list(supertypes or [])
        calls = list(calls or [])
        sql_accesses = list(sql_accesses or [])
        sql_column_accesses = list(sql_column_accesses or [])
        annotations = list(annotations or [])
        entrypoints = list(entrypoints or [])
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

        def supertype_row(item):
            ref, resolution = item
            target_fqn = (
                resolution.resolved_fqn
                if resolution.outcome == "resolved" else None
            )
            return (
                file_ids[ref.path], ref.owner_fqn, ref.line, ref.relation,
                ref.raw, ref.name, target_fqn, resolution.rule,
                resolution.outcome,
                json.dumps(sorted(resolution.candidates), ensure_ascii=False,
                           separators=(",", ":")),
            )

        connection.executemany(
            "INSERT INTO supertypes(file_id, owner_fqn, line, relation, raw, name, "
            "target_fqn, rule, outcome, candidates) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                supertype_row(item)
                for item in sorted(
                    supertypes,
                    key=lambda item: (
                        item[0].path, item[0].line, item[0].owner_fqn,
                        item[0].relation, item[0].raw, item[0].name,
                    )
                )
            )
        )

        def call_row(resolution, target_fqn, candidates):
            site = resolution.site
            return (
                file_ids[site.path], site.enclosing_fqn, site.enclosing_kind,
                site.line, site.form, site.receiver, site.name,
                resolution.owner_fqn, target_fqn, resolution.confidence,
                resolution.reason,
                json.dumps(candidates, ensure_ascii=False,
                           separators=(",", ":")),
            )

        expanded_calls = []
        for resolution in calls:
            candidates = sorted(set(resolution.targets))
            targets = candidates or [None]
            for target_fqn in targets:
                expanded_calls.append((resolution, target_fqn, candidates))

        def call_sort_key(item):
            resolution, target_fqn, candidates = item
            site = resolution.site
            return (
                site.path, site.enclosing_fqn, site.enclosing_kind, site.line,
                site.form, site.receiver or "", site.name,
                resolution.owner_fqn or "", target_fqn or "",
                resolution.confidence, resolution.reason,
                json.dumps(candidates, ensure_ascii=False, separators=(",", ":")),
            )

        connection.executemany(
            "INSERT INTO calls(file_id, caller_fqn, caller_kind, line, form, "
            "receiver, name, owner_fqn, target_fqn, confidence, reason, candidates) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                call_row(resolution, target_fqn, candidates)
                for resolution, target_fqn, candidates
                in sorted(expanded_calls, key=call_sort_key)
            )
        )

        def sql_access_row(item):
            statement, access = item
            table_name = access.table
            return (
                file_ids[statement.path], statement.enclosing_fqn,
                statement.enclosing_kind, statement.line, statement.verb,
                table_name, table_name.casefold(), access.access,
                statement.statement,
            )

        def sql_access_sort_key(item):
            statement, access = item
            return (
                statement.path, statement.enclosing_fqn,
                statement.enclosing_kind, statement.line, statement.verb,
                access.table, access.access, statement.statement,
            )

        connection.executemany(
            "INSERT INTO sql_accesses(file_id, method_fqn, method_kind, line, "
            "verb, table_name, table_key, access, statement) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sql_access_row(item)
                for item in sorted(sql_accesses, key=sql_access_sort_key)
            )
        )

        def sql_column_access_row(item):
            statement, column, access = item
            table_name = column.table
            column_name = column.column
            return (
                file_ids[statement.path], statement.enclosing_fqn,
                statement.enclosing_kind, statement.line, statement.verb,
                table_name, table_name.casefold(), column_name,
                column_name.casefold(), access, statement.statement,
            )

        def sql_column_access_sort_key(item):
            statement, column, access = item
            return (
                statement.path, statement.enclosing_fqn,
                statement.enclosing_kind, statement.line, statement.verb,
                column.table, column.column, access, statement.statement,
            )

        connection.executemany(
            "INSERT INTO sql_column_accesses(file_id, method_fqn, method_kind, "
            "line, verb, table_name, table_key, column_name, column_key, "
            "access, statement) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sql_column_access_row(item)
                for item in sorted(
                    sql_column_accesses, key=sql_column_access_sort_key
                )
            )
        )

        def annotation_row(annotation):
            return (
                file_ids[annotation.path], annotation.owner_fqn,
                annotation.owner_kind, annotation.name,
                annotation.name.rsplit(".", 1)[-1], annotation.line,
                annotation.raw,
            )

        def annotation_sort_key(annotation):
            return (
                annotation.path, annotation.owner_fqn, annotation.owner_kind,
                annotation.line, annotation.name, annotation.raw,
            )

        connection.executemany(
            "INSERT INTO annotations(file_id, owner_fqn, owner_kind, name, "
            "simple_name, line, raw) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                annotation_row(annotation)
                for annotation in sorted(annotations, key=annotation_sort_key)
            )
        )

        def entrypoint_row(entrypoint):
            return (
                file_ids[entrypoint.path], entrypoint.method_fqn,
                entrypoint.owner_fqn, entrypoint.kind, entrypoint.reason,
                entrypoint.line,
            )

        def entrypoint_sort_key(entrypoint):
            return (
                entrypoint.path, entrypoint.line, entrypoint.method_fqn,
                entrypoint.owner_fqn, entrypoint.kind, entrypoint.reason,
            )

        connection.executemany(
            "INSERT INTO entrypoints(file_id, method_fqn, owner_fqn, kind, "
            "reason, line) VALUES (?, ?, ?, ?, ?, ?)",
            (
                entrypoint_row(entrypoint)
                for entrypoint in sorted(entrypoints, key=entrypoint_sort_key)
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
