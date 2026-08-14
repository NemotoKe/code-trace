from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class CallPersistenceTests(unittest.TestCase):
    @staticmethod
    def _write_file(root, relative_path, contents):
        path = os.path.join(root, relative_path)
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(contents)

    @classmethod
    def _write_call_repository(cls, root, extra_files=0):
        cls._write_file(
            root,
            "src/p/Caller.java",
            "package p;\n"
            "class Caller {\n"
            "    void run(Dao dao) { dao.save(); unknown.missing(); "
            "dao.save(); missing(); Dao::save; new Dao(); }\n"
            "}\n",
        )
        cls._write_file(
            root,
            "src/p/Dao.java",
            "package p;\nclass Dao { void save() {} }\n",
        )
        for index in range(extra_files):
            package = "extra%03d" % index
            name = "Type%03d" % index
            cls._write_file(
                root,
                "src/%s/%s.java" % (package, name),
                "package %s;\nclass %s {}\n" % (package, name),
            )

    @staticmethod
    def _call_rows(db_path):
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                "SELECT c.call_id, f.path, c.caller_fqn, c.caller_kind, c.line, "
                "c.form, c.receiver, c.name, c.owner_fqn, c.target_fqn, "
                "c.confidence, c.reason, c.candidates "
                "FROM calls AS c JOIN files AS f USING(file_id) "
                "ORDER BY c.call_id"
            ).fetchall()
            return [row[:-1] + (json.loads(row[-1]),) for row in rows]
        finally:
            connection.close()

    def test_pipeline_extracts_resolves_and_persists_call_rows_and_counts(self):
        from codewiki.index import pipeline

        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            self._write_call_repository(root)
            events = []
            result = pipeline.run(
                root,
                out,
                jobs=1,
                progress=lambda stage, message: events.append((stage, message)),
            )

            self.assertEqual(6, result.calls_found)
            self.assertEqual(
                {
                    "receiver": 3,
                    "bare": 1,
                    "chained": 0,
                    "method_ref": 1,
                    "constructor": 1,
                },
                result.call_forms,
            )
            self.assertEqual(
                {"CONFIRMED": 2, "POSSIBLE": 0, "UNRESOLVED": 4},
                result.call_confidences,
            )
            self.assertAlmostEqual(2.0 / 3.0, result.call_resolution_rate)
            self.assertGreaterEqual(result.timings["calls"], 0.0)
            self.assertIn(("calls", "resolving Java calls"), events)

            rows = self._call_rows(result.db_path)
            self.assertEqual(6, len(rows))
            self.assertEqual(
                [
                    ("bare", None, "missing"),
                    ("constructor", None, "Dao"),
                    ("method_ref", "Dao", "save"),
                ],
                [(row[5], row[6], row[7]) for row in rows if row[5] != "receiver"],
            )
            self.assertEqual(
                [
                    (
                        "dao", "save", "p.Dao", "p.Dao.save", "CONFIRMED",
                        "single_member", ["p.Dao.save"],
                    ),
                    (
                        "dao", "save", "p.Dao", "p.Dao.save", "CONFIRMED",
                        "single_member", ["p.Dao.save"],
                    ),
                    (
                        "unknown", "missing", None, None, "UNRESOLVED",
                        "no_declaration", [],
                    ),
                ],
                [
                    (
                        row[6], row[7], row[8], row[9], row[10], row[11],
                        row[12],
                    )
                    for row in rows if row[5] == "receiver"
                ],
            )
            for row in rows:
                self.assertEqual("p.Caller.run", row[2])
                self.assertEqual("method", row[3])
                self.assertEqual(3, row[4])
                if row[5] != "receiver":
                    self.assertIsNone(row[8])
                    self.assertIsNone(row[9])
                    self.assertEqual("UNRESOLVED", row[10])
                    self.assertEqual("form_not_resolved", row[11])
                    self.assertEqual([], row[12])

            connection = sqlite3.connect(result.db_path)
            try:
                meta_keys = {
                    row[0] for row in connection.execute("SELECT key FROM meta")
                }
            finally:
                connection.close()
            self.assertFalse(
                meta_keys.intersection({
                    "scan", "symbols", "imports", "supertypes", "calls",
                    "persist", "total",
                })
            )

    def test_pipeline_counts_call_sites_separately_from_call_rows(self):
        from codewiki.index import pipeline

        with tempfile.TemporaryDirectory(prefix="codewiki-call-ambiguous-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-ambiguous-out-") as out:
            self._write_file(
                root,
                "src/p/Caller.java",
                "package p;\n"
                "class Caller {\n"
                "    void run(C value) { value.run(); }\n"
                "}\n",
            )
            self._write_file(
                root,
                "src/p/L.java",
                "package p;\ninterface L { void run(); }\n",
            )
            self._write_file(
                root,
                "src/p/R.java",
                "package p;\ninterface R { void run(); }\n",
            )
            self._write_file(
                root,
                "src/p/C.java",
                "package p;\nclass C implements L, R {}\n",
            )

            result = pipeline.run(root, out, jobs=1)

            self.assertEqual(1, result.calls_found)
            self.assertEqual(2, result.calls_rows)
            self.assertEqual(
                {
                    "receiver": 1,
                    "bare": 0,
                    "chained": 0,
                    "method_ref": 0,
                    "constructor": 0,
                },
                result.call_forms,
            )
            self.assertEqual(
                {"CONFIRMED": 0, "POSSIBLE": 1, "UNRESOLVED": 0},
                result.call_confidences,
            )

            connection = sqlite3.connect(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT target_fqn, candidates FROM calls ORDER BY call_id"
                ).fetchall()
            finally:
                connection.close()

            indexed = subprocess.run(
                [
                    sys.executable, "-m", "codewiki", "index", root,
                    "--out", out, "--jobs", "1", "--quiet",
                ],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertEqual(
            [
                ('p.L.run', '["p.L.run","p.R.run"]'),
                ('p.R.run', '["p.L.run","p.R.run"]'),
            ],
            rows,
        )
        self.assertEqual(0, indexed.returncode, indexed.stderr)
        self.assertIn("calls found: 1", indexed.stdout)
        self.assertIn("calls rows: 2", indexed.stdout)
        self.assertIn("calls form receiver: 1", indexed.stdout)
        self.assertIn("calls confidence POSSIBLE: 1", indexed.stdout)

    def test_pipeline_reads_each_java_analysis_item_once_and_keeps_call_resolution(self):
        from unittest.mock import patch

        from codewiki.index import pipeline

        with tempfile.TemporaryDirectory(prefix="codewiki-call-read-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-read-out-") as out:
            self._write_call_repository(root)
            with patch.object(
                pipeline.scan,
                "read_text",
                wraps=pipeline.scan.read_text,
            ) as read_text:
                result = pipeline.run(root, out, jobs=1)

            self.assertEqual(2, result.files_analyzed)
            self.assertEqual(2, read_text.call_count)
            self.assertEqual(
                ["src/p/Caller.java", "src/p/Dao.java"],
                sorted(call[0][1] for call in read_text.call_args_list),
            )
            rows = self._call_rows(result.db_path)
            self.assertEqual(6, len(rows))
            self.assertEqual(
                2,
                sum(
                    row[10] == "CONFIRMED" and row[5] == "receiver"
                    for row in rows
                ),
            )

    def test_pipeline_call_rows_match_between_serial_and_real_parallel_runs(self):
        from codewiki.index import pipeline

        with tempfile.TemporaryDirectory(prefix="codewiki-call-many-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-many-one-") as one, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-many-two-") as two:
            self._write_call_repository(root, extra_files=398)
            first = pipeline.run(root, one, jobs=1)
            second = pipeline.run(root, two, jobs=2)

            self.assertEqual(400, first.files_analyzed)
            self.assertEqual(400, second.files_analyzed)
            self.assertEqual(2, second.parallel_jobs)
            self.assertEqual(
                self._call_rows(first.db_path),
                self._call_rows(second.db_path),
            )
            self.assertEqual(6, len(self._call_rows(second.db_path)))

    def test_cli_reports_call_counts_rate_and_timing(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-cli-root-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-cli-out-") as out:
            self._write_call_repository(root)
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
        for line in (
            "calls found: 6",
            "calls rows: same as call sites",
            "calls form receiver: 3",
            "calls form bare: 1",
            "calls form chained: 0",
            "calls form method_ref: 1",
            "calls form constructor: 1",
            "calls confidence CONFIRMED: 2",
            "calls confidence POSSIBLE: 0",
            "calls confidence UNRESOLVED: 4",
            "call resolution rate (receiver forms only): 66.7%",
        ):
            self.assertIn(line, completed.stdout)
        self.assertRegex(completed.stdout, r"(?m)^calls: [0-9]+\.[0-9]{3}s$")

    def test_pipeline_persists_chained_non_receiver_as_unresolved_json(self):
        from codewiki.index import pipeline

        with tempfile.TemporaryDirectory(prefix="codewiki-call-chain-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-chain-out-") as out:
            self._write_file(
                root,
                "src/p/Caller.java",
                "package p;\n"
                "class Caller {\n"
                "    void run() { make().finish(); }\n"
                "}\n",
            )
            result = pipeline.run(root, out, jobs=1)

            connection = sqlite3.connect(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT form, receiver, owner_fqn, target_fqn, confidence, "
                    "reason, candidates FROM calls ORDER BY call_id"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                ("bare", None, None, None, "UNRESOLVED", "form_not_resolved", "[]"),
                ("chained", None, None, None, "UNRESOLVED", "form_not_resolved", "[]"),
            ],
            rows,
        )
        self.assertEqual([[], []], [json.loads(row[-1]) for row in rows])

    def test_schema_has_exact_calls_columns_and_indexes(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        try:
            initialize(connection, repo_root="/repo")
            self.assertEqual(
                [
                    "call_id", "file_id", "caller_fqn", "caller_kind", "line",
                    "form", "receiver", "name", "owner_fqn", "target_fqn",
                    "confidence", "reason", "candidates",
                ],
                [row[1] for row in connection.execute("PRAGMA table_info(calls)")],
            )
            index_rows = list(connection.execute("PRAGMA index_list(calls)"))
            self.assertEqual(
                {
                    "idx_calls_caller", "idx_calls_target", "idx_calls_name",
                    "idx_calls_file",
                },
                {row[1] for row in index_rows},
            )
            self.assertTrue(all(row[2] == 0 for row in index_rows))
            self.assertFalse(any(row[1].startswith("sqlite_autoindex_calls")
                                 for row in index_rows))
        finally:
            connection.close()

    def test_writer_persists_sorted_call_resolution_rows_and_duplicates(self):
        from codewiki.index.callgraph import CallResolution
        from codewiki.index.calls import CallSite
        from codewiki.index.scan import FileRecord
        from codewiki.store import db

        records = [
            FileRecord(
                path="src/p/Zed.java", language="java", lines=20,
                sha256="zed-sha", is_test=False, is_generated=False, package="p",
            ),
            FileRecord(
                path="src/p/Caller.java", language="java", lines=25,
                sha256="caller-sha", is_test=False, is_generated=False, package="p",
            ),
        ]
        chained = CallResolution(
            CallSite(
                "src/p/Caller.java", "p.Caller.run", "method", 7,
                "chained", None, "finish",
            ),
            "p.Foo", ("p.Foo.finish",), "POSSIBLE", "chained_member",
        )
        method_reference = CallResolution(
            CallSite(
                "src/p/Caller.java", "p.Caller.run", "method", 7,
                "method_ref", "Foo", "run",
            ),
            "p.Foo", ("p.Foo.run",), "CONFIRMED", "method_reference",
        )
        unresolved = CallResolution(
            CallSite(
                "src/p/Caller.java", "p.Caller.run", "method", 20,
                "bare", None, "missing",
            ),
            None, (), "UNRESOLVED", "no_declaration",
        )
        receiver = CallResolution(
            CallSite(
                "src/p/Zed.java", "p.Zed.run", "method", 12,
                "receiver", "foo", "run",
            ),
            "p.Foo", ("p.Foo.run",), "CONFIRMED", "single_member",
        )
        calls = [receiver, method_reference, unresolved, method_reference, chained]

        with tempfile.TemporaryDirectory(prefix="codewiki-call-db-") as out:
            db_path = os.path.join(out, "index.sqlite3")
            db.write_index(
                db_path,
                "/repo",
                records,
                [],
                generated_at="2026-01-01T00:00:00+00:00",
                calls=calls,
            )
            connection = db.open_index(db_path)
            try:
                actual = connection.execute(
                    "SELECT c.call_id, f.path, c.caller_fqn, c.caller_kind, c.line, "
                    "c.form, c.receiver, c.name, c.owner_fqn, c.target_fqn, "
                    "c.confidence, c.reason, c.candidates "
                    "FROM calls AS c JOIN files AS f USING(file_id) "
                    "ORDER BY c.call_id"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                (1, "src/p/Caller.java", "p.Caller.run", "method", 7,
                 "chained", None, "finish", "p.Foo", "p.Foo.finish",
                 "POSSIBLE", "chained_member", '["p.Foo.finish"]'),
                (2, "src/p/Caller.java", "p.Caller.run", "method", 7,
                 "method_ref", "Foo", "run", "p.Foo", "p.Foo.run",
                 "CONFIRMED", "method_reference", '["p.Foo.run"]'),
                (3, "src/p/Caller.java", "p.Caller.run", "method", 7,
                 "method_ref", "Foo", "run", "p.Foo", "p.Foo.run",
                 "CONFIRMED", "method_reference", '["p.Foo.run"]'),
                (4, "src/p/Caller.java", "p.Caller.run", "method", 20,
                 "bare", None, "missing", None, None, "UNRESOLVED",
                 "no_declaration", "[]"),
                (5, "src/p/Zed.java", "p.Zed.run", "method", 12,
                 "receiver", "foo", "run", "p.Foo", "p.Foo.run",
                 "CONFIRMED", "single_member", '["p.Foo.run"]'),
            ],
            actual,
        )
        self.assertEqual(2, sum(1 for row in actual if row[5] == "method_ref"))

    def test_writer_persists_one_row_per_distinct_target(self):
        from codewiki.index.callgraph import CallResolution
        from codewiki.index.calls import CallSite
        from codewiki.index.scan import FileRecord
        from codewiki.store import db

        record = FileRecord(
            path="src/p/Caller.java", language="java", lines=5,
            sha256="caller-sha", is_test=False, is_generated=False, package="p",
        )
        resolution = CallResolution(
            CallSite(
                record.path, "p.Caller.run", "method", 3,
                "receiver", "foo", "run",
            ),
            "p.Foo", ("z.Foo.run", "a.Foo.run"), "POSSIBLE", "overloaded",
        )

        with tempfile.TemporaryDirectory(prefix="codewiki-call-failure-") as out:
            db_path = os.path.join(out, "index.sqlite3")
            db.write_index(
                db_path,
                "/repo",
                [record],
                [],
                calls=[resolution],
            )
            connection = db.open_index(db_path)
            try:
                rows = connection.execute(
                    "SELECT caller_fqn, caller_kind, line, form, receiver, name, "
                    "owner_fqn, target_fqn, confidence, reason, candidates "
                    "FROM calls ORDER BY call_id"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                (
                    "p.Caller.run", "method", 3, "receiver", "foo", "run",
                    "p.Foo", "a.Foo.run", "POSSIBLE", "overloaded",
                    '["a.Foo.run","z.Foo.run"]',
                ),
                (
                    "p.Caller.run", "method", 3, "receiver", "foo", "run",
                    "p.Foo", "z.Foo.run", "POSSIBLE", "overloaded",
                    '["a.Foo.run","z.Foo.run"]',
                )
            ],
            rows,
        )


if __name__ == "__main__":
    unittest.main()
