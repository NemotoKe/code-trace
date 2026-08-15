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


if __name__ == "__main__":
    unittest.main()
