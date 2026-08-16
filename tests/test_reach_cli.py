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


class ReachCliIntegrationTests(unittest.TestCase):
    def test_reach_json_reports_sql_method_reach_metrics(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-reach-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-reach-out-") as out:
            write_file(
                root,
                "src/p/Web.java",
                "package p;\n"
                "import javax.servlet.http.HttpServlet;\n"
                "import javax.servlet.http.HttpServletRequest;\n"
                "import javax.servlet.http.HttpServletResponse;\n"
                "public class Web extends HttpServlet {\n"
                "    private Svc svc;\n"
                "    protected void doPost(HttpServletRequest q, HttpServletResponse r) { svc.touch(); }\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/Svc.java",
                "package p;\n"
                "public class Svc {\n"
                "    private Dao dao;\n"
                "    public void touch() { dao.write(); }\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/Dao.java",
                "package p;\n"
                "public class Dao {\n"
                "    public void write() { run(\"UPDATE T1 SET C1 = ?\"); }\n"
                "    public void orphan() { run(\"SELECT C1 FROM T2\"); }\n"
                "    void run(String sql) {}\n"
                "}\n",
            )

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("reach", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            self.assertEqual(1, len(queried.stdout.splitlines()))
            payload = json.loads(queried.stdout)

            self.assertEqual(
                {
                    "depth", "methods", "reached", "reach_rate", "no_caller",
                    "truncated", "depth_histogram", "entrypoint_kind_hits",
                },
                set(payload),
            )
            self.assertEqual(8, payload["depth"])
            self.assertEqual(2, payload["methods"])
            self.assertEqual(1, payload["reached"])
            self.assertEqual(0.5, payload["reach_rate"])
            self.assertEqual(1, payload["no_caller"])
            self.assertEqual(0, payload["truncated"])
            self.assertEqual(
                {str(depth): (1 if depth == 2 else 0) for depth in range(1, 9)},
                payload["depth_histogram"],
            )
            self.assertEqual(
                {"main": 0, "servlet": 1, "jaxrs": 0, "other": 0},
                payload["entrypoint_kind_hits"],
            )

    def test_reach_depth_and_truncation_with_near_and_far_entrypoints(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-reach-depth-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-reach-depth-out-") as out:
            write_file(
                root,
                "src/p/Near.java",
                "package p;\n"
                "import javax.servlet.http.HttpServlet;\n"
                "import javax.servlet.http.HttpServletRequest;\n"
                "import javax.servlet.http.HttpServletResponse;\n"
                "public class Near extends HttpServlet {\n"
                "    private Dao dao;\n"
                "    protected void doGet(HttpServletRequest q, HttpServletResponse r) { dao.write(); }\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/Far.java",
                "package p;\n"
                "public class Far {\n"
                "    private static Mid mid;\n"
                "    public static void main(String[] args) { mid.go(); }\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/Mid.java",
                "package p;\n"
                "public class Mid {\n"
                "    private Dao dao;\n"
                "    public void go() { dao.write(); }\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/Dao.java",
                "package p;\n"
                "public class Dao {\n"
                "    public void write() { run(\"UPDATE T1 SET C1 = ?\"); }\n"
                "    void run(String sql) {}\n"
                "}\n",
            )

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            default_query = run_cli("reach", "--out", out, "--json")
            self.assertEqual(0, default_query.returncode, default_query.stderr)
            self.assertEqual(
                {
                    "depth": 8,
                    "methods": 1,
                    "reached": 1,
                    "reach_rate": 1.0,
                    "no_caller": 0,
                    "truncated": 0,
                    "depth_histogram": {
                        "1": 1, "2": 0, "3": 0, "4": 0,
                        "5": 0, "6": 0, "7": 0, "8": 0,
                    },
                    "entrypoint_kind_hits": {
                        "main": 1, "servlet": 1, "jaxrs": 0, "other": 0,
                    },
                },
                json.loads(default_query.stdout),
            )

            shallow_query = run_cli(
                "reach", "--out", out, "--depth", "1", "--json"
            )
            self.assertEqual(0, shallow_query.returncode, shallow_query.stderr)
            self.assertEqual(
                {
                    "depth": 1,
                    "methods": 1,
                    "reached": 1,
                    "reach_rate": 1.0,
                    "no_caller": 0,
                    "truncated": 1,
                    "depth_histogram": {"1": 1},
                    "entrypoint_kind_hits": {
                        "main": 0, "servlet": 1, "jaxrs": 0, "other": 0,
                    },
                },
                json.loads(shallow_query.stdout),
            )

    def test_reach_json_does_not_leak_source_identifiers(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-reach-private-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-reach-private-out-") as out:
            write_file(
                root,
                "src/com/secret/SecretDao.java",
                "package com.secret;\n"
                "public class SecretDao {\n"
                "    public void secretWrite() { run(\"UPDATE SECRET_TABLE SET SECRET_COLUMN = ?\"); }\n"
                "    void run(String sql) {}\n"
                "}\n",
            )
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("reach", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            for identifier in (
                    "com.secret", "SecretDao", "secretWrite", "SECRET_TABLE"):
                self.assertNotIn(identifier, queried.stdout)

    def test_reach_unknown_entrypoint_kind_is_counted_as_other(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-reach-kind-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-reach-kind-out-") as out:
            write_file(
                root,
                "src/p/App.java",
                "package p;\n"
                "public class App {\n"
                "    public static void main(String[] args) { run(); }\n"
                "    void run() { exec(\"SELECT C1 FROM T1\"); }\n"
                "    void exec(String sql) {}\n"
                "}\n",
            )
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            database = sqlite3.connect(os.path.join(out, "index.sqlite3"))
            try:
                database.execute(
                    "UPDATE entrypoints SET kind = ?", ("internalFramework",)
                )
                database.commit()
            finally:
                database.close()

            queried = run_cli("reach", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(1, payload["reached"])
            self.assertEqual(
                {"main": 0, "servlet": 0, "jaxrs": 0, "other": 1},
                payload["entrypoint_kind_hits"],
            )
            self.assertNotIn("internalFramework", queried.stdout)

    def test_reach_human_output_has_one_line_per_metric(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-reach-human-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-reach-human-out-") as out:
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("reach", "--out", out)
            self.assertEqual(0, queried.returncode, queried.stderr)
            lines = queried.stdout.splitlines()
            self.assertEqual(18, len(lines))
            self.assertIn("depth: 8", lines)
            self.assertIn("methods: 0", lines)
            self.assertIn("reach_rate: 0.0", lines)
            self.assertIn("depth_histogram.1: 0", lines)
            self.assertIn("depth_histogram.8: 0", lines)
            self.assertIn("entrypoint_kind_hits.main: 0", lines)
            self.assertIn("entrypoint_kind_hits.other: 0", lines)

    def test_reach_missing_and_wrong_schema_fail_with_rerun_message(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-reach-missing-out-") as out:
            missing = run_cli("reach", "--out", out, "--json")
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)
            self.assertIn("rerun index", missing.stderr.lower())

        with tempfile.TemporaryDirectory(prefix="codewiki-reach-schema-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-reach-schema-out-") as out:
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            database = sqlite3.connect(os.path.join(out, "index.sqlite3"))
            try:
                database.execute(
                    "UPDATE meta SET value = '999' WHERE key = 'schema_version'"
                )
                database.commit()
            finally:
                database.close()

            wrong = run_cli("reach", "--out", out, "--json")
            self.assertEqual(2, wrong.returncode)
            self.assertEqual("", wrong.stdout)
            self.assertIn("rerun index", wrong.stderr.lower())


if __name__ == "__main__":
    unittest.main()
