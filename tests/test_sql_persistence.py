from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


class SqlPersistenceTests(unittest.TestCase):
    @staticmethod
    def _write_file(root, relative_path, contents):
        path = os.path.join(root, relative_path)
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(contents)

    @staticmethod
    def _rows(db_path):
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT f.path, s.method_fqn, s.method_kind, s.line, s.verb, "
                "s.table_name, s.table_key, s.access, s.statement "
                "FROM sql_accesses AS s JOIN files AS f USING(file_id) "
                "ORDER BY s.access_id"
            ).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _all_sql_rows(db_path):
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT access_id, file_id, method_fqn, method_kind, line, verb, "
                "table_name, table_key, access, statement FROM sql_accesses "
                "ORDER BY access_id"
            ).fetchall()
        finally:
            connection.close()

    def test_pipeline_persists_select_insert_and_delete_accesses(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class OrderRepository {\n"
            "    void execute() {\n"
            "        String read = \"SELECT * FROM Orders\";\n"
            "        String create = \"INSERT INTO AuditLog (id) VALUES (?)\";\n"
            "        String remove = \"DELETE FROM OldOrders WHERE id = ?\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-out-") as out:
            self._write_file(root, "src/p/OrderRepository.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._rows(result.db_path)

        self.assertEqual(3, result.sql_statements_found)
        self.assertEqual(3, result.sql_access_rows)
        self.assertEqual(
            [
                (
                    "src/p/OrderRepository.java", "p.OrderRepository.execute",
                    "method", 4, "select", "Orders", "orders", "READ",
                    "SELECT * FROM Orders",
                ),
                (
                    "src/p/OrderRepository.java", "p.OrderRepository.execute",
                    "method", 5, "insert", "AuditLog", "auditlog", "WRITE",
                    "INSERT INTO AuditLog (id) VALUES (?)",
                ),
                (
                    "src/p/OrderRepository.java", "p.OrderRepository.execute",
                    "method", 6, "delete", "OldOrders", "oldorders", "WRITE",
                    "DELETE FROM OldOrders WHERE id = ?",
                ),
            ],
            rows,
        )

    def test_pipeline_folds_table_key_case(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class Lookup {\n"
            "    void read() {\n"
            "        String first = \"SELECT * FROM Orders\";\n"
            "        String second = \"select * from ORDERS\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-case-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-case-out-") as out:
            self._write_file(root, "src/p/Lookup.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._rows(result.db_path)

        self.assertEqual(2, result.sql_statements_found)
        self.assertEqual(2, result.sql_access_rows)
        self.assertEqual(
            [("Orders", "orders"), ("ORDERS", "orders")],
            [(row[5], row[6]) for row in rows],
        )

    def test_repeated_indexing_has_identical_sql_access_rows(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class Repository {\n"
            "    void run() {\n"
            "        String merge = \"MERGE INTO Orders USING staging ON (Orders.id = staging.id)\";\n"
            "        String read = \"SELECT * FROM orders\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-repeat-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-repeat-out-one-") as out_one, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-repeat-out-two-") as out_two:
            self._write_file(root, "src/p/Repository.java", source)
            first = pipeline.run(root, out_one, jobs=1)
            second = pipeline.run(root, out_two, jobs=1)
            first_rows = self._all_sql_rows(first.db_path)
            second_rows = self._all_sql_rows(second.db_path)

        self.assertEqual(first_rows, second_rows)
        self.assertEqual(first.sql_access_rows, len(first_rows))
        self.assertEqual(second.sql_access_rows, len(second_rows))

    def test_schema_contains_sql_accesses_table_and_indexes(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        try:
            initialize(connection, repo_root="/repo")
            self.assertEqual(
                [
                    "access_id", "file_id", "method_fqn", "method_kind", "line",
                    "verb", "table_name", "table_key", "access", "statement",
                ],
                [row[1] for row in connection.execute(
                    "PRAGMA table_info(sql_accesses)"
                )],
            )
            indexes = {
                row[1] for row in connection.execute(
                    "PRAGMA index_list(sql_accesses)"
                )
            }
            self.assertEqual(
                {
                    "idx_sql_accesses_table", "idx_sql_accesses_method",
                    "idx_sql_accesses_file",
                },
                indexes,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
