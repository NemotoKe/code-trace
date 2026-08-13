from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest


class SupertypePersistenceTests(unittest.TestCase):
    def test_schema_and_writer_persist_supertype_resolution_rows(self):
        from codewiki.index.resolution import TypeResolution
        from codewiki.index.scan import FileRecord
        from codewiki.index.supertypes import SupertypeRef
        from codewiki.store import db

        record = FileRecord(
            path="src/p/Child.java",
            language="java",
            lines=5,
            sha256="child-sha",
            is_test=False,
            is_generated=False,
            package="p",
        )
        rows = [
            (
                SupertypeRef(
                    record.path, "p.Child", 4, "implements",
                    "java.util.List<String>", "java.util.List",
                ),
                TypeResolution(
                    record.path, "java.util.List", None, None, "external",
                    ["java.util.List"],
                ),
            ),
            (
                SupertypeRef(
                    record.path, "p.Child", 3, "extends", "Missing", "Missing",
                ),
                TypeResolution(
                    record.path, "Missing", None, None, "unresolved",
                    ["p.Missing"],
                ),
            ),
            (
                SupertypeRef(
                    record.path, "p.Child", 2, "extends", "Base<T>", "Base",
                ),
                TypeResolution(
                    record.path, "Base", "p.Base", 3, "resolved",
                    ["z.Candidate", "p.Base"],
                ),
            ),
        ]

        with tempfile.TemporaryDirectory(prefix="codewiki-supertype-db-") as out:
            db_path = os.path.join(out, "index.sqlite3")
            db.write_index(
                db_path,
                "/repo",
                [record],
                [],
                generated_at="2026-01-01T00:00:00+00:00",
                supertypes=list(reversed(rows)),
            )
            connection = db.open_index(db_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertIn("supertypes", tables)
                self.assertEqual(
                    [
                        "supertype_id", "file_id", "owner_fqn", "line", "relation",
                        "raw", "name", "target_fqn", "rule", "outcome", "candidates",
                    ],
                    [row[1] for row in connection.execute(
                        "PRAGMA table_info(supertypes)"
                    )],
                )
                indexes = {
                    row[1]
                    for row in connection.execute("PRAGMA index_list(supertypes)")
                }
                self.assertIn("idx_supertypes_owner", indexes)
                self.assertIn("idx_supertypes_target", indexes)
                actual = connection.execute(
                    "SELECT f.path, s.owner_fqn, s.line, s.relation, s.raw, s.name, "
                    "s.target_fqn, s.rule, s.outcome, s.candidates "
                    "FROM supertypes AS s JOIN files AS f USING(file_id) "
                    "ORDER BY s.supertype_id"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                ("src/p/Child.java", "p.Child", 2, "extends", "Base<T>", "Base",
                 "p.Base", 3, "resolved", '["p.Base","z.Candidate"]'),
                ("src/p/Child.java", "p.Child", 3, "extends", "Missing", "Missing",
                 None, None, "unresolved", '["p.Missing"]'),
                ("src/p/Child.java", "p.Child", 4, "implements",
                 "java.util.List<String>", "java.util.List", None, None,
                 "external", '["java.util.List"]'),
            ],
            actual,
        )
        self.assertEqual(["p.Base", "z.Candidate"], json.loads(actual[0][-1]))

    def test_pipeline_extracts_resolves_and_reindexes_supertype_rows(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index
        from tests.fixture import fixture_directory, write_fixture

        with fixture_directory() as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-supertype-out-1-") as out_one, \
                tempfile.TemporaryDirectory(prefix="codewiki-supertype-out-2-") as out_two:
            write_fixture(root)
            path = os.path.join(root, "src/com/acme/Mixed.java")
            with open(path, "w", encoding="utf-8") as stream:
                stream.write(
                    "package com.acme;\n"
                    "public class Mixed extends Missing "
                    "implements java.io.Serializable {}\n"
                )

            first = pipeline.run(root, out_one, jobs=1)
            self.assertEqual(3, first.supertypes_found)
            self.assertEqual(
                {"resolved": 1, "external": 1, "unresolved": 1, "excluded": 0},
                first.supertype_outcomes,
            )
            self.assertEqual(0.5, first.supertype_resolution_rate)
            self.assertGreaterEqual(first.timings["supertypes"], 0.0)

            def rows(db_path):
                connection = open_index(db_path)
                try:
                    return connection.execute(
                        "SELECT s.supertype_id, s.file_id, f.path, s.owner_fqn, s.line, "
                        "s.relation, s.raw, s.name, s.target_fqn, s.rule, s.outcome, "
                        "s.candidates FROM supertypes AS s JOIN files AS f USING(file_id) "
                        "ORDER BY s.supertype_id"
                    ).fetchall()
                finally:
                    connection.close()

            first_rows = rows(first.db_path)
            self.assertEqual(
                [
                    (1, 5, "src/com/acme/Mixed.java", "com.acme.Mixed", 2,
                     "extends", "Missing", "Missing", None, None,
                     "unresolved", "[]"),
                    (2, 5, "src/com/acme/Mixed.java", "com.acme.Mixed", 2,
                     "implements", "java.io.Serializable", "java.io.Serializable",
                     None, None, "external", '["java.io.Serializable"]'),
                    (3, 8, "src/com/acme/OrderRepository.java",
                     "com.acme.OrderRepository", 2, "implements", "OrderDao",
                     "OrderDao", "com.acme.OrderDao", 3, "resolved",
                     '["com.acme.OrderDao"]'),
                ],
                first_rows,
            )

            second = pipeline.run(root, out_two, jobs=1)
            self.assertEqual(first_rows, rows(second.db_path))

    def test_cli_reports_supertype_counts_rate_and_timing(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-supertype-cli-root-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-supertype-cli-out-") as out:
            os.makedirs(os.path.join(root, "src/p"))
            os.makedirs(os.path.join(root, "src/app"))
            os.makedirs(os.path.join(root, "generated"))
            with open(os.path.join(root, "src/p/Base.java"), "w", encoding="utf-8") as stream:
                stream.write("package p;\npublic class Base {}\n")
            with open(os.path.join(root, "generated/Present.java"), "w", encoding="utf-8") as stream:
                stream.write(
                    "// Code generated by fixture\n"
                    "package g;\npublic class Present {}\n"
                )
            with open(os.path.join(root, "src/app/Child.java"), "w", encoding="utf-8") as stream:
                stream.write(
                    "package app;\n"
                    "import p.Base;\n"
                    "public class Child extends Base implements Missing, "
                    "java.util.List, g.Missing {}\n"
                )

            completed = subprocess.run(
                [
                    sys.executable, "-m", "codewiki", "index", root,
                    "--out", out, "--jobs", "1",
                ],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("supertypes found: 4", completed.stdout)
        self.assertIn("supertypes outcome resolved: 1", completed.stdout)
        self.assertIn("supertypes outcome external: 1", completed.stdout)
        self.assertIn("supertypes outcome unresolved: 1", completed.stdout)
        self.assertIn("supertypes outcome excluded: 1", completed.stdout)
        self.assertIn("supertype resolution rate: 50.0%", completed.stdout)
        self.assertRegex(completed.stdout, r"(?m)^supertypes: [0-9]+\.[0-9]{3}s$")


if __name__ == "__main__":
    unittest.main()
