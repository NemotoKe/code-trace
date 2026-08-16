from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WARNING = "警告: この出力は識別子を含む。実ソース環境の外へ持ち出さないこと。"


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


SAMPLE_SOURCE = (
    "package p;\n"
    "public class Repo {\n"
    "    public static void main(String[] args) { run(); }\n"
    "    static void run() {\n"
    "        exec(\"SELECT ID FROM T1\");\n"
    "        exec(\"SELECT ID FROM T2\");\n"
    "        exec(\"SELECT ID FROM T3\");\n"
    "        exec(\"SELECT ID FROM T4\");\n"
    "        exec(\"SELECT ID FROM T5\");\n"
    "        exec(\"SELECT ID FROM T6\");\n"
    "        exec(\"SELECT ID FROM T7\");\n"
    "        exec(\"SELECT ID FROM T8\");\n"
    "        exec(\"SELECT ID FROM T9\");\n"
    "    }\n"
    "    static void exec(String sql) {}\n"
    "}\n"
)

NINE_SAMPLE_SOURCE = (
    "package p;\n"
    "public class Nine {\n"
    "    void m1() { run(\"SELECT C1 FROM T1\"); }\n"
    "    void m2() { run(\"SELECT C1 FROM T2\"); }\n"
    "    void m3() { run(\"SELECT C1 FROM T3\"); }\n"
    "    void m4() { run(\"SELECT C1 FROM T4\"); }\n"
    "    void m5() { run(\"SELECT C1 FROM T5\"); }\n"
    "    void m6() { run(\"SELECT C1 FROM T6\"); }\n"
    "    void m7() { run(\"SELECT C1 FROM T7\"); }\n"
    "    void m8() { run(\"SELECT C1 FROM T8\"); }\n"
    "    void m9() { run(\"SELECT C1 FROM T9\"); }\n"
    "    void run(String sql) {}\n"
    "}\n"
)


