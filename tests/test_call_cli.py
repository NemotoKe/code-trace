from __future__ import annotations

import json
import os
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


def write_call_repository(root):
    write_file(
        root,
        "src/p/Contract.java",
        "package p;\n"
        "interface Contract {\n"
        "    void run();\n"
        "    void run(int value);\n"
        "}\n",
    )
    write_file(
        root,
        "src/p/Child.java",
        "package p;\n"
        "class Child implements Contract {\n"
        "    public void run() {}\n"
        "}\n",
    )
    write_file(
        root,
        "src/p/Callers.java",
        "package p;\n"
        "class Callers {\n"
        "    void direct(Child child) {\n"
        "        child.run();\n"
        "    }\n"
        "    void expanded(Contract contract) {\n"
        "        contract.run();\n"
        "    }\n"
        "}\n",
    )
    write_file(
        root,
        "src/p/Dao.java",
        "package p;\n"
        "class Dao { void save() {} }\n",
    )
    write_file(
        root,
        "src/p/Service.java",
        "package p;\n"
        "class Service {\n"
        "    MissingType retVal;\n"
        "    void execute(Dao dao) {\n"
        "        dao.save();\n"
        "        retVal.charAt();\n"
        "        unknown.missing();\n"
        "    }\n"
        "}\n",
    )


def index_call_repository(root, out):
    write_call_repository(root)
    result = run_cli("index", root, "--out", out, "--quiet")
    if result.returncode != 0:
        raise AssertionError(result.stderr)


