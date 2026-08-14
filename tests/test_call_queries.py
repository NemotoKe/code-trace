from __future__ import annotations

import os
import json
import sqlite3
import tempfile
import unittest


class CallQueryTests(unittest.TestCase):
    def setUp(self):
        from codewiki.store import db

        self.directory = tempfile.TemporaryDirectory(prefix="codewiki-call-query-")
        self.db_path = os.path.join(self.directory.name, "index.sqlite3")
        connection = sqlite3.connect(self.db_path)
        try:
            db.initialize(connection, repo_root="/repo")
        finally:
            connection.close()

    def tearDown(self):
        self.directory.cleanup()

    def _file(self, path, package="p"):
        connection = sqlite3.connect(self.db_path)
        try:
            cursor = connection.execute(
                "INSERT INTO files(path, language, package, lines, sha256, "
                "is_test, is_generated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (path, "java", package, 20, path, 0, 0),
            )
            connection.commit()
            return cursor.lastrowid
        finally:
            connection.close()

    def _symbol(self, file_id, name, fqn, owner_fqn=None, kind="method"):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO symbols(file_id, name, kind, fqn, owner_fqn, "
                "params, param_count, signature, line, end_line, confidence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id, name, kind, fqn, owner_fqn, None, None,
                    name + "()", 1, 1, "CERTAIN",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _call(self, file_id, caller_fqn, line, form, receiver, name,
              owner_fqn=None, target_fqn=None, confidence="UNRESOLVED",
              reason="no_declaration", candidates=()):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO calls(file_id, caller_fqn, caller_kind, line, form, "
                "receiver, name, owner_fqn, target_fqn, confidence, reason, "
                "candidates) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id, caller_fqn, "method", line, form, receiver, name,
                    owner_fqn, target_fqn, confidence, reason,
                    json.dumps(list(candidates)),
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def _supertype(self, file_id, owner_fqn, target_fqn, line=2):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "INSERT INTO supertypes(file_id, owner_fqn, line, relation, raw, "
                "name, target_fqn, rule, outcome, candidates) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_id, owner_fqn, line, "extends", target_fqn,
                    target_fqn.rsplit(".", 1)[-1], target_fqn, 1,
                    "resolved", "[]",
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def test_callees_includes_unresolved_rows_in_source_order(self):
        file_id = self._file("src/p/Service.java")
        self._symbol(file_id, "run", "p.Service.run", "p.Service")
        self._call(
            file_id, "p.Service.run", 14, "receiver", "dao", "save",
            owner_fqn="p.Dao", target_fqn="p.Dao.save", confidence="CONFIRMED",
            reason="single_member", candidates=("p.Dao.save",),
        )
        self._call(
            file_id, "p.Service.run", 8, "receiver", "thing", "store",
        )
        self._call(
            file_id, "p.Service.run", 14, "bare", None, "close",
            reason="form_not_resolved",
        )

        from codewiki.query.calls import CalleeResult, callees

        result = callees(self.db_path, "p.Service.run")

        self.assertEqual(
            [
                CalleeResult(
                    8, "receiver", "thing", "store", None,
                    "UNRESOLVED", "no_declaration",
                ),
                CalleeResult(
                    14, "bare", None, "close", None,
                    "UNRESOLVED", "form_not_resolved",
                ),
                CalleeResult(
                    14, "receiver", "dao", "save", "p.Dao.save",
                    "CONFIRMED", "single_member",
                ),
            ],
            result,
        )
        self.assertEqual(
            {
                "line": 8,
                "form": "receiver",
                "receiver": "thing",
                "name": "store",
                "target_fqn": None,
                "confidence": "UNRESOLVED",
                "reason": "no_declaration",
            },
            result[0].as_dict(),
        )

    def test_callers_returns_direct_rows_in_deterministic_order(self):
        target_file_id = self._file("src/p/Service.java")
        self._symbol(
            target_file_id, "run", "p.Service.run", "p.Service"
        )
        first_file_id = self._file("src/a/Caller.java", package="a")
        self._symbol(first_file_id, "invoke", "a.Caller.invoke", "a.Caller")
        self._call(
            first_file_id, "a.Caller.invoke", 12, "receiver", "service", "run",
            owner_fqn="p.Service", target_fqn="p.Service.run",
            confidence="CONFIRMED", reason="single_member",
        )
        second_file_id = self._file("src/z/Caller.java", package="z")
        self._symbol(second_file_id, "invoke", "z.Caller.invoke", "z.Caller")
        self._call(
            second_file_id, "z.Caller.invoke", 4, "bare", None, "run",
            target_fqn="p.Service.run", confidence="POSSIBLE",
            reason="form_not_resolved",
        )

        from codewiki.query.calls import CallerResult, callers

        result = callers(self.db_path, "p.Service.run")

        self.assertEqual(
            [
                CallerResult(
                    "a.Caller.invoke", "src/a/Caller.java", 12,
                    "receiver", "service", "run", "CONFIRMED",
                    "single_member", None,
                ),
                CallerResult(
                    "z.Caller.invoke", "src/z/Caller.java", 4,
                    "bare", None, "run", "POSSIBLE",
                    "form_not_resolved", None,
                ),
            ],
            result,
        )
        self.assertEqual(
            {
                "caller_fqn": "a.Caller.invoke",
                "path": "src/a/Caller.java",
                "line": 12,
                "form": "receiver",
                "receiver": "service",
                "name": "run",
                "confidence": "CONFIRMED",
                "reason": "single_member",
                "via_fqn": None,
            },
            result[0].as_dict(),
        )

    def test_callers_includes_callers_of_same_named_overridden_ancestor(self):
        child_file_id = self._file("src/p/Child.java")
        self._symbol(child_file_id, "Child", "p.Child", kind="class")
        self._symbol(child_file_id, "run", "p.Child.run", "p.Child")
        parent_file_id = self._file("src/p/Parent.java")
        self._symbol(parent_file_id, "Parent", "p.Parent", kind="interface")
        self._symbol(parent_file_id, "run", "p.Parent.run", "p.Parent")
        self._supertype(child_file_id, "p.Child", "p.Parent")

        direct_file_id = self._file("src/z/Direct.java", package="z")
        self._symbol(direct_file_id, "invoke", "z.Direct.invoke", "z.Direct")
        self._call(
            direct_file_id, "z.Direct.invoke", 40, "receiver", "child", "run",
            owner_fqn="p.Child", target_fqn="p.Child.run",
            confidence="CONFIRMED", reason="single_member",
        )
        expanded_file_id = self._file("src/a/InterfaceUser.java", package="a")
        self._symbol(
            expanded_file_id, "invoke", "a.InterfaceUser.invoke", "a.InterfaceUser"
        )
        self._call(
            expanded_file_id, "a.InterfaceUser.invoke", 3, "receiver", "parent", "run",
            owner_fqn="p.Parent", target_fqn="p.Parent.run",
            confidence="CONFIRMED", reason="single_member",
        )

        from codewiki.query.calls import CallerResult, callers

        result = callers(self.db_path, "p.Child.run")

        self.assertEqual(
            [
                CallerResult(
                    "z.Direct.invoke", "src/z/Direct.java", 40,
                    "receiver", "child", "run", "CONFIRMED",
                    "single_member", None,
                ),
                CallerResult(
                    "a.InterfaceUser.invoke", "src/a/InterfaceUser.java", 3,
                    "receiver", "parent", "run", "CONFIRMED",
                    "single_member", "p.Parent.run",
                ),
            ],
            result,
        )

    def test_callers_finds_inherited_callers_when_direct_callers_are_empty(self):
        leaf_file_id = self._file("src/graph/Leaf.java", package="graph")
        self._symbol(leaf_file_id, "Leaf", "graph.Leaf", kind="class")
        self._symbol(leaf_file_id, "run", "graph.Leaf.run", "graph.Leaf")
        mid_file_id = self._file("src/graph/Mid.java", package="graph")
        self._symbol(mid_file_id, "Mid", "graph.Mid", kind="interface")
        self._symbol(mid_file_id, "run", "graph.Mid.run", "graph.Mid")
        base_file_id = self._file("src/graph/Base.java", package="graph")
        self._symbol(base_file_id, "Base", "graph.Base", kind="interface")
        self._symbol(base_file_id, "run", "graph.Base.run", "graph.Base")
        self._supertype(leaf_file_id, "graph.Leaf", "graph.Mid")
        self._supertype(mid_file_id, "graph.Mid", "graph.Base")

        caller_file_id = self._file("src/graph/Client.java", package="graph")
        self._symbol(caller_file_id, "invoke", "graph.Client.invoke", "graph.Client")
        self._call(
            caller_file_id, "graph.Client.invoke", 9, "receiver", "contract", "run",
            owner_fqn="graph.Base", target_fqn="graph.Base.run",
            confidence="CONFIRMED", reason="single_member",
        )

        from codewiki.query.calls import CallerResult, callers

        result = callers(self.db_path, "graph.Leaf.run")

        self.assertEqual(
            [
                CallerResult(
                    "graph.Client.invoke", "src/graph/Client.java", 9,
                    "receiver", "contract", "run", "CONFIRMED",
                    "single_member", "graph.Base.run",
                ),
            ],
            result,
        )

    def test_callers_cycle_in_supertype_rows_terminates(self):
        owner_file_id = self._file("src/cycle/A.java", package="cycle")
        self._symbol(owner_file_id, "A", "cycle.A", kind="class")
        self._symbol(owner_file_id, "run", "cycle.A.run", "cycle.A")
        b_file_id = self._file("src/cycle/B.java", package="cycle")
        self._symbol(b_file_id, "B", "cycle.B", kind="class")
        self._symbol(b_file_id, "run", "cycle.B.run", "cycle.B")
        c_file_id = self._file("src/cycle/C.java", package="cycle")
        self._symbol(c_file_id, "C", "cycle.C", kind="class")
        self._symbol(c_file_id, "run", "cycle.C.run", "cycle.C")
        self._supertype(owner_file_id, "cycle.A", "cycle.B", line=2)
        self._supertype(b_file_id, "cycle.B", "cycle.C", line=3)
        self._supertype(c_file_id, "cycle.C", "cycle.B", line=4)

        b_caller_file_id = self._file("src/cycle/BCaller.java", package="cycle")
        self._symbol(
            b_caller_file_id, "invoke", "cycle.BCaller.invoke", "cycle.BCaller"
        )
        self._call(
            b_caller_file_id, "cycle.BCaller.invoke", 5, "receiver", "value", "run",
            owner_fqn="cycle.B", target_fqn="cycle.B.run",
            confidence="CONFIRMED", reason="single_member",
        )
        c_caller_file_id = self._file("src/cycle/CCaller.java", package="cycle")
        self._symbol(
            c_caller_file_id, "invoke", "cycle.CCaller.invoke", "cycle.CCaller"
        )
        self._call(
            c_caller_file_id, "cycle.CCaller.invoke", 6, "receiver", "value", "run",
            owner_fqn="cycle.C", target_fqn="cycle.C.run",
            confidence="CONFIRMED", reason="single_member",
        )

        from codewiki.query.calls import CallerResult, callers

        result = callers(self.db_path, "cycle.A.run")

        self.assertEqual(
            [
                CallerResult(
                    "cycle.BCaller.invoke", "src/cycle/BCaller.java", 5,
                    "receiver", "value", "run", "CONFIRMED",
                    "single_member", "cycle.B.run",
                ),
                CallerResult(
                    "cycle.CCaller.invoke", "src/cycle/CCaller.java", 6,
                    "receiver", "value", "run", "CONFIRMED",
                    "single_member", "cycle.C.run",
                ),
            ],
            result,
        )

    def test_unknown_fqn_is_an_empty_result_for_both_directions(self):
        from codewiki.query.calls import callees, callers

        self.assertEqual([], callees(self.db_path, "com.example.NoSuchType.noSuchMethod"))
        self.assertEqual([], callers(self.db_path, "com.example.NoSuchType.noSuchMethod"))

    def test_missing_index_raises_the_query_error(self):
        from codewiki.query.calls import TypeQueryError, callees, callers

        missing = os.path.join(self.directory.name, "missing.sqlite3")
        with self.assertRaises(TypeQueryError):
            callees(missing, "p.Service.run")
        with self.assertRaises(TypeQueryError):
            callers(missing, "p.Service.run")


if __name__ == "__main__":
    unittest.main()