class SampleCliIntegrationTests(unittest.TestCase):
    def _index_source(self, source, relative_path):
        root = tempfile.TemporaryDirectory(prefix="codewiki-sample-repo-")
        out = tempfile.TemporaryDirectory(prefix="codewiki-sample-out-")
        write_file(root.name, relative_path, source)
        indexed = run_cli("index", root.name, "--out", out.name, "--quiet")
        self.assertEqual(0, indexed.returncode, indexed.stderr)
        return root, out

    def _index_sample(self):
        return self._index_source(SAMPLE_SOURCE, "src/p/Repo.java")

    def test_sql_sample_uses_primary_key_interval(self):
        root, out = self._index_source(NINE_SAMPLE_SOURCE, "src/p/Nine.java")
        try:
            queried = run_cli(
                "sample", "sql", "--out", out.name, "-n", "3", "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)

            self.assertEqual(3, payload["count"])
            self.assertEqual(
                ["T3", "T6", "T9"],
                [item["table_name"] for item in payload["results"]],
            )
            self.assertEqual(
                ["p.Nine.m3", "p.Nine.m6", "p.Nine.m9"],
                [item["method_fqn"] for item in payload["results"]],
            )
        finally:
            root.cleanup()
            out.cleanup()

    def test_sql_sample_is_deterministic_and_returns_three_rows(self):
        root, out = self._index_sample()
        try:
            database = sqlite3.connect(os.path.join(out.name, "index.sqlite3"))
            try:
                self.assertEqual(
                    9,
                    database.execute("SELECT COUNT(*) FROM sql_accesses").fetchone()[0],
                )
            finally:
                database.close()

            first = run_cli("sample", "sql", "--out", out.name, "-n", "3", "--json")
            second = run_cli("sample", "sql", "--out", out.name, "-n", "3", "--json")
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(first.stdout, second.stdout)

            payload = json.loads(first.stdout)
            self.assertEqual({"kind", "n", "count", "exportable", "results"}, set(payload))
            self.assertEqual("sql", payload["kind"])
            self.assertEqual(3, payload["n"])
            self.assertEqual(3, payload["count"])
            self.assertFalse(payload["exportable"])
            self.assertEqual(3, len(payload["results"]))
            for result in payload["results"]:
                self.assertEqual(
                    {"path", "line", "method_fqn", "verb", "access", "table_name"},
                    set(result),
                )
                self.assertEqual("src/p/Repo.java", result["path"])
                self.assertIsInstance(result["line"], int)
        finally:
            root.cleanup()
            out.cleanup()

    def test_each_kind_has_non_exportable_json_and_human_warning(self):
        root, out = self._index_sample()
        try:
            entrypoints = run_cli("sample", "entrypoints", "--out", out.name, "--json")
            self.assertEqual(0, entrypoints.returncode, entrypoints.stderr)
            entrypoint_payload = json.loads(entrypoints.stdout)
            self.assertEqual("entrypoints", entrypoint_payload["kind"])
            self.assertFalse(entrypoint_payload["exportable"])
            self.assertGreaterEqual(entrypoint_payload["count"], 1)
            self.assertEqual(
                {"path", "line", "method_fqn", "kind", "reason"},
                set(entrypoint_payload["results"][0]),
            )

            calls = run_cli("sample", "calls", "--out", out.name, "--json")
            self.assertEqual(0, calls.returncode, calls.stderr)
            call_payload = json.loads(calls.stdout)
            self.assertEqual("calls", call_payload["kind"])
            self.assertFalse(call_payload["exportable"])
            self.assertGreaterEqual(call_payload["count"], 1)
            self.assertEqual(
                {"path", "line", "caller_fqn", "target_fqn", "confidence", "reason"},
                set(call_payload["results"][0]),
            )
            self.assertTrue(all(item["target_fqn"] is not None for item in call_payload["results"]))

            human = run_cli("sample", "sql", "--out", out.name, "-n", "1")
            self.assertEqual(0, human.returncode, human.stderr)
            lines = human.stdout.splitlines()
            self.assertEqual(WARNING, lines[0])
            self.assertTrue(lines[1].startswith("src/p/Repo.java:"))
        finally:
            root.cleanup()
            out.cleanup()

    def test_calls_sample_excludes_unresolved_targets(self):
        root = tempfile.TemporaryDirectory(prefix="codewiki-sample-calls-repo-")
        out = tempfile.TemporaryDirectory(prefix="codewiki-sample-calls-out-")
        try:
            write_file(
                root.name,
                "src/p/Dao.java",
                "package p;\n"
                "class Dao { void save() {} }\n",
            )
            write_file(
                root.name,
                "src/p/Caller.java",
                "package p;\n"
                "class Caller {\n"
                "    void run(Dao dao) {\n"
                "        dao.save();\n"
                "        unknown.missing();\n"
                "        make().finish();\n"
                "        new MissingType();\n"
                "    }\n"
                "}\n",
            )
            indexed = run_cli("index", root.name, "--out", out.name, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("sample", "calls", "--out", out.name, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)

            self.assertGreater(payload["count"], 0)
            self.assertTrue(
                all(
                    item["target_fqn"] not in (None, "")
                    for item in payload["results"]
                )
            )
        finally:
            root.cleanup()
            out.cleanup()

    def test_unknown_kind_is_an_argparse_error(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-sample-invalid-out-") as out:
            result = run_cli("sample", "symbols", "--out", out)
            self.assertEqual(2, result.returncode)
            self.assertEqual("", result.stdout)
            self.assertIn("invalid choice", result.stderr)

    def test_missing_and_wrong_schema_fail_with_rerun_message(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-sample-missing-out-") as out:
            missing = run_cli("sample", "sql", "--out", out, "--json")
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)
            self.assertIn("rerun index", missing.stderr.lower())

        root, out = self._index_sample()
        try:
            database = sqlite3.connect(os.path.join(out.name, "index.sqlite3"))
            try:
                database.execute(
                    "UPDATE meta SET value = '999' WHERE key = 'schema_version'"
                )
                database.commit()
            finally:
                database.close()

            wrong = run_cli("sample", "calls", "--out", out.name, "--json")
            self.assertEqual(2, wrong.returncode)
            self.assertEqual("", wrong.stdout)
            self.assertIn("rerun index", wrong.stderr.lower())
        finally:
            root.cleanup()
            out.cleanup()


if __name__ == "__main__":
    unittest.main()
