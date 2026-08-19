from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest


class TraceQueryTests(unittest.TestCase):
    def setUp(self):
        from codewiki.store import db

        self.directory = tempfile.TemporaryDirectory(prefix="codewiki-trace-query-")
        self.db_path = os.path.join(self.directory.name, "index.sqlite3")
        connection = sqlite3.connect(self.db_path)
        try:
            db.initialize(connection, repo_root="/repo")
        finally:
            connection.close()
        self.file_ids = {}

    def tearDown(self):
        self.directory.cleanup()

    def _file(self, path):
        connection = sqlite3.connect(self.db_path)
        try:
            cursor = connection.execute(
                "INSERT INTO files(path, language, package, lines, sha256, "
                "is_test, is_generated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (path, "java", "p", 40, path, 0, 0),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def _method(self, fqn, path):
        file_id = self._file(path)
        owner_fqn, name = fqn.rsplit(".", 1)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO symbols(file_id, name, kind, fqn, owner_fqn, "
                "params, param_count, signature, line, end_line, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id, name, "method", fqn, owner_fqn, None, None,
                    name + "()", 1, 1, "CERTAIN",
                ),
            )
            connection.commit()
        finally:
            connection.close()
        self.file_ids[fqn] = file_id

    def _call(self, caller_fqn, target_fqn, line, confidence="CONFIRMED"):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO calls(file_id, caller_fqn, caller_kind, line, form, "
                "receiver, name, owner_fqn, target_fqn, confidence, reason, "
                "candidates) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.file_ids[caller_fqn], caller_fqn, "method", line,
                    "receiver", "value", target_fqn.rsplit(".", 1)[-1],
                    target_fqn.rsplit(".", 1)[0], target_fqn, confidence,
                    "single_member", json.dumps([target_fqn]),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _entrypoints(self, rows):
        file_id = self._file("src/entrypoints/Fixture.java")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.executemany(
                "INSERT INTO entrypoints(file_id, method_fqn, owner_fqn, kind, "
                "reason, line) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    (
                        file_id,
                        method_fqn,
                        method_fqn.rsplit(".", 1)[0],
                        kind,
                        "test:%s" % kind,
                        1,
                    )
                    for method_fqn, kind in rows
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def test_chain_and_reconvergence_have_shortest_parents(self):
        self._method("p.Repo.repo", "src/p/Repo.java")
        self._method("p.Service.service", "src/p/Service.java")
        self._method("p.Entry.entry", "src/p/Entry.java")
        self._method("p.Other.other", "src/p/Other.java")
        self._call("p.Service.service", "p.Repo.repo", 11)
        self._call("p.Entry.entry", "p.Service.service", 21)
        self._call("p.Other.other", "p.Service.service", 31, "POSSIBLE")

        from codewiki.query.trace import TraceNode, callers_upward, path_to

        nodes, truncated = callers_upward(self.db_path, "p.Repo.repo")

        self.assertFalse(truncated)
        self.assertEqual(
            [
                TraceNode(
                    "p.Service.service", 1, "src/p/Service.java", 11,
                    "CONFIRMED", None, "p.Repo.repo",
                ),
                TraceNode(
                    "p.Entry.entry", 2, "src/p/Entry.java", 21,
                    "CONFIRMED", None, "p.Service.service",
                ),
                TraceNode(
                    "p.Other.other", 2, "src/p/Other.java", 31,
                    "POSSIBLE", None, "p.Service.service",
                ),
            ],
            nodes,
        )
        self.assertEqual(
            [nodes[1], nodes[0]], path_to(nodes, "p.Entry.entry")
        )

    def test_cycle_records_each_reachable_method_once(self):
        self._method("p.A.a", "src/p/A.java")
        self._method("p.B.b", "src/p/B.java")
        self._call("p.B.b", "p.A.a", 10)
        self._call("p.A.a", "p.B.b", 20)

        from codewiki.query.trace import callers_upward

        nodes, truncated = callers_upward(self.db_path, "p.A.a")

        self.assertFalse(truncated)
        self.assertEqual(["p.B.b"], [node.fqn for node in nodes])
        self.assertEqual([1], [node.depth for node in nodes])

    def test_max_depth_only_returns_direct_callers_and_marks_truncated(self):
        self._method("p.Repo.repo", "src/p/Repo.java")
        self._method("p.Service.service", "src/p/Service.java")
        self._method("p.Entry.entry", "src/p/Entry.java")
        self._call("p.Service.service", "p.Repo.repo", 11)
        self._call("p.Entry.entry", "p.Service.service", 21)

        from codewiki.query.trace import callers_upward

        nodes, truncated = callers_upward(
            self.db_path, "p.Repo.repo", max_depth=1
        )

        self.assertTrue(truncated)
        self.assertEqual(["p.Service.service"], [node.fqn for node in nodes])

    def test_max_depth_at_end_of_chain_does_not_mark_truncated(self):
        self._method("p.Repo.repo", "src/p/Repo.java")
        self._method("p.Service.service", "src/p/Service.java")
        self._method("p.Entry.entry", "src/p/Entry.java")
        self._call("p.Service.service", "p.Repo.repo", 11)
        self._call("p.Entry.entry", "p.Service.service", 21)

        from codewiki.query.trace import callers_upward

        nodes, truncated = callers_upward(
            self.db_path, "p.Repo.repo", max_depth=2
        )

        self.assertFalse(truncated)
        self.assertEqual(
            ["p.Service.service", "p.Entry.entry"],
            [node.fqn for node in nodes],
        )

    def test_max_depth_past_end_of_chain_marks_truncated(self):
        self._method("p.Repo.repo", "src/p/Repo.java")
        self._method("p.Service.service", "src/p/Service.java")
        self._method("p.Entry.entry", "src/p/Entry.java")
        self._method("p.Controller.controller", "src/p/Controller.java")
        self._call("p.Service.service", "p.Repo.repo", 11)
        self._call("p.Entry.entry", "p.Service.service", 21)
        self._call("p.Controller.controller", "p.Entry.entry", 31)

        from codewiki.query.trace import callers_upward

        nodes, truncated = callers_upward(
            self.db_path, "p.Repo.repo", max_depth=2
        )

        self.assertTrue(truncated)
        self.assertEqual(
            ["p.Service.service", "p.Entry.entry"],
            [node.fqn for node in nodes],
        )

    def test_boundary_node_with_only_visited_caller_does_not_truncate(self):
        self._method("p.Repo.repo", "src/p/Repo.java")
        self._method("p.Short.short", "src/p/Short.java")
        self._method("p.Root.root", "src/p/Root.java")
        self._method("p.Boundary.boundary", "src/p/Boundary.java")
        self._call("p.Short.short", "p.Repo.repo", 11)
        self._call("p.Root.root", "p.Repo.repo", 12)
        self._call("p.Boundary.boundary", "p.Root.root", 21)
        self._call("p.Short.short", "p.Boundary.boundary", 31)

        from codewiki.query.trace import callers_upward

        nodes, truncated = callers_upward(
            self.db_path, "p.Repo.repo", max_depth=2
        )

        self.assertFalse(truncated)
        self.assertEqual(
            ["p.Root.root", "p.Short.short", "p.Boundary.boundary"],
            [node.fqn for node in nodes],
        )

    def test_boundary_node_with_no_callers_does_not_truncate(self):
        self._method("p.Repo.repo", "src/p/Repo.java")
        self._method("p.Service.service", "src/p/Service.java")
        self._method("p.Entry.entry", "src/p/Entry.java")
        self._call("p.Service.service", "p.Repo.repo", 11)
        self._call("p.Entry.entry", "p.Service.service", 21)

        from codewiki.query.trace import callers_upward

        nodes, truncated = callers_upward(
            self.db_path, "p.Repo.repo", max_depth=2
        )

        self.assertFalse(truncated)
        self.assertEqual(
            ["p.Service.service", "p.Entry.entry"],
            [node.fqn for node in nodes],
        )

    def test_max_nodes_stops_as_soon_as_the_limit_is_recorded(self):
        self._method("p.Repo.repo", "src/p/Repo.java")
        self._method("p.Service.service", "src/p/Service.java")
        self._call("p.Service.service", "p.Repo.repo", 11)

        from codewiki.query.trace import callers_upward

        nodes, truncated = callers_upward(
            self.db_path, "p.Repo.repo", max_nodes=1
        )

        self.assertTrue(truncated)
        self.assertEqual(["p.Service.service"], [node.fqn for node in nodes])

    def test_unknown_fqn_returns_empty_non_truncated_result(self):
        from codewiki.query.trace import callers_upward, path_to

        nodes, truncated = callers_upward(self.db_path, "p.Missing.missing")

        self.assertEqual([], nodes)
        self.assertFalse(truncated)
        self.assertEqual([], path_to(nodes, "p.Missing.missing"))

    def test_entrypoints_among_returns_sorted_kinds_for_requested_fqns(self):
        self._entrypoints(
            [
                ("p.Servlet.doPost", "servlet"),
                ("p.Servlet.doPost", "jaxrs"),
                ("p.Servlet.doPost", "servlet"),
                ("p.Batch.main", "main"),
            ]
        )

        from codewiki.query.trace import entrypoints_among

        self.assertEqual(
            {
                "p.Batch.main": ("main",),
                "p.Servlet.doPost": ("jaxrs", "servlet"),
            },
            entrypoints_among(
                self.db_path,
                [
                    "p.Servlet.doPost",
                    "p.Batch.main",
                    "p.Servlet.doPost",
                    "p.Missing.missing",
                ],
            ),
        )

    def test_entrypoints_among_chunks_large_requests_and_binds_fqns(self):
        injected = "p.Bad'); DROP TABLE entrypoints; --"
        fqns = ["p.Type%d.run" % index for index in range(1001)] + [injected]
        self._entrypoints([(fqn, "main") for fqn in fqns])

        from codewiki.query.trace import entrypoints_among

        result = entrypoints_among(self.db_path, list(reversed(fqns)) + [injected])

        self.assertEqual(
            {fqn: ("main",) for fqn in fqns},
            result,
        )

    def test_entrypoints_among_empty_input_does_not_require_table(self):
        from codewiki.query.trace import entrypoints_among

        self.assertEqual({}, entrypoints_among(self.db_path, []))

    def test_entrypoints_among_wraps_missing_or_uninitialized_database_errors(self):
        from codewiki.query.trace import TypeQueryError, entrypoints_among

        uninitialized_path = os.path.join(
            self.directory.name, "uninitialized.sqlite3"
        )
        sqlite3.connect(uninitialized_path).close()

        missing_path = os.path.join(self.directory.name, "missing.sqlite3")
        for path in (uninitialized_path, missing_path):
            with self.subTest(path=path):
                with self.assertRaises(TypeQueryError) as database_error:
                    entrypoints_among(path, ["p.Missing.missing"])
                self.assertEqual(
                    "index database missing or stale; rerun index",
                    str(database_error.exception),
                )


if __name__ == "__main__":
    unittest.main()
