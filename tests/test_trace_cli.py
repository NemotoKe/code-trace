from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = "status.StatusUpdateServiceWithAnExcessivelyLongName.updateStatus"
NO_ENTRYPOINT_TARGET = "status.Unreached.run"
SERVICE = "app.StatusService.invoke"
MAIN = "batch.LongRunningJobWithAnExcessivelyLongName.main"
SERVLET = "web.StatusServlet.doPost"


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


class TraceCliIntegrationTests(unittest.TestCase):
    def _fixture(self, root, jaxrs=False, main=True):
        write_file(
            root,
            "src/status/StatusUpdateServiceWithAnExcessivelyLongName.java",
            "package status;\n"
            "public class StatusUpdateServiceWithAnExcessivelyLongName {\n"
            "    public void updateStatus() {\n"
            "        String sql = \"UPDATE STATUS_RECORDS SET STATUS = ? WHERE ID = ?\";\n"
            "    }\n"
            "}\n",
        )
        write_file(
            root,
            "src/app/StatusService.java",
            "package app;\n"
            "import status.StatusUpdateServiceWithAnExcessivelyLongName;\n"
            "public class StatusService {\n"
            "    public void invoke() {\n"
            "        StatusUpdateServiceWithAnExcessivelyLongName target = "
            "new StatusUpdateServiceWithAnExcessivelyLongName();\n"
            "        target.updateStatus();\n"
            "    }\n"
            "}\n",
        )
        write_file(
            root,
            "src/web/StatusServlet.java",
            "package web;\n"
            "import app.StatusService;\n"
            + ("@Path(\"/status\")\n" if jaxrs else "")
            + "public class StatusServlet extends HttpServlet {\n"
            + ("    @GET\n" if jaxrs else "")
            + "    public void doPost() {\n"
            + "        StatusService service = new StatusService();\n"
            + "        service.invoke();\n"
            + "    }\n"
            + "}\n",
        )
        write_file(
            root,
            "src/status/Unreached.java",
            "package status;\n"
            "public class Unreached {\n"
            "    public void run() {}\n"
            "}\n",
        )
        if main:
            write_file(
                root,
                "src/batch/LongRunningJobWithAnExcessivelyLongName.java",
                "package batch;\n"
                "import app.StatusService;\n"
                "public class LongRunningJobWithAnExcessivelyLongName {\n"
                "    public static void main(String[] args) {\n"
                "        StatusService service = new StatusService();\n"
                "        service.invoke();\n"
                "    }\n"
                "}\n",
            )

    def _index(self, root, out, jaxrs=False, main=True):
        self._fixture(root, jaxrs=jaxrs, main=main)
        indexed = run_cli("index", root, "--out", out, "--jobs", "1", "--quiet")
        self.assertEqual(
            0,
            indexed.returncode,
            "index stdout:\n%s\nindex stderr:\n%s"
            % (indexed.stdout, indexed.stderr),
        )

    def test_trace_up_json_and_human_output_preserve_trace_order_and_spacing(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            connection = sqlite3.connect(os.path.join(out, "index.sqlite3"))
            try:
                writes = connection.execute(
                    "SELECT method_fqn, table_name, access, statement "
                    "FROM sql_accesses WHERE method_fqn = ? "
                    "AND access = 'WRITE' ORDER BY access_id",
                    (TARGET,),
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(
                [
                    (
                        TARGET,
                        "STATUS_RECORDS",
                        "WRITE",
                        "UPDATE STATUS_RECORDS SET STATUS = ? WHERE ID = ?",
                    ),
                ],
                writes,
            )

            queried = run_cli("trace-up", TARGET, "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(
                [
                    "fqn", "depth", "entrypoints_only", "count", "truncated",
                    "max_depth_reached", "results",
                ],
                list(payload.keys()),
            )
            self.assertEqual(TARGET, payload["fqn"])
            self.assertEqual(8, payload["depth"])
            self.assertFalse(payload["entrypoints_only"])
            self.assertEqual(3, payload["count"])
            self.assertFalse(payload["truncated"])
            self.assertEqual(2, payload["max_depth_reached"])
            self.assertEqual(
                [
                    {
                        "fqn": SERVICE,
                        "depth": 1,
                        "path": "src/app/StatusService.java",
                        "line": 6,
                        "confidence": "CONFIRMED",
                        "via_fqn": None,
                        "parent_fqn": TARGET,
                    },
                    {
                        "fqn": MAIN,
                        "depth": 2,
                        "path": "src/batch/LongRunningJobWithAnExcessivelyLongName.java",
                        "line": 6,
                        "confidence": "CONFIRMED",
                        "via_fqn": None,
                        "parent_fqn": SERVICE,
                    },
                    {
                        "fqn": SERVLET,
                        "depth": 2,
                        "path": "src/web/StatusServlet.java",
                        "line": 6,
                        "confidence": "CONFIRMED",
                        "via_fqn": None,
                        "parent_fqn": SERVICE,
                    },
                ],
                payload["results"],
            )

            human = run_cli("trace-up", TARGET, "--out", out)
            self.assertEqual(0, human.returncode, human.stderr)
            self.assertEqual(
                [
                    "1  app.StatusService.invoke  src/app/StatusService.java:6  CONFIRMED",
                    "2  batch.LongRunningJobWithAnExcessivelyLongName.main  "
                    "src/batch/LongRunningJobWithAnExcessivelyLongName.java:6  CONFIRMED",
                    "2  web.StatusServlet.doPost  src/web/StatusServlet.java:6  CONFIRMED",
                    "3 methods reach " + TARGET + " (max depth 2)",
                ],
                human.stdout.splitlines(),
            )
            self.assertEqual("", human.stderr)

    def test_depth_one_marks_json_truncated(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            queried = run_cli(
                "trace-up", TARGET, "--out", out, "--depth", "1", "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(1, payload["depth"])
            self.assertTrue(payload["truncated"])
            self.assertEqual(1, payload["count"])
            self.assertEqual(1, payload["max_depth_reached"])
            self.assertEqual(SERVICE, payload["results"][0]["fqn"])

    def test_limit_prints_truncation_and_limits_final_rows(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            limited = run_cli(
                "trace-up", TARGET, "--out", out, "--limit", "1"
            )
            self.assertEqual(0, limited.returncode, limited.stderr)
            self.assertEqual(
                [
                    "1  app.StatusService.invoke  src/app/StatusService.java:6  CONFIRMED",
                    "truncated: limit reached",
                    "1 method reaches " + TARGET + " (max depth 1)",
                ],
                limited.stdout.splitlines(),
            )

    def test_entrypoints_expand_chains_and_handle_no_match(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            queried = run_cli(
                "trace-up", TARGET, "--out", out, "--entrypoints", "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(
                [
                    "fqn", "depth", "entrypoints_only", "count", "truncated",
                    "max_depth_reached", "results",
                ],
                list(payload.keys()),
            )
            self.assertEqual(2, payload["count"])
            self.assertTrue(payload["entrypoints_only"])
            self.assertFalse(payload["truncated"])
            self.assertEqual(2, payload["max_depth_reached"])
            self.assertEqual(
                [
                    {
                        "fqn": MAIN,
                        "depth": 2,
                        "path": "src/batch/LongRunningJobWithAnExcessivelyLongName.java",
                        "line": 6,
                        "confidence": "CONFIRMED",
                        "via_fqn": None,
                        "parent_fqn": SERVICE,
                        "kind": "main",
                        "chain": [
                            {
                                "fqn": MAIN,
                                "depth": 2,
                                "path": "src/batch/LongRunningJobWithAnExcessivelyLongName.java",
                                "line": 6,
                                "confidence": "CONFIRMED",
                                "via_fqn": None,
                                "parent_fqn": SERVICE,
                            },
                            {
                                "fqn": SERVICE,
                                "depth": 1,
                                "path": "src/app/StatusService.java",
                                "line": 6,
                                "confidence": "CONFIRMED",
                                "via_fqn": None,
                                "parent_fqn": TARGET,
                            },
                            {"fqn": TARGET},
                        ],
                    },
                    {
                        "fqn": SERVLET,
                        "depth": 2,
                        "path": "src/web/StatusServlet.java",
                        "line": 6,
                        "confidence": "CONFIRMED",
                        "via_fqn": None,
                        "parent_fqn": SERVICE,
                        "kind": "servlet",
                        "chain": [
                            {
                                "fqn": SERVLET,
                                "depth": 2,
                                "path": "src/web/StatusServlet.java",
                                "line": 6,
                                "confidence": "CONFIRMED",
                                "via_fqn": None,
                                "parent_fqn": SERVICE,
                            },
                            {
                                "fqn": SERVICE,
                                "depth": 1,
                                "path": "src/app/StatusService.java",
                                "line": 6,
                                "confidence": "CONFIRMED",
                                "via_fqn": None,
                                "parent_fqn": TARGET,
                            },
                            {"fqn": TARGET},
                        ],
                    },
                ],
                payload["results"],
            )

            human = run_cli("trace-up", TARGET, "--out", out, "--entrypoints")
            self.assertEqual(0, human.returncode, human.stderr)
            self.assertEqual(
                [
                    "main  " + MAIN + "  "
                    "src/batch/LongRunningJobWithAnExcessivelyLongName.java:6",
                    "    -> app.StatusService.invoke  src/app/StatusService.java:6  CONFIRMED",
                    "    -> " + TARGET,
                    "servlet  " + SERVLET + "  src/web/StatusServlet.java:6",
                    "    -> app.StatusService.invoke  src/app/StatusService.java:6  CONFIRMED",
                    "    -> " + TARGET,
                    "2 entry points reach " + TARGET,
                ],
                human.stdout.splitlines(),
            )

            no_match = run_cli(
                "trace-up", NO_ENTRYPOINT_TARGET, "--out", out,
                "--entrypoints", "--limit", "1"
            )
            self.assertEqual(0, no_match.returncode, no_match.stderr)
            self.assertEqual("", no_match.stderr)
            self.assertEqual(
                "no entry point reaches " + NO_ENTRYPOINT_TARGET + "\n",
                no_match.stdout,
            )

    def test_entrypoints_limit_zero_reports_truncation_after_matching(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            limited = run_cli(
                "trace-up", TARGET, "--out", out, "--entrypoints", "--limit", "0"
            )
            self.assertEqual(0, limited.returncode, limited.stderr)
            self.assertEqual("", limited.stderr)
            self.assertEqual(
                [
                    "truncated: limit reached",
                    "0 entry points reach " + TARGET,
                ],
                limited.stdout.splitlines(),
            )

    def test_entrypoints_emit_each_kind_for_same_reached_method(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out, jaxrs=True, main=False)

            queried = run_cli(
                "trace-up", TARGET, "--out", out, "--entrypoints", "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(2, payload["count"])
            self.assertEqual(
                [(SERVLET, "jaxrs"), (SERVLET, "servlet")],
                [
                    (result["fqn"], result["kind"])
                    for result in payload["results"]
                ],
            )
            self.assertEqual(
                [
                    [SERVLET, SERVICE, TARGET],
                    [SERVLET, SERVICE, TARGET],
                ],
                [
                    [node["fqn"] for node in result["chain"]]
                    for result in payload["results"]
                ],
            )


if __name__ == "__main__":
    unittest.main()
