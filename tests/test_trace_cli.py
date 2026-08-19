from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from codewiki.cli import _parser


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = "status.StatusUpdateServiceWithAnExcessivelyLongName.updateStatus"
NO_ENTRYPOINT_TARGET = "status.Unreached.run"
NOT_INDEXED_TARGET = "status.NotIndexed.run"
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


def write_profile_trace_repository(root):
    write_file(
        root,
        "src/p/Target.java",
        "package p;\n"
        "public class Target { public void run() {} }\n",
    )
    for number in range(1, 6):
        target_type = "Target" if number == 1 else "C%d" % (number - 1)
        target_method = "run" if number == 1 else "call"
        write_file(
            root,
            "src/p/C%d.java" % number,
            "package p;\n"
            "public class C%d {\n"
            "    public void call() {\n"
            "        %s target = new %s();\n"
            "        target.%s();\n"
            "    }\n"
            "}\n" % (number, target_type, target_type, target_method),
        )


class TraceCliIntegrationTests(unittest.TestCase):
    def test_parser_keeps_omitted_depth_distinguishable_from_explicit_depth(self):
        omitted = _parser().parse_args(["trace-up", "p.Target.run"])
        explicit = _parser().parse_args([
            "trace-up", "p.Target.run", "--depth", "8"
        ])

        self.assertIsNone(omitted.depth)
        self.assertIsNone(omitted.profile)
        self.assertEqual(8, explicit.depth)

    def test_profile_controls_trace_depth_and_explicit_override(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-profile-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-profile-out-") as out:
            write_profile_trace_repository(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            default = json.loads(run_cli(
                "trace-up", "p.Target.run", "--out", out, "--json"
            ).stdout)
            detailed = json.loads(run_cli(
                "trace-up", "p.Target.run", "--out", out,
                "--profile", "detailed", "--json"
            ).stdout)
            normal = json.loads(run_cli(
                "trace-up", "p.Target.run", "--out", out,
                "--profile", "normal", "--json"
            ).stdout)
            normal_then_explicit = json.loads(run_cli(
                "trace-up", "p.Target.run", "--out", out,
                "--profile", "normal", "--depth", "12", "--json"
            ).stdout)
            explicit_then_normal = json.loads(run_cli(
                "trace-up", "p.Target.run", "--out", out,
                "--depth", "12", "--profile", "normal", "--json"
            ).stdout)

            self.assertEqual(8, default["depth"])
            self.assertEqual(5, default["count"])
            self.assertFalse(default["truncated"])
            self.assertIsNone(default["truncation_reason"])
            self.assertIsNone(default["profile"])
            self.assertEqual(default["results"], detailed["results"])
            self.assertEqual(8, detailed["depth"])
            self.assertEqual("detailed", detailed["profile"])
            self.assertEqual(4, normal["depth"])
            self.assertEqual(4, normal["count"])
            self.assertTrue(normal["truncated"])
            self.assertEqual("depth", normal["truncation_reason"])
            self.assertEqual("normal", normal["profile"])
            self.assertEqual(12, normal_then_explicit["depth"])
            self.assertEqual(5, normal_then_explicit["count"])
            self.assertFalse(normal_then_explicit["truncated"])
            self.assertIsNone(normal_then_explicit["truncation_reason"])
            self.assertEqual("normal", normal_then_explicit["profile"])
            self.assertEqual(
                normal_then_explicit["results"], explicit_then_normal["results"]
            )

    def test_normal_profile_does_not_truncate_a_small_trace(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-profile-small-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-profile-small-out-") as out:
            self._index(root, out)

            payload = json.loads(run_cli(
                "trace-up", TARGET, "--out", out, "--profile", "normal",
                "--json"
            ).stdout)

            self.assertEqual("COMPLETE", payload["status"])
            self.assertFalse(payload["truncated"])
            self.assertIsNone(payload["truncation_reason"])

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
                    "status", "truncation_reason", "boundaries",
                    "max_depth_reached", "results", "profile",
                ],
                list(payload.keys()),
            )
            self.assertEqual(TARGET, payload["fqn"])
            self.assertEqual(8, payload["depth"])
            self.assertIsNone(payload["profile"])
            self.assertFalse(payload["entrypoints_only"])
            self.assertEqual(3, payload["count"])
            self.assertFalse(payload["truncated"])
            self.assertEqual("COMPLETE", payload["status"])
            self.assertIsNone(payload["truncation_reason"])
            self.assertEqual([], payload["boundaries"])
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
            self.assertEqual("TRUNCATED", payload["status"])
            self.assertEqual("depth", payload["truncation_reason"])
            self.assertEqual([], payload["boundaries"])
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
                    "status", "truncation_reason", "boundaries",
                    "max_depth_reached", "results", "profile",
                ],
                list(payload.keys()),
            )
            self.assertEqual(2, payload["count"])
            self.assertTrue(payload["entrypoints_only"])
            self.assertFalse(payload["truncated"])
            self.assertEqual("COMPLETE", payload["status"])
            self.assertIsNone(payload["truncation_reason"])
            self.assertEqual([], payload["boundaries"])
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

    def test_trace_up_json_state_vocabulary_plain_and_entrypoints(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            cases = [
                (TARGET, [], "COMPLETE", None, False),
                (TARGET, ["--depth", "1"], "TRUNCATED", "depth", False),
                (TARGET, ["--limit", "1"], "TRUNCATED", "limit", False),
                (NO_ENTRYPOINT_TARGET, [], "COMPLETE", None, False),
                (NOT_INDEXED_TARGET, ["--limit", "0"], "NOT_INDEXED", None, False),
            ]
            for fqn, options, status, reason, entrypoints in cases:
                queried = run_cli(
                    "trace-up", fqn, "--out", out, *options,
                    *( ["--entrypoints"] if entrypoints else []), "--json",
                )
                self.assertEqual(0, queried.returncode, queried.stderr)
                payload = json.loads(queried.stdout)
                self.assertEqual(status, payload["status"], fqn)
                self.assertEqual(reason, payload["truncation_reason"], fqn)
                self.assertEqual([], payload["boundaries"], fqn)

            entrypoint_cases = [
                (TARGET, [], "COMPLETE", None),
                (TARGET, ["--depth", "1"], "TRUNCATED", "depth"),
                (TARGET, ["--limit", "0"], "TRUNCATED", "limit"),
                (NO_ENTRYPOINT_TARGET, [], "COMPLETE", None),
                (NOT_INDEXED_TARGET, ["--limit", "0"], "NOT_INDEXED", None),
            ]
            for fqn, options, status, reason in entrypoint_cases:
                queried = run_cli(
                    "trace-up", fqn, "--out", out, *options,
                    "--entrypoints", "--json",
                )
                self.assertEqual(0, queried.returncode, queried.stderr)
                payload = json.loads(queried.stdout)
                self.assertEqual(status, payload["status"], fqn)
                self.assertEqual(reason, payload["truncation_reason"], fqn)
                self.assertEqual([], payload["boundaries"], fqn)

    def test_plain_trace_depth_reason_wins_when_limit_also_truncates(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            queried = run_cli(
                "trace-up", TARGET, "--out", out, "--depth", "1",
                "--limit", "0", "--json",
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertTrue(payload["truncated"])
            self.assertEqual("TRUNCATED", payload["status"])
            self.assertEqual("depth", payload["truncation_reason"])
            self.assertEqual([], payload["boundaries"])

    def test_entrypoints_depth_reason_wins_when_limit_also_truncates(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-trace-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-trace-out-") as out:
            self._index(root, out)

            connection = sqlite3.connect(os.path.join(out, "index.sqlite3"))
            try:
                file_id, owner_fqn, line = connection.execute(
                    "SELECT file_id, owner_fqn, line FROM symbols WHERE fqn = ?",
                    (SERVICE,),
                ).fetchone()
                connection.executemany(
                    "INSERT INTO entrypoints(file_id, method_fqn, owner_fqn, kind, "
                    "reason, line) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (file_id, SERVICE, owner_fqn, "test-main", "test", line),
                        (file_id, SERVICE, owner_fqn, "test-servlet", "test", line),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            queried = run_cli(
                "trace-up", TARGET, "--out", out, "--entrypoints", "--depth", "1",
                "--limit", "1", "--json",
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertTrue(payload["truncated"])
            self.assertEqual("TRUNCATED", payload["status"])
            self.assertEqual("depth", payload["truncation_reason"])
            self.assertEqual([], payload["boundaries"])

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
