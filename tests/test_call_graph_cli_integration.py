from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "codewiki"] + list(args),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_file(root, relative_path, contents):
    path = os.path.join(root, relative_path)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(contents)


def call_rows(out):
    connection = sqlite3.connect(os.path.join(out, "index.sqlite3"))
    try:
        rows = connection.execute(
            "SELECT f.path, c.caller_fqn, c.line, c.form, c.receiver, "
            "c.name, c.owner_fqn, c.target_fqn, c.confidence, c.reason, "
            "c.candidates "
            "FROM calls AS c JOIN files AS f USING(file_id) "
            "ORDER BY c.call_id"
        ).fetchall()
        return [row[:-1] + (json.loads(row[-1]),) for row in rows]
    finally:
        connection.close()


class CallGraphCliIntegrationTests(unittest.TestCase):
    def index_repository(self, root, out):
        indexed = run_cli(
            "index", root, "--out", out, "--jobs", "1", "--quiet"
        )
        self.assertEqual(
            0,
            indexed.returncode,
            "index stdout:\n%s\nindex stderr:\n%s"
            % (indexed.stdout, indexed.stderr),
        )
        self.assertTrue(
            os.path.isfile(os.path.join(out, "index.sqlite3")),
            indexed.stdout,
        )
        return indexed

    def test_interface_typed_call_reaches_implementation_only_via_ancestor(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-callers-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-callers-out-") as out:
            write_file(
                root,
                "src/api/Contract.java",
                "package api;\n"
                "public interface Contract {\n"
                "    void run();\n"
                "}\n",
            )
            write_file(
                root,
                "src/impl/Worker.java",
                "package impl;\n"
                "import api.Contract;\n"
                "public class Worker implements Contract {\n"
                "    public void run() {}\n"
                "}\n",
            )
            write_file(
                root,
                "src/app/Caller.java",
                "package app;\n"
                "import api.Contract;\n"
                "public class Caller {\n"
                "    void invoke(Contract contract) {\n"
                "        contract.run();\n"
                "    }\n"
                "}\n",
            )
            self.index_repository(root, out)

            rows = call_rows(out)
            self.assertEqual(
                [
                    (
                        "src/app/Caller.java", "app.Caller.invoke", 5,
                        "receiver", "contract", "run", "api.Contract",
                        "api.Contract.run", "CONFIRMED", "single_member",
                        ["api.Contract.run"],
                    ),
                ],
                rows,
            )

            callers = run_cli(
                "callers", "impl.Worker.run", "--out", out, "--json"
            )
            self.assertEqual(0, callers.returncode, callers.stderr)
            payload = json.loads(callers.stdout)
            self.assertEqual(1, payload["count"])
            self.assertEqual(0, payload["direct"])
            self.assertEqual(1, payload["expanded"])
            self.assertEqual(
                {
                    "caller_fqn": "app.Caller.invoke",
                    "path": "src/app/Caller.java",
                    "line": 5,
                    "form": "receiver",
                    "receiver": "contract",
                    "name": "run",
                    "confidence": "CONFIRMED",
                    "reason": "single_member",
                    "via_fqn": "api.Contract.run",
                },
                payload["results"][0],
            )

            direct = run_cli(
                "callers", "impl.Worker.run", "--out", out,
                "--direct", "--json",
            )
            self.assertEqual(0, direct.returncode, direct.stderr)
            direct_payload = json.loads(direct.stdout)
            self.assertEqual(0, direct_payload["count"])
            self.assertEqual([], direct_payload["results"])

    def test_inherited_field_from_base_file_resolves_in_callees(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-field-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-field-out-") as out:
            write_file(
                root,
                "src/base/Base.java",
                "package base;\n"
                "import dep.Dao;\n"
                "public class Base {\n"
                "    protected Dao dao;\n"
                "}\n",
            )
            write_file(
                root,
                "src/sub/Child.java",
                "package sub;\n"
                "import base.Base;\n"
                "public class Child extends Base {\n"
                "    void run() {\n"
                "        dao.save();\n"
                "    }\n"
                "}\n",
            )
            write_file(
                root,
                "src/dep/Dao.java",
                "package dep;\n"
                "public class Dao {\n"
                "    public void save() {}\n"
                "}\n",
            )
            self.index_repository(root, out)

            rows = call_rows(out)
            self.assertEqual(
                [
                    (
                        "src/sub/Child.java", "sub.Child.run", 5,
                        "receiver", "dao", "save", "dep.Dao", "dep.Dao.save",
                        "CONFIRMED", "inherited_field_single_member",
                        ["dep.Dao.save"],
                    ),
                ],
                rows,
            )
            connection = sqlite3.connect(os.path.join(out, "index.sqlite3"))
            try:
                self.assertEqual(
                    1,
                    connection.execute(
                        "SELECT COUNT(*) FROM symbols WHERE fqn = ?",
                        ("dep.Dao.save",),
                    ).fetchone()[0],
                )
            finally:
                connection.close()

            queried = run_cli("callees", "sub.Child.run", "--out", out)
            self.assertEqual(0, queried.returncode, queried.stderr)
            self.assertEqual(
                [
                    "5  receiver  dao.save           CONFIRMED  "
                    "inherited_field_single_member",
                    "1 callees (1 resolved, 0 unresolved)",
                ],
                queried.stdout.splitlines(),
            )

    def test_overloaded_member_is_possible_and_removed_by_confirmed_filter(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-overload-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-overload-out-") as out:
            write_file(
                root,
                "src/p/Dao.java",
                "package p;\n"
                "public class Dao {\n"
                "    void save() {}\n"
                "    void save(int value) {}\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/Caller.java",
                "package p;\n"
                "public class Caller {\n"
                "    void invoke(Dao dao) {\n"
                "        dao.save();\n"
                "    }\n"
                "}\n",
            )
            indexed = self.index_repository(root, out)
            self.assertIn("calls confidence POSSIBLE: 1", indexed.stdout)

            rows = call_rows(out)
            self.assertEqual(
                [
                    (
                        "src/p/Caller.java", "p.Caller.invoke", 4,
                        "receiver", "dao", "save", "p.Dao", "p.Dao.save",
                        "POSSIBLE", "overloaded", ["p.Dao.save"],
                    ),
                ],
                rows,
            )

            all_callees = run_cli(
                "callees", "p.Caller.invoke", "--out", out
            )
            self.assertEqual(0, all_callees.returncode, all_callees.stderr)
            self.assertEqual(
                [
                    "4  receiver  dao.save           POSSIBLE  overloaded",
                    "1 callees (1 resolved, 0 unresolved)",
                ],
                all_callees.stdout.splitlines(),
            )

            confirmed = run_cli(
                "callees", "p.Caller.invoke", "--out", out, "--confirmed"
            )
            self.assertEqual(0, confirmed.returncode, confirmed.stderr)
            self.assertEqual(
                ["0 callees (0 resolved, 0 unresolved)"],
                confirmed.stdout.splitlines(),
            )

    def test_unresolved_chained_call_is_persisted_and_returned_by_callees(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-chain-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-chain-out-") as out:
            write_file(
                root,
                "src/p/ChainCaller.java",
                "package p;\n"
                "public class ChainCaller {\n"
                "    void invoke() {\n"
                "        make().finish();\n"
                "    }\n"
                "}\n",
            )
            self.index_repository(root, out)

            rows = call_rows(out)
            self.assertEqual(2, len(rows))
            chained = [row for row in rows if row[3] == "chained"]
            self.assertEqual(
                [
                    (
                        "src/p/ChainCaller.java", "p.ChainCaller.invoke", 4,
                        "chained", "make", "finish", None, None,
                        "UNRESOLVED", "chained_receiver_unresolved", [],
                    ),
                ],
                chained,
            )

            queried = run_cli(
                "callees", "p.ChainCaller.invoke", "--out", out, "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(2, payload["count"])
            self.assertEqual(0, payload["resolved"])
            self.assertEqual(2, payload["unresolved"])
            self.assertIn(
                {
                    "line": 4,
                    "form": "chained",
                    "receiver": "make",
                    "name": "finish",
                    "target_fqn": None,
                    "confidence": "UNRESOLVED",
                    "reason": "chained_receiver_unresolved",
                },
                payload["results"],
            )

    def test_comments_and_text_blocks_produce_no_call_rows_or_callees(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-noise-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-noise-out-") as out:
            write_file(
                root,
                "src/p/Noise.java",
                "package p;\n"
                "public class Noise {\n"
                "    void invoke() {\n"
                "        // lineCommentGhost.call();\n"
                "        /* blockCommentGhost.call(); */\n"
                "        String sql = \"\"\"\n"
                "            textBlockGhost.call();\n"
                "            anotherTextBlockGhost.more();\n"
                "            \"\"\";\n"
                "        realCall();\n"
                "    }\n"
                "    void realCall() {}\n"
                "}\n",
            )
            self.index_repository(root, out)

            rows = call_rows(out)
            self.assertEqual(
                [
                    (
                        "src/p/Noise.java", "p.Noise.invoke", 10,
                        "bare", None, "realCall", "p.Noise", "p.Noise.realCall",
                        "CONFIRMED", "bare_single_member", ["p.Noise.realCall"],
                    ),
                ],
                rows,
            )

            queried = run_cli(
                "callees", "p.Noise.invoke", "--out", out, "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(1, payload["count"])
            self.assertEqual("realCall", payload["results"][0]["name"])
            self.assertTrue(
                {"lineCommentGhost", "blockCommentGhost", "textBlockGhost",
                 "anotherTextBlockGhost"}.isdisjoint(
                     {item["name"] for item in payload["results"]}
                 )
            )

    def test_queries_use_persisted_index_after_source_files_are_removed(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-boundary-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-boundary-out-") as out:
            write_file(
                root,
                "src/p/Dao.java",
                "package p;\n"
                "public class Dao {\n"
                "    public void save() {}\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/Caller.java",
                "package p;\n"
                "public class Caller {\n"
                "    void run(Dao dao) {\n"
                "        dao.save();\n"
                "    }\n"
                "}\n",
            )
            self.index_repository(root, out)
            os.remove(os.path.join(root, "src/p/Dao.java"))
            os.remove(os.path.join(root, "src/p/Caller.java"))

            callees = run_cli(
                "callees", "p.Caller.run", "--out", out, "--json"
            )
            self.assertEqual(0, callees.returncode, callees.stderr)
            callee_payload = json.loads(callees.stdout)
            self.assertEqual(1, callee_payload["count"])
            self.assertEqual("p.Dao.save", callee_payload["results"][0]["target_fqn"])

            callers = run_cli(
                "callers", "p.Dao.save", "--out", out, "--json"
            )
            self.assertEqual(0, callers.returncode, callers.stderr)
            caller_payload = json.loads(callers.stdout)
            self.assertEqual(1, caller_payload["count"])
            self.assertEqual(
                "p.Caller.run", caller_payload["results"][0]["caller_fqn"]
            )


if __name__ == "__main__":
    unittest.main()
