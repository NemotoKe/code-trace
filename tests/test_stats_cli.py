from __future__ import annotations

import ast
import json
import os
import re
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


def expected_payload_keys():
    return {
        "schema_version", "generated_at", "files", "symbols", "imports",
        "type_resolutions", "supertypes", "calls", "sql", "entrypoints",
    }


def implementation_call_reasons():
    reason_pattern = re.compile(r"[a-z_]+")
    reasons = set()
    source_paths = (
        os.path.join(ROOT, "codewiki", "index", "callgraph.py"),
        os.path.join(ROOT, "codewiki", "index", "pipeline.py"),
    )
    for source_path in source_paths:
        with open(source_path, "r", encoding="utf-8") as stream:
            tree = ast.parse(stream.read(), filename=source_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if isinstance(node.func, ast.Name):
                function_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function_name = node.func.attr
            else:
                continue
            if function_name not in ("_result", "CallResolution"):
                continue
            for literal in ast.walk(node.args[-1]):
                if (isinstance(literal, ast.Constant)
                        and isinstance(literal.value, str)
                        and reason_pattern.fullmatch(literal.value)):
                    reasons.add(literal.value)
    return reasons


class StatsCliIntegrationTests(unittest.TestCase):
    def test_call_reasons_match_the_implementation(self):
        from codewiki.query.stats import _CALL_REASONS

        implementation_reasons = implementation_call_reasons()
        catalog_reasons = set(_CALL_REASONS)
        self.assertEqual(
            implementation_reasons,
            catalog_reasons,
            "\n".join((
                "実装にあって _CALL_REASONS に無い: {}".format(
                    sorted(implementation_reasons - catalog_reasons)
                ),
                "_CALL_REASONS にあって実装に無い: {}".format(
                    sorted(catalog_reasons - implementation_reasons)
                ),
            )),
        )

    def test_stats_json_has_fixed_shape_and_zero_maps(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-empty-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-empty-out-") as out:
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("stats", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            self.assertEqual(1, len(queried.stdout.splitlines()))
            payload = json.loads(queried.stdout)

            self.assertEqual(expected_payload_keys(), set(payload))
            self.assertEqual("5", payload["schema_version"])
            self.assertTrue(payload["generated_at"].endswith("+00:00"))
            self.assertEqual(
                {"java": 0, "xml": 0, "sql": 0, "properties": 0, "other": 0},
                payload["files"],
            )
            self.assertEqual(
                {"CONFIRMED": 0, "POSSIBLE": 0, "UNRESOLVED": 0, "other": 0},
                payload["symbols"]["by_confidence"],
            )
            self.assertEqual(
                {
                    "class": 0, "interface": 0, "enum": 0, "record": 0,
                    "annotation": 0, "method": 0, "constructor": 0,
                    "other": 0,
                },
                payload["symbols"]["by_kind"],
            )
            self.assertEqual(
                {"single": 0, "wildcard": 0, "static_single": 0,
                 "static_wildcard": 0},
                payload["imports"]["by_form"],
            )
            metadata_outcomes = {
                "resolved": 0, "external": 0, "unresolved": 0, "excluded": 0,
            }
            self.assertEqual(metadata_outcomes, payload["imports"]["by_outcome"])
            self.assertEqual(
                metadata_outcomes, payload["type_resolutions"]["by_outcome"]
            )
            self.assertEqual(
                {
                    "resolved": 0, "external": 0, "unresolved": 0,
                    "excluded": 0, "other": 0,
                },
                payload["supertypes"]["by_outcome"],
            )
            self.assertEqual(
                {"receiver": 0, "bare": 0, "chained": 0,
                 "method_ref": 0, "constructor": 0, "other": 0},
                payload["calls"]["by_form"],
            )
            self.assertEqual(
                {"CONFIRMED": 0, "POSSIBLE": 0, "UNRESOLVED": 0, "other": 0},
                payload["calls"]["by_confidence"],
            )
            self.assertEqual(
                {
                    "form_not_resolved": 0,
                    "no_declaration": 0,
                    "type_unresolved": 0,
                    "receiver_not_internal": 0,
                    "reflective_dispatch": 0,
                    "single_member": 0,
                    "overloaded": 0,
                    "member_absent": 0,
                    "inherited_single_member": 0,
                    "inherited_overloaded": 0,
                    "static_single_member": 0,
                    "static_overloaded": 0,
                    "static_member_absent": 0,
                    "static_inherited_single_member": 0,
                    "static_inherited_overloaded": 0,
                    "inherited_field_single_member": 0,
                    "inherited_field_overloaded": 0,
                    "inherited_field_member_absent": 0,
                    "inherited_field_type_unresolved": 0,
                    "bare_single_member": 0,
                    "bare_overloaded": 0,
                    "bare_member_absent": 0,
                    "bare_inherited_single_member": 0,
                    "bare_inherited_overloaded": 0,
                    "bare_supertype_not_internal": 0,
                    "chained_single_member": 0,
                    "chained_overloaded": 0,
                    "chained_member_absent": 0,
                    "chained_inherited_single_member": 0,
                    "chained_inherited_overloaded": 0,
                    "chained_receiver_unresolved": 0,
                    "chained_return_type_not_internal": 0,
                    "chained_return_type_unknown": 0,
                    "other": 0,
                },
                payload["calls"]["by_reason"],
            )
            self.assertEqual(
                {
                    form + "|" + confidence: 0
                    for form in ("receiver", "bare", "chained", "method_ref", "constructor")
                    for confidence in ("CONFIRMED", "POSSIBLE", "UNRESOLVED")
                },
                payload["calls"]["by_form_confidence"],
            )
            self.assertEqual(
                {
                    verb + "|" + access: 0
                    for verb in ("select", "insert", "update", "delete", "merge")
                    for access in ("READ", "WRITE")
                },
                payload["sql"]["by_verb_access"],
            )
            self.assertEqual(
                {"main": 0, "servlet": 0, "jaxrs": 0, "other": 0},
                payload["entrypoints"]["by_kind"],
            )

            def assert_numeric(value):
                if isinstance(value, dict):
                    for nested in value.values():
                        assert_numeric(nested)
                else:
                    self.assertIsInstance(value, (int, float))

            for section in (
                    "files", "symbols", "imports", "type_resolutions",
                    "supertypes", "calls", "sql", "entrypoints"):
                assert_numeric(payload[section])

    def test_stats_json_reports_indexed_counts_and_rates(self):
        source = (
            "package p;\n"
            "public class Plain {\n"
            "    void read() {\n"
            "        String sql = \"SELECT ID FROM ORDERS\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-counts-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-counts-out-") as out:
            write_file(root, "src/p/Plain.java", source)
            write_file(root, "config/app.xml", "<app/>\n")
            write_file(root, "config/app.properties", "enabled=true\n")
            write_file(root, "db/schema.sql", "CREATE TABLE orders (id INTEGER);\n")

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            queried = run_cli("stats", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)

            self.assertEqual(
                {"java": 1, "xml": 1, "sql": 1, "properties": 1, "other": 0},
                payload["files"],
            )
            self.assertEqual(2, payload["symbols"]["total"])
            self.assertEqual(2, payload["symbols"]["by_confidence"]["CONFIRMED"])
            self.assertEqual(1, payload["symbols"]["by_kind"]["class"])
            self.assertEqual(1, payload["symbols"]["by_kind"]["method"])
            self.assertEqual(0, payload["imports"]["total"])
            self.assertEqual(0.0, payload["imports"]["internal_resolution_rate"])
            self.assertEqual(0.0, payload["supertypes"]["resolution_rate"])
            self.assertEqual(0, payload["calls"]["total"])
            self.assertEqual(
                payload["calls"]["total"],
                sum(payload["calls"]["by_reason"].values()),
            )
            self.assertEqual(1, payload["calls"]["methods"])
            self.assertEqual(1, payload["sql"]["accesses"])
            self.assertEqual(1, payload["sql"]["tables"])
            self.assertEqual(1, payload["sql"]["methods"])
            self.assertEqual(1, payload["sql"]["by_verb_access"]["select|READ"])
            self.assertEqual(1, payload["sql"]["column_accesses"])
            self.assertEqual(1, payload["sql"]["columns"])
            self.assertEqual(1, payload["sql"]["column_methods"])
            self.assertEqual(0, payload["sql"]["accesses_without_column"])
            self.assertEqual(0, payload["entrypoints"]["total"])
            self.assertEqual(0, payload["entrypoints"]["methods"])

    def test_stats_counts_duplicate_sql_accesses_as_one_table(self):
        source = (
            "class Plain {\n"
            "    void read() {\n"
            "        String first = \"SELECT ID FROM ORDERS\";\n"
            "        String second = \"SELECT ID FROM ORDERS\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-distinct-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-distinct-out-") as out:
            write_file(root, "Plain.java", source)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("stats", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)

            self.assertEqual(2, payload["sql"]["accesses"])
            self.assertEqual(1, payload["sql"]["tables"])

    def test_stats_counts_all_distinct_sql_and_call_targets(self):
        source = (
            "package com.acme;\n"
            "public class Repo {\n"
            "    void first()  { exec(\"UPDATE T1 SET C1 = ? WHERE C2 = ?\"); }\n"
            "    void second() { exec(\"SELECT C1, C2 FROM T1 WHERE C2 = ?\"); }\n"
            "    void third()  { exec(\"DELETE FROM T1 WHERE C2 = ?\"); exec(\"UPDATE T1 SET C1 = ?\"); }\n"
            "    void exec(String sql) {}\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-all-distinct-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-all-distinct-out-") as out:
            write_file(root, "src/com/acme/Repo.java", source)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("stats", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)

            self.assertEqual(4, payload["sql"]["accesses"])
            self.assertEqual(1, payload["sql"]["tables"])
            self.assertEqual(3, payload["sql"]["methods"])
            self.assertEqual(2, payload["sql"]["columns"])
            self.assertEqual(3, payload["sql"]["column_methods"])
            self.assertEqual(6, payload["sql"]["column_accesses"])
            self.assertEqual(4, payload["calls"]["total"])
            self.assertEqual(
                payload["calls"]["total"],
                sum(payload["calls"]["by_reason"].values()),
            )
            self.assertEqual(1, payload["calls"]["resolved_targets"])
            self.assertEqual(2, payload["sql"]["by_verb_access"]["update|WRITE"])
            self.assertEqual(1, payload["sql"]["by_verb_access"]["select|READ"])
            self.assertEqual(1, payload["sql"]["by_verb_access"]["delete|WRITE"])
            for key in (
                    "select|WRITE", "insert|READ", "insert|WRITE",
                    "update|READ", "delete|READ", "merge|READ", "merge|WRITE"):
                self.assertEqual(0, payload["sql"]["by_verb_access"][key])

    def test_stats_groups_call_reasons_for_resolved_and_unresolved_calls(self):
        dep_source = (
            "package p;\n"
            "public class Dep {\n"
            "    public Dep self() { return this; }\n"
            "    public void go() {}\n"
            "}\n"
        )
        use_source = (
            "package p;\n"
            "public class Use {\n"
            "    private Dep dep;\n"
            "    void a() { dep.go(); }\n"
            "    void b() { helper(); }\n"
            "    void c() { dep.self().go(); }\n"
            "    void d() { new Dep(); }\n"
            "    void helper() {}\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-call-reasons-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-call-reasons-out-") as out:
            write_file(root, "src/p/Dep.java", dep_source)
            write_file(root, "src/p/Use.java", use_source)

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            queried = run_cli("stats", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)

            calls = payload["calls"]
            by_reason = calls["by_reason"]
            self.assertEqual(5, calls["total"])
            self.assertEqual(2, by_reason["single_member"])
            self.assertEqual(1, by_reason["bare_single_member"])
            self.assertEqual(1, by_reason["chained_single_member"])
            self.assertEqual(1, by_reason["form_not_resolved"])
            self.assertEqual(0, by_reason["other"])
            self.assertEqual(calls["total"], sum(by_reason.values()))
            for reason, count in by_reason.items():
                if reason not in (
                        "single_member", "bare_single_member",
                        "chained_single_member", "form_not_resolved", "other"):
                    self.assertEqual(0, count, reason)

    def test_stats_groups_unknown_entrypoint_kind_as_other_without_leaking_it(self):
        unknown_kind = "shanaiFramework"
        source = (
            "public class App {\n"
            "    public static void main(String[] args) {}\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-other-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-other-out-") as out:
            write_file(root, "App.java", source)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            from codewiki.store.db import connect

            connection = connect(os.path.join(out, "index.sqlite3"))
            try:
                connection.execute(
                    "UPDATE entrypoints SET kind = ?", (unknown_kind,)
                )
                connection.commit()
            finally:
                connection.close()

            queried = run_cli("stats", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            by_kind = payload["entrypoints"]["by_kind"]
            self.assertEqual(1, by_kind["other"])
            self.assertEqual(payload["entrypoints"]["total"], sum(by_kind.values()))
            self.assertNotIn(unknown_kind, queried.stdout)

    def test_stats_json_contains_no_source_identifiers(self):
        source = (
            "package com.secret;\n"
            "public class SecretDao {\n"
            "    public void secretMethod() {\n"
            "        String sql = \"SELECT SECRET_COL FROM SECRET_TABLE\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-private-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-private-out-") as out:
            write_file(root, "src/com/secret/SecretService.java", source)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("stats", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            output = queried.stdout
            payload = json.loads(output)
            self.assertGreater(payload["symbols"]["total"], 0)
            self.assertGreater(payload["sql"]["accesses"], 0)
            for identifier in (
                    "com.secret", "SecretDao", "secretMethod",
                    "SECRET_TABLE", "SECRET_COL"):
                self.assertNotIn(identifier, output)
            self.assertNotIn(root, output)

    def test_stats_human_output_has_one_line_per_metric(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-human-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-human-out-") as out:
            self.assertEqual(0, run_cli("index", root, "--out", out, "--quiet").returncode)
            queried = run_cli("stats", "--out", out)
            self.assertEqual(0, queried.returncode, queried.stderr)
            lines = queried.stdout.splitlines()
            self.assertEqual(126, len(lines))
            self.assertEqual(len(lines), len(set(lines)))
            self.assertIn("files.java: 0", lines)
            self.assertIn("calls.by_form_confidence.receiver|CONFIRMED: 0", lines)
            self.assertIn("calls.by_reason.form_not_resolved: 0", lines)
            self.assertIn("sql.by_verb_access.select|READ: 0", lines)
            self.assertIn("entrypoints.by_kind.main: 0", lines)
            self.assertNotIn(root, queried.stdout)

    def test_stats_missing_and_wrong_schema_fail_with_rerun_message(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-stats-missing-out-") as out:
            missing = run_cli("stats", "--out", out, "--json")
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)
            self.assertIn("rerun index", missing.stderr.lower())

        with tempfile.TemporaryDirectory(prefix="codewiki-stats-schema-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-stats-schema-out-") as out:
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            from codewiki.store.db import connect

            connection = connect(os.path.join(out, "index.sqlite3"))
            try:
                connection.execute(
                    "UPDATE meta SET value = '999' WHERE key = 'schema_version'"
                )
                connection.commit()
            finally:
                connection.close()

            wrong = run_cli("stats", "--out", out, "--json")
            self.assertEqual(2, wrong.returncode)
            self.assertEqual("", wrong.stdout)
            self.assertIn("rerun index", wrong.stderr.lower())


if __name__ == "__main__":
    unittest.main()