class CallCliTests(unittest.TestCase):
    def test_json_state_vocabulary_and_precedence(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)
            write_file(
                root,
                "src/p/ReflectiveCaller.java",
                "package p;\n"
                "class ReflectiveCaller {\n"
                "    void run(String name) {\n"
                "        Class.forName(name).newInstance();\n"
                "    }\n"
                "}\n",
            )
            # Re-index after adding the reflective fixture.
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            callers = json.loads(run_cli(
                "callers", "p.Child.run", "--out", out, "--json"
            ).stdout)
            callers_limited = json.loads(run_cli(
                "callers", "p.Child.run", "--out", out, "--json",
                "--limit", "1",
            ).stdout)
            callers_absent = json.loads(run_cli(
                "callers", "p.Absent.run", "--out", out, "--json",
                "--limit", "0",
            ).stdout)
            callees = json.loads(run_cli(
                "callees", "p.ReflectiveCaller.run", "--out", out, "--json"
            ).stdout)
            callees_limited = json.loads(run_cli(
                "callees", "p.ReflectiveCaller.run", "--out", out,
                "--json", "--limit", "1",
            ).stdout)
            callees_absent = json.loads(run_cli(
                "callees", "p.Absent.run", "--out", out, "--json",
                "--limit", "0",
            ).stdout)

            self.assertEqual("COMPLETE", callers["status"])
            self.assertIsNone(callers["truncation_reason"])
            self.assertEqual([], callers["boundaries"])
            self.assertEqual("TRUNCATED", callers_limited["status"])
            self.assertEqual("limit", callers_limited["truncation_reason"])
            self.assertEqual("NOT_INDEXED", callers_absent["status"])
            self.assertIsNone(callers_absent["truncation_reason"])
            self.assertEqual([], callers_absent["boundaries"])

            self.assertEqual("STOPPED_AT_BOUNDARY", callees["status"])
            self.assertIsNone(callees["truncation_reason"])
            self.assertEqual(
                [
                    {
                        "kind": "dynamic_dispatch",
                        "reason": "reflective_dispatch",
                        "name": "forName",
                        "line": 4,
                    },
                    {
                        "kind": "dynamic_dispatch",
                        "reason": "reflective_dispatch",
                        "name": "newInstance",
                        "line": 4,
                    },
                ],
                callees["boundaries"],
            )
            self.assertEqual("TRUNCATED", callees_limited["status"])
            self.assertTrue(callees_limited["truncated"])
            self.assertEqual("limit", callees_limited["truncation_reason"])
            self.assertEqual(2, len(callees_limited["boundaries"]))
            self.assertEqual("NOT_INDEXED", callees_absent["status"])
            self.assertIsNone(callees_absent["truncation_reason"])
            self.assertEqual([], callees_absent["boundaries"])

    def test_callees_limit_keeps_boundaries_from_full_result_set(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)
            write_file(
                root,
                "src/p/MixedReflectiveCaller.java",
                "package p;\n"
                "class MixedReflectiveCaller {\n"
                "    void run(Dao dao, String name) {\n"
                "        dao.save();\n"
                "        Class.forName(name).newInstance();\n"
                "    }\n"
                "}\n",
            )
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            result = run_cli(
                "callees", "p.MixedReflectiveCaller.run", "--out", out,
                "--json", "--limit", "1",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["truncated"])
            self.assertEqual("TRUNCATED", payload["status"])
            self.assertEqual("limit", payload["truncation_reason"])
            self.assertEqual(
                [
                    {
                        "kind": "dynamic_dispatch",
                        "reason": "reflective_dispatch",
                        "name": "forName",
                        "line": 5,
                    },
                    {
                        "kind": "dynamic_dispatch",
                        "reason": "reflective_dispatch",
                        "name": "newInstance",
                        "line": 5,
                    },
                ],
                payload["boundaries"],
            )

    def test_callers_human_output_includes_rows_and_expanded_count(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)

            result = run_cli("callers", "p.Child.run", "--out", out)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "p.Callers.direct  src/p/Callers.java:4  CONFIRMED",
                    "p.Callers.expanded  src/p/Callers.java:7  POSSIBLE  via p.Contract.run",
                    "2 callers (1 direct, 1 via an overridden method)",
                ],
                result.stdout.splitlines(),
            )
            self.assertEqual("", result.stderr)

    def test_callees_human_output_includes_rows_and_resolved_count(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)

            result = run_cli("callees", "p.Service.execute", "--out", out)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "5  receiver  dao.save           CONFIRMED  single_member",
                    "6  receiver  retVal.charAt      UNRESOLVED  type_unresolved",
                    "7  receiver  unknown.missing    UNRESOLVED  no_declaration",
                    "3 callees (1 resolved, 2 unresolved)",
                ],
                result.stdout.splitlines(),
            )
            self.assertEqual("", result.stderr)

    def test_confirmed_keeps_only_confirmed_callers_and_callees(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)

            callers = run_cli(
                "callers", "p.Child.run", "--out", out, "--confirmed"
            )
            callees = run_cli(
                "callees", "p.Service.execute", "--out", out, "--confirmed"
            )

            self.assertEqual(0, callers.returncode, callers.stderr)
            self.assertEqual(
                [
                    "p.Callers.direct  src/p/Callers.java:4  CONFIRMED",
                    "1 callers (1 direct, 0 via an overridden method)",
                ],
                callers.stdout.splitlines(),
            )
            self.assertEqual(0, callees.returncode, callees.stderr)
            self.assertEqual(
                [
                    "5  receiver  dao.save           CONFIRMED  single_member",
                    "1 callees (1 resolved, 0 unresolved)",
                ],
                callees.stdout.splitlines(),
            )

    def test_direct_keeps_only_callers_that_named_the_queried_method(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)

            result = run_cli(
                "callers", "p.Child.run", "--out", out, "--direct"
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "p.Callers.direct  src/p/Callers.java:4  CONFIRMED",
                    "1 callers (1 direct, 0 via an overridden method)",
                ],
                result.stdout.splitlines(),
            )

    def test_limit_truncates_after_filters_and_reports_it(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)

            callers = run_cli(
                "callers", "p.Child.run", "--out", out, "--limit", "1"
            )
            callees = run_cli(
                "callees", "p.Service.execute", "--out", out, "--limit", "2"
            )

            self.assertEqual(0, callers.returncode, callers.stderr)
            self.assertEqual(
                [
                    "p.Callers.direct  src/p/Callers.java:4  CONFIRMED",
                    "truncated: limit reached",
                    "1 callers (1 direct, 0 via an overridden method)",
                ],
                callers.stdout.splitlines(),
            )
            self.assertEqual(0, callees.returncode, callees.stderr)
            self.assertEqual(
                [
                    "5  receiver  dao.save           CONFIRMED  single_member",
                    "6  receiver  retVal.charAt      UNRESOLVED  type_unresolved",
                    "truncated: limit reached",
                    "2 callees (1 resolved, 1 unresolved)",
                ],
                callees.stdout.splitlines(),
            )

    def test_empty_result_is_success_in_human_and_json(self):
        fqn = "p.NoSuchType.noSuchMethod"
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)

            callers = run_cli("callers", fqn, "--out", out)
            callees = run_cli("callees", fqn, "--out", out)
            callers_json = run_cli("callers", fqn, "--out", out, "--json")
            callees_json = run_cli("callees", fqn, "--out", out, "--json")

            self.assertEqual(0, callers.returncode, callers.stderr)
            self.assertEqual(
                ["0 callers (0 direct, 0 via an overridden method)"],
                callers.stdout.splitlines(),
            )
            self.assertEqual(0, callees.returncode, callees.stderr)
            self.assertEqual(
                ["0 callees (0 resolved, 0 unresolved)"],
                callees.stdout.splitlines(),
            )
            self.assertEqual(0, callers_json.returncode, callers_json.stderr)
            self.assertEqual(
                {
                    "fqn": fqn,
                    "direct_only": False,
                    "confirmed_only": False,
                    "count": 0,
                    "truncated": False,
                    "direct": 0,
                    "expanded": 0,
                    "results": [],
                    "status": "NOT_INDEXED",
                    "truncation_reason": None,
                    "boundaries": [],
                },
                json.loads(callers_json.stdout),
            )
            self.assertEqual(0, callees_json.returncode, callees_json.stderr)
            self.assertEqual(
                {
                    "fqn": fqn,
                    "confirmed_only": False,
                    "count": 0,
                    "truncated": False,
                    "resolved": 0,
                    "unresolved": 0,
                    "results": [],
                    "status": "NOT_INDEXED",
                    "truncation_reason": None,
                    "boundaries": [],
                },
                json.loads(callees_json.stdout),
            )

    def test_json_output_has_stable_shapes_nulls_and_limit_metadata(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-call-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-call-out-") as out:
            index_call_repository(root, out)

            callers = run_cli(
                "callers", "p.Child.run", "--out", out, "--json"
            )
            limited = run_cli(
                "callers", "p.Child.run", "--out", out,
                "--json", "--limit", "1",
            )
            callees = run_cli(
                "callees", "p.Service.execute", "--out", out, "--json"
            )

            self.assertEqual(0, callers.returncode, callers.stderr)
            callers_payload = json.loads(callers.stdout)
            self.assertEqual(
                [
                    "fqn", "direct_only", "confirmed_only", "count",
                    "truncated", "direct", "expanded", "results", "status",
                    "truncation_reason", "boundaries",
                ],
                list(callers_payload.keys()),
            )
            self.assertEqual("p.Child.run", callers_payload["fqn"])
            self.assertFalse(callers_payload["direct_only"])
            self.assertFalse(callers_payload["confirmed_only"])
            self.assertEqual(2, callers_payload["count"])
            self.assertFalse(callers_payload["truncated"])
            self.assertEqual("COMPLETE", callers_payload["status"])
            self.assertIsNone(callers_payload["truncation_reason"])
            self.assertEqual([], callers_payload["boundaries"])
            self.assertEqual(1, callers_payload["direct"])
            self.assertEqual(1, callers_payload["expanded"])
            self.assertEqual(
                [
                    "caller_fqn", "path", "line", "form", "receiver",
                    "name", "confidence", "reason", "via_fqn",
                ],
                list(callers_payload["results"][0].keys()),
            )
            self.assertEqual(
                {
                    "caller_fqn": "p.Callers.direct",
                    "path": "src/p/Callers.java",
                    "line": 4,
                    "form": "receiver",
                    "receiver": "child",
                    "name": "run",
                    "confidence": "CONFIRMED",
                    "reason": "single_member",
                    "via_fqn": None,
                },
                callers_payload["results"][0],
            )
            self.assertEqual("p.Contract.run", callers_payload["results"][1]["via_fqn"])

            self.assertEqual(0, limited.returncode, limited.stderr)
            limited_payload = json.loads(limited.stdout)
            self.assertEqual(1, limited_payload["count"])
            self.assertTrue(limited_payload["truncated"])
            self.assertEqual("TRUNCATED", limited_payload["status"])
            self.assertEqual("limit", limited_payload["truncation_reason"])
            self.assertEqual([], limited_payload["boundaries"])
            self.assertEqual(1, limited_payload["direct"])
            self.assertEqual(0, limited_payload["expanded"])

            self.assertEqual(0, callees.returncode, callees.stderr)
            callees_payload = json.loads(callees.stdout)
            self.assertEqual(
                [
                    "fqn", "confirmed_only", "count", "truncated",
                    "resolved", "unresolved", "results", "status",
                    "truncation_reason", "boundaries",
                ],
                list(callees_payload.keys()),
            )
            self.assertEqual("p.Service.execute", callees_payload["fqn"])
            self.assertFalse(callees_payload["confirmed_only"])
            self.assertEqual(3, callees_payload["count"])
            self.assertFalse(callees_payload["truncated"])
            self.assertEqual("COMPLETE", callees_payload["status"])
            self.assertIsNone(callees_payload["truncation_reason"])
            self.assertEqual([], callees_payload["boundaries"])
            self.assertEqual(1, callees_payload["resolved"])
            self.assertEqual(2, callees_payload["unresolved"])
            self.assertEqual(
                [
                    "line", "form", "receiver", "name", "target_fqn",
                    "confidence", "reason",
                ],
                list(callees_payload["results"][0].keys()),
            )
            self.assertEqual("p.Dao.save", callees_payload["results"][0]["target_fqn"])
            self.assertIsNone(callees_payload["results"][1]["target_fqn"])

    def test_missing_or_stale_index_uses_the_standard_error(self):
        for command in ("callers", "callees"):
            with tempfile.TemporaryDirectory(prefix="codewiki-call-missing-") as out:
                missing = run_cli(command, "p.Service.execute", "--out", out)
                self.assertEqual(2, missing.returncode)
                self.assertEqual("", missing.stdout)
                self.assertIn("index database missing or stale", missing.stderr)
                self.assertIn("rerun index", missing.stderr)

            with tempfile.TemporaryDirectory(prefix="codewiki-call-stale-") as out:
                write_file(out, "index.sqlite3", "not a sqlite database\n")
                stale = run_cli(command, "p.Service.execute", "--out", out)
                self.assertEqual(2, stale.returncode)
                self.assertEqual("", stale.stdout)
                self.assertIn("index database missing or stale", stale.stderr)
                self.assertIn("rerun index", stale.stderr)


if __name__ == "__main__":
    unittest.main()
