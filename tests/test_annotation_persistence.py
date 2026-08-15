from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


class AnnotationPersistenceTests(unittest.TestCase):
    @staticmethod
    def _write_file(root, relative_path, source):
        path = os.path.join(root, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(source)

    @staticmethod
    def _rows(db_path):
        connection = sqlite3.connect(db_path)
        try:
            return connection.execute(
                "SELECT f.path, a.owner_fqn, a.owner_kind, a.name, "
                "a.simple_name, a.line, a.raw "
                "FROM annotations AS a JOIN files AS f USING(file_id) "
                "ORDER BY a.annotation_id"
            ).fetchall()
        finally:
            connection.close()

    def test_pipeline_persists_type_and_method_annotations(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "\n"
            "@Service\n"
            "@First\n"
            "@Second\n"
            "class Example {\n"
            "\n"
            "    @Override\n"
            "    @jakarta.ws.rs.GET\n"
            "    void run(@Nonnull String value) {}\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-annotation-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-annotation-out-") as out:
            self._write_file(root, "src/p/Example.java", source)
            result = pipeline.run(root, out, jobs=1)
            rows = self._rows(result.db_path)

        self.assertEqual(5, result.annotations_found)
        self.assertEqual(
            [
                (
                    "src/p/Example.java", "p.Example", "class", "Service",
                    "Service", 3, "@Service",
                ),
                (
                    "src/p/Example.java", "p.Example", "class", "First",
                    "First", 4, "@First",
                ),
                (
                    "src/p/Example.java", "p.Example", "class", "Second",
                    "Second", 5, "@Second",
                ),
                (
                    "src/p/Example.java", "p.Example.run", "method", "Override",
                    "Override", 8, "@Override",
                ),
                (
                    "src/p/Example.java", "p.Example.run", "method",
                    "jakarta.ws.rs.GET", "GET", 9, "@jakarta.ws.rs.GET",
                ),
            ],
            rows,
        )
        self.assertEqual(3, sum(row[2] == "class" for row in rows))
        self.assertEqual(2, sum(row[3] in ("First", "Second") for row in rows))
        self.assertNotIn("Nonnull", [row[3] for row in rows])

    def test_schema_contains_annotations_table_and_indexes(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        try:
            initialize(connection, repo_root="/repo")
            self.assertEqual(
                [
                    "annotation_id", "file_id", "owner_fqn", "owner_kind",
                    "name", "simple_name", "line", "raw",
                ],
                [row[1] for row in connection.execute(
                    "PRAGMA table_info(annotations)"
                )],
            )
            indexes = {
                row[1] for row in connection.execute(
                    "PRAGMA index_list(annotations)"
                )
            }
            self.assertEqual(
                {
                    "idx_annotations_simple_name",
                    "idx_annotations_owner",
                    "idx_annotations_file",
                },
                indexes,
            )
        finally:
            connection.close()

    def test_repeated_indexing_has_identical_annotation_rows(self):
        from codewiki.index import pipeline

        source = (
            "package p;\n"
            "@B\n"
            "@A\n"
            "class Example {}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-annotation-repeat-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-annotation-repeat-out-one-") as out_one, \
                tempfile.TemporaryDirectory(prefix="codewiki-annotation-repeat-out-two-") as out_two:
            self._write_file(root, "src/p/Example.java", source)
            first = pipeline.run(root, out_one, jobs=1)
            second = pipeline.run(root, out_two, jobs=1)
            first_rows = self._rows(first.db_path)
            second_rows = self._rows(second.db_path)

        self.assertEqual(first_rows, second_rows)
        self.assertEqual(2, first.annotations_found)
        self.assertEqual(2, second.annotations_found)


if __name__ == "__main__":
    unittest.main()
