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

    @staticmethod
    def _column_rows(db_path):
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT f.path, c.method_fqn, c.method_kind, c.line, c.verb, "
                "c.table_name, c.table_key, c.column_name, c.column_key, "
                "c.access, c.statement "
                "FROM sql_column_accesses AS c JOIN files AS f USING(file_id) "
                "ORDER BY c.column_access_id"
            ).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _all_sql_column_rows(db_path):
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT column_access_id, file_id, method_fqn, method_kind, line, "
                "verb, table_name, table_key, column_name, column_key, access, "
                "statement FROM sql_column_accesses ORDER BY column_access_id"
            ).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _sql_rows_in_access_id_order(db_path):
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT f.path, s.method_fqn, s.method_kind, s.line, s.verb, "
                "s.table_name, s.access, s.statement "
                "FROM sql_accesses AS s JOIN files AS f USING(file_id) "
                "ORDER BY s.access_id"
            ).fetchall()
        finally:
            connection.close()

    @staticmethod
    def _insert_file(connection):
        connection.execute(
            "INSERT INTO files(path, language, package, lines, sha256, "
            "is_test, is_generated) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("src/p/Repo.java", "java", "p", 1, "fixture", 0, 0),
        )

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

    def test_pipeline_persists_written_sql_columns(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class OrderRepository {\n"
            "    void execute() {\n"
            "        String update = \"UPDATE ORDERS SET STATUS = ?, UPDATED_AT = ?\";\n"
            "        String create = \"insert into audit_log (id, note) values (?, ?)\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-column-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-column-out-") as out:
            self._write_file(root, "src/p/OrderRepository.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._column_rows(result.db_path)

        self.assertEqual(2, result.sql_statements_found)
        self.assertEqual(4, result.sql_column_rows)
        self.assertEqual(
            [
                (
                    "src/p/OrderRepository.java", "p.OrderRepository.execute",
                    "method", 4, "update", "ORDERS", "orders", "STATUS",
                    "status", "WRITE",
                    "UPDATE ORDERS SET STATUS = ?, UPDATED_AT = ?",
                ),
                (
                    "src/p/OrderRepository.java", "p.OrderRepository.execute",
                    "method", 4, "update", "ORDERS", "orders", "UPDATED_AT",
                    "updated_at", "WRITE",
                    "UPDATE ORDERS SET STATUS = ?, UPDATED_AT = ?",
                ),
                (
                    "src/p/OrderRepository.java", "p.OrderRepository.execute",
                    "method", 5, "insert", "audit_log", "audit_log", "id",
                    "id", "WRITE",
                    "insert into audit_log (id, note) values (?, ?)",
                ),
                (
                    "src/p/OrderRepository.java", "p.OrderRepository.execute",
                    "method", 5, "insert", "audit_log", "audit_log", "note",
                    "note", "WRITE",
                    "insert into audit_log (id, note) values (?, ?)",
                ),
            ],
            rows,
        )

    def test_pipeline_persists_read_and_written_sql_columns(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class OrderRepository {\n"
            "    void execute() {\n"
            "        String update = \"UPDATE ORDERS SET STATUS = ? WHERE ID = ?\";\n"
            "        String select = \"SELECT STATUS FROM ORDERS WHERE ID = ?\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-read-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-read-out-") as out:
            self._write_file(root, "src/p/OrderRepository.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._column_rows(result.db_path)

        self.assertEqual(4, result.sql_column_rows)
        self.assertEqual(
            [
                ("ORDERS", "ID", "READ"),
                ("ORDERS", "STATUS", "WRITE"),
                ("ORDERS", "ID", "READ"),
                ("ORDERS", "STATUS", "READ"),
            ],
            [(row[5], row[7], row[9]) for row in rows],
        )

    def test_pipeline_keeps_write_and_read_rows_for_same_column(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class Repository {\n"
            "    void execute() {\n"
            "        String update = \"UPDATE t SET a = ? WHERE a = 1\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-dual-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-dual-out-") as out:
            self._write_file(root, "src/p/Repository.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._column_rows(result.db_path)

        self.assertEqual(2, result.sql_column_rows)
        self.assertEqual(
            [("t", "a", "READ"), ("t", "a", "WRITE")],
            [(row[5], row[7], row[9]) for row in rows],
        )

    def test_pipeline_preserves_raw_multiline_sql_for_column_reads(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class Repository {\n"
            "    void execute() {\n"
            "        String select = \"\"\"\n"
            "            SELECT STATUS\n"
            "            FROM ORDERS -- keep parsing the next line\n"
            "            WHERE ID = ?\n"
            "            \"\"\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-raw-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-raw-out-") as out:
            self._write_file(root, "src/p/Repository.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._column_rows(result.db_path)

        self.assertEqual(2, result.sql_column_rows)
        self.assertEqual(
            [("ORDERS", "ID", "READ"), ("ORDERS", "STATUS", "READ")],
            [(row[5], row[7], row[9]) for row in rows],
        )
        self.assertIn("\n", rows[0][10])

    def test_pipeline_folds_table_and_column_keys_case(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class Lookup {\n"
            "    void update() {\n"
            "        String first = \"UPDATE Orders SET Status = ?\";\n"
            "        String second = \"update ORDERS set STATUS = ?\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-column-case-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-column-case-out-") as out:
            self._write_file(root, "src/p/Lookup.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._column_rows(result.db_path)

        self.assertEqual(2, result.sql_column_rows)
        self.assertEqual(
            [("Orders", "orders", "Status", "status"),
             ("ORDERS", "orders", "STATUS", "status")],
            [(row[5], row[6], row[7], row[8]) for row in rows],
        )

    def test_pipeline_persists_sql_accesses_in_canonical_order(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class Repo {\n"
            "    void zzz() {\n"
            "        String read = \"SELECT * FROM Orders\";\n"
            "    }\n"
            "    void aaa() {\n"
            "        String create = \"INSERT INTO AuditLog (id) VALUES (?)\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-order-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-order-out-") as out:
            self._write_file(root, "src/p/Repo.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._sql_rows_in_access_id_order(result.db_path)

        self.assertEqual(2, result.sql_access_rows)
        self.assertEqual(
            [
                (
                    "src/p/Repo.java", "p.Repo.aaa", "method", 7, "insert",
                    "AuditLog", "WRITE", "INSERT INTO AuditLog (id) VALUES (?)",
                ),
                (
                    "src/p/Repo.java", "p.Repo.zzz", "method", 4, "select",
                    "Orders", "READ", "SELECT * FROM Orders",
                ),
            ],
            rows,
        )
        # The later aaa method sorts first by FQN, so the fixture reverses
        # source order and canonical order by construction.
        self.assertGreater(rows[0][3], rows[1][3])

    def test_sql_accesses_reject_invalid_access(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        try:
            initialize(connection, repo_root="/repo")
            self._insert_file(connection)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO sql_accesses(file_id, method_fqn, method_kind, "
                    "line, verb, table_name, table_key, access, statement) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        1, "p.Repo.run", "method", 2, "select", "Orders",
                        "orders", "MAYBE", "SELECT * FROM Orders",
                    ),
                )
        finally:
            connection.close()

    def test_sql_accesses_reject_invalid_verb(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        try:
            initialize(connection, repo_root="/repo")
            self._insert_file(connection)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO sql_accesses(file_id, method_fqn, method_kind, "
                    "line, verb, table_name, table_key, access, statement) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        1, "p.Repo.run", "method", 2, "maybe", "Orders",
                        "orders", "READ", "SELECT * FROM Orders",
                    ),
                )
        finally:
            connection.close()

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

    def test_repeated_indexing_has_identical_sql_column_rows(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "class Repository {\n"
            "    void run() {\n"
            "        String update = \"UPDATE orders SET status = ?, updated_at = ?\";\n"
            "        String create = \"INSERT INTO audit_log (id, note) VALUES (?, ?)\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-column-repeat-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-column-repeat-out-one-") as out_one, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-column-repeat-out-two-") as out_two:
            self._write_file(root, "src/p/Repository.java", source)
            first = pipeline.run(root, out_one, jobs=1)
            second = pipeline.run(root, out_two, jobs=1)
            first_rows = self._all_sql_column_rows(first.db_path)
            second_rows = self._all_sql_column_rows(second.db_path)

        self.assertEqual(first_rows, second_rows)
        self.assertEqual(first.sql_column_rows, len(first_rows))
        self.assertEqual(second.sql_column_rows, len(second_rows))

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

    def test_schema_contains_sql_column_accesses_table_and_indexes(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        try:
            initialize(connection, repo_root="/repo")
            self.assertEqual(
                [
                    "column_access_id", "file_id", "method_fqn", "method_kind",
                    "line", "verb", "table_name", "table_key", "column_name",
                    "column_key", "access", "statement",
                ],
                [row[1] for row in connection.execute(
                    "PRAGMA table_info(sql_column_accesses)"
                )],
            )
            indexes = {
                row[1] for row in connection.execute(
                    "PRAGMA index_list(sql_column_accesses)"
                )
            }
            self.assertEqual(
                {
                    "idx_sql_column_accesses_column",
                    "idx_sql_column_accesses_method",
                    "idx_sql_column_accesses_file",
                },
                indexes,
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
