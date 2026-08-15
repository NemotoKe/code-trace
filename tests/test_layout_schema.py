from __future__ import annotations

import os
import sqlite3
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LayoutAndSchemaTests(unittest.TestCase):
    def test_required_layout_exists(self):
        required = [
            "codewiki/__init__.py",
            "codewiki/__main__.py",
            "codewiki/config.py",
            "codewiki/parallel.py",
            "codewiki/index/__init__.py",
            "codewiki/index/scan.py",
            "codewiki/index/symbols.py",
            "codewiki/index/pipeline.py",
            "codewiki/store/__init__.py",
            "codewiki/store/db.py",
            "codewiki/store/schema.sql",
            "codewiki/query/__init__.py",
            "codewiki/query/symbols.py",
            "codewiki/cli.py",
        ]
        missing = [path for path in required if not os.path.isfile(os.path.join(ROOT, path))]
        self.assertEqual([], missing)

    def test_schema_creates_required_tables_columns_and_indexes(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        initialize(connection, repo_root="/repo")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({"files", "symbols", "meta"}.issubset(tables))
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(symbols)")
        }
        self.assertTrue(
            {
                "symbol_id", "file_id", "name", "kind", "fqn", "owner_fqn",
                "params", "param_count", "signature", "line", "end_line",
                "confidence",
            }.issubset(columns)
        )
        end_line = next(
            row for row in connection.execute("PRAGMA table_info(symbols)")
            if row[1] == "end_line"
        )
        self.assertEqual(0, end_line[3])
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(symbols)")
        }
        self.assertTrue(any("name" in index for index in indexes))
        self.assertTrue(any("fqn" in index for index in indexes))
        self.assertTrue(any("owner" in index for index in indexes))
        self.assertEqual("4", connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()[0])

    def test_wrong_schema_version_is_actionable(self):
        from codewiki.store.db import connect, initialize, validate_schema

        connection = connect(":memory:")
        initialize(connection, repo_root="/repo")
        connection.execute(
            "UPDATE meta SET value = '999' WHERE key = 'schema_version'"
        )
        connection.commit()
        with self.assertRaisesRegex(RuntimeError, "rerun index"):
            validate_schema(connection)


if __name__ == "__main__":
    unittest.main()
