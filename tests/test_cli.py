from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from tests.fixture import fixture_directory, write_fixture


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "codewiki"] + list(args),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class CliTests(unittest.TestCase):
    def test_default_output_containment_uses_canonical_paths(self):
        from codewiki.cli import main

        with tempfile.TemporaryDirectory(prefix="codewiki-path-") as parent:
            real_repo = os.path.join(parent, "repo")
            os.mkdir(real_repo)
            with open(os.path.join(real_repo, "A.java"), "w", encoding="utf-8") as stream:
                stream.write("class A {}\n")
            alias_repo = os.path.join(parent, "repo-alias")
            os.symlink(real_repo, alias_repo)

            original_cwd = os.getcwd()
            try:
                os.chdir(alias_repo)
                stdout = StringIO()
                stderr = StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    default_inside = main(["index", alias_repo, "--quiet"])
            finally:
                os.chdir(original_cwd)
            self.assertEqual(2, default_inside)
            self.assertFalse(os.path.exists(os.path.join(real_repo, ".codewiki", "index.sqlite3")))

            with tempfile.TemporaryDirectory(prefix="codewiki-cwd-") as outside:
                original_cwd = os.getcwd()
                try:
                    os.chdir(outside)
                    default_outside = main(["index", alias_repo, "--quiet"])
                finally:
                    os.chdir(original_cwd)
                self.assertEqual(0, default_outside)
                self.assertTrue(os.path.isfile(os.path.join(outside, ".codewiki", "index.sqlite3")))

            explicit_out = os.path.join(real_repo, "explicit-index")
            self.assertEqual(0, main(["index", alias_repo, "--out", explicit_out, "--quiet"]))
            self.assertTrue(os.path.isfile(os.path.join(explicit_out, "index.sqlite3")))

    def test_index_prints_summary_timings_and_does_not_change_sources(self):
        with fixture_directory() as root, tempfile.TemporaryDirectory(prefix="codewiki-out-") as out:
            write_fixture(root)
            before = {}
            for dirpath, _dirnames, filenames in os.walk(root):
                for filename in filenames:
                    path = os.path.join(dirpath, filename)
                    with open(path, "rb") as stream:
                        before[os.path.relpath(path, root)] = stream.read()
            completed = run_cli("index", root, "--out", out, "--jobs", "1")
            self.assertEqual(0, completed.returncode, completed.stderr)
            for phrase in (
                "files scanned", "files analyzed", "symbols found", "scan", "symbols",
                "persist", "total",
            ):
                self.assertIn(phrase, completed.stdout)
            self.assertTrue(os.path.isfile(os.path.join(out, "index.sqlite3")))
            after = {}
            for dirpath, _dirnames, filenames in os.walk(root):
                for filename in filenames:
                    path = os.path.join(dirpath, filename)
                    with open(path, "rb") as stream:
                        after[os.path.relpath(path, root)] = stream.read()
            self.assertEqual(before, after)

    def test_oversized_files_are_reported_and_skip_counts_are_persisted(self):
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-large-file-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-large-out-") as out:
            path = os.path.join(root, "TooLarge.java")
            with open(path, "wb") as stream:
                stream.write(b"x" * 1500001)

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            self.assertIn("skipped too_large: 1", indexed.stdout)
            connection = open_index(os.path.join(out, "index.sqlite3"))
            try:
                self.assertEqual(
                    "1",
                    connection.execute(
                        "SELECT value FROM meta WHERE key = 'scan_skipped_too_large'"
                    ).fetchone()[0],
                )
            finally:
                connection.close()

    def test_index_reports_and_persists_each_nonzero_scan_skip_reason(self):
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-skip-reasons-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-skip-out-") as out:
            os.mkdir(os.path.join(root, "target"))
            with open(os.path.join(root, "target", "Ignored.java"), "w", encoding="utf-8") as stream:
                stream.write("class Ignored {}\n")
            with open(os.path.join(root, "archive.class"), "wb") as stream:
                stream.write(b"compiled")
            with open(os.path.join(root, "notes.bin"), "wb") as stream:
                stream.write(b"unknown")
            with open(os.path.join(root, "TooLarge.java"), "wb") as stream:
                stream.write(b"x" * 1500001)
            with open(os.path.join(root, "Generated.java"), "w", encoding="utf-8") as stream:
                stream.write("// Code generated by fixture\nclass Generated {}\n")
            with open(os.path.join(root, "Unreadable.java"), "wb") as stream:
                stream.write(b"\x00not text")

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            expected = {
                "dir_excluded": 1,
                "glob_excluded": 1,
                "unknown_language": 1,
                "too_large": 1,
                "unreadable": 1,
            }
            for reason, count in expected.items():
                self.assertIn("skipped %s: %d" % (reason, count), indexed.stdout)
            self.assertIn("files flagged generated: 1", indexed.stdout)
            self.assertNotIn("skipped generated:", indexed.stdout)

            connection = open_index(os.path.join(out, "index.sqlite3"))
            try:
                meta = dict(connection.execute(
                    "SELECT key, value FROM meta WHERE key LIKE 'scan_skipped%'")
                )
            finally:
                connection.close()
            self.assertEqual(expected, json.loads(meta["scan_skipped"]))
            self.assertNotIn("scan_skipped_generated", meta)
            for reason, count in expected.items():
                self.assertEqual(str(count), meta["scan_skipped_" + reason])

    def test_json_query_has_stable_shape_and_no_match_is_success(self):
        with fixture_directory() as root, tempfile.TemporaryDirectory(prefix="codewiki-out-") as out:
            write_fixture(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            queried = run_cli(
                "symbol", "OrderService.cancel", "--out", out, "--json", "--limit", "1"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(
                ["query", "count", "truncated", "results"], list(payload.keys())
            )
            self.assertEqual("OrderService.cancel", payload["query"])
            self.assertEqual(1, payload["count"])
            self.assertTrue(payload["truncated"])
            self.assertEqual({
                "fqn", "name", "kind", "package", "owner_fqn", "params", "param_count",
                "signature", "path", "line", "end_line", "confidence",
            }, set(payload["results"][0]))
            no_match = run_cli("symbol", "missing", "--out", out, "--json")
            self.assertEqual(0, no_match.returncode)
            self.assertEqual(0, json.loads(no_match.stdout)["count"])

    def test_non_java_files_are_recorded_and_multiline_params_survive_json(self):
        with fixture_directory() as root, tempfile.TemporaryDirectory(prefix="codewiki-out-") as out:
            write_fixture(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli(
                "symbol", "OrderService.multiline", "--out", out, "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(1, payload["count"])
            self.assertFalse(payload["truncated"])
            result = payload["results"][0]
            self.assertEqual([
                "fqn", "name", "kind", "package", "owner_fqn", "params",
                "param_count", "signature", "path", "line", "end_line",
                "confidence",
            ], list(result.keys()))
            self.assertEqual(["String", "int"], result["params"])
            self.assertEqual(2, result["param_count"])
            self.assertEqual("CONFIRMED", result["confidence"])

            from codewiki.store.db import open_index
            connection = open_index(os.path.join(out, "index.sqlite3"))
            try:
                non_java = connection.execute(
                    "SELECT path, language, package FROM files "
                    "WHERE language != 'java' ORDER BY path"
                ).fetchall()
                self.assertEqual([
                    ("config/application.properties", "properties", None),
                    ("config/application.xml", "xml", None),
                    ("db/schema.sql", "sql", None),
                ], non_java)
                self.assertEqual(0, connection.execute(
                    "SELECT count(*) FROM symbols AS s "
                    "JOIN files AS f ON f.file_id = s.file_id "
                    "WHERE f.language != 'java'"
                ).fetchone()[0])
            finally:
                connection.close()

    def test_cli_query_returns_wrapped_multiline_overloads(self):
        with fixture_directory() as root, tempfile.TemporaryDirectory(prefix="codewiki-out-") as out:
            write_fixture(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            queried = run_cli(
                "symbol", "OrderService.wrapped", "--out", out, "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(2, payload["count"])
            self.assertEqual({1, 2}, {
                result["param_count"] for result in payload["results"]
            })
            self.assertEqual({("String",), ("String", "int")}, {
                tuple(result["params"]) for result in payload["results"]
            })
            self.assertTrue(all(
                result["confidence"] == "CONFIRMED"
                for result in payload["results"]
            ))

    def test_index_and_query_persist_corrective_multiline_matrix(self):
        from codewiki.index.symbols import MAX_SIGNATURE

        many_parameters = ",\n".join(
            "      String value%d" % index for index in range(40)
        )
        source = (
            "class Corrective {\n"
            "  void calls() {\n"
            "    retVal.putIfAbsent(\n"
            "        ManagedBeanSettings.BEAN_CONTAINER, new SpringBeanContainer(factory));\n"
            "    return foo();\n"
            "    throw new IllegalStateException();\n"
            "  }\n"
            "  public Response delete() { return null; }\n"
            "  void wrapped(\n"
            "      Map<Class<? extends IBase>, BaseRuntimeElement<?>> value\n"
            "  ) {}\n"
            "  void wrapped(\n"
            "      @Nonnull String x,\n"
            "      final String[] names,\n"
            "      String... rest\n"
            "  ) {}\n"
            "  void zero(\n"
            "  ) {}\n"
            "  void many(\n"
            + many_parameters
            + "\n  ) {}\n"
            "  void broken(\n"
            "      String value\n"
            "}\n"
            "interface Contract {\n"
            "  void doIt(String a) throws Exception;\n"
            "}\n"
        )

        with tempfile.TemporaryDirectory(prefix="codewiki-corrective-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-out-") as out:
            source_path = os.path.join(root, "Corrective.java")
            with open(source_path, "wb") as stream:
                stream.write(source.encode("utf-8"))
            before = source.encode("utf-8")

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            with open(source_path, "rb") as stream:
                self.assertEqual(before, stream.read())

            os.remove(source_path)

            def query(name):
                completed = run_cli("symbol", name, "--out", out, "--json")
                self.assertEqual(0, completed.returncode, completed.stderr)
                return json.loads(completed.stdout)

            wrapped = query("Corrective.wrapped")
            self.assertEqual(2, wrapped["count"])
            self.assertEqual({
                ("Map<Class<? extends IBase>, BaseRuntimeElement<?>>",): 1,
                ("String", "String[]", "String..."): 3,
            }, {
                tuple(result["params"]): result["param_count"]
                for result in wrapped["results"]
            })
            self.assertTrue(all(
                result["confidence"] == "CONFIRMED"
                for result in wrapped["results"]
            ))

            zero = query("Corrective.zero")
            self.assertEqual(1, zero["count"])
            self.assertEqual([], zero["results"][0]["params"])
            self.assertEqual(0, zero["results"][0]["param_count"])
            self.assertEqual("CONFIRMED", zero["results"][0]["confidence"])

            broken = query("Corrective.broken")
            self.assertEqual(1, broken["count"])
            self.assertIsNone(broken["results"][0]["params"])
            self.assertIsNone(broken["results"][0]["param_count"])
            self.assertEqual("POSSIBLE", broken["results"][0]["confidence"])

            many = query("Corrective.many")
            self.assertEqual(1, many["count"])
            self.assertEqual(40, many["results"][0]["param_count"])
            self.assertEqual(["String"] * 40, many["results"][0]["params"])
            self.assertEqual("CONFIRMED", many["results"][0]["confidence"])
            self.assertEqual(200, MAX_SIGNATURE)
            self.assertEqual(MAX_SIGNATURE, len(many["results"][0]["signature"]))

            self.assertEqual(0, query("SpringBeanContainer")["count"])
            self.assertEqual(0, query("foo")["count"])
            self.assertEqual(0, query("IllegalStateException")["count"])
            delete = query("Corrective.delete")
            self.assertEqual(1, delete["count"])
            self.assertEqual("method", delete["results"][0]["kind"])
            interface_method = query("Contract.doIt")
            self.assertEqual(1, interface_method["count"])
            self.assertEqual(["String"], interface_method["results"][0]["params"])
            self.assertEqual(1, interface_method["results"][0]["param_count"])
            self.assertEqual("CONFIRMED", interface_method["results"][0]["confidence"])

    def test_missing_and_wrong_schema_fail_without_empty_json(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-out-") as out:
            missing = run_cli("symbol", "Order", "--out", out, "--json")
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)
            self.assertIn("rerun index", missing.stderr.lower())

        with fixture_directory() as root, tempfile.TemporaryDirectory(prefix="codewiki-out-") as out:
            write_fixture(root)
            self.assertEqual(0, run_cli("index", root, "--out", out).returncode)
            from codewiki.store.db import connect
            connection = connect(os.path.join(out, "index.sqlite3"))
            connection.execute("UPDATE meta SET value = '999' WHERE key = 'schema_version'")
            connection.commit()
            connection.close()
            wrong = run_cli("symbol", "Order", "--out", out, "--json")
            self.assertEqual(2, wrong.returncode)
            self.assertEqual("", wrong.stdout)
            self.assertIn("rerun index", wrong.stderr.lower())

    def test_query_module_is_independent_of_index_package(self):
        path = os.path.join(ROOT, "codewiki", "query", "symbols.py")
        with open(path, "r", encoding="utf-8") as stream:
            source = stream.read()
        self.assertNotIn("codewiki.index", source)
        self.assertNotIn("open(source", source)


if __name__ == "__main__":
    unittest.main()
