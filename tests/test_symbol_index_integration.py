from __future__ import annotations

import ast
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from codewiki import parallel


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_codewiki(*args):
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
    with open(path, "wb") as stream:
        stream.write(contents.encode("utf-8"))
    return path


def byte_snapshot(root):
    snapshot = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            path = os.path.join(dirpath, filename)
            with open(path, "rb") as stream:
                snapshot[os.path.relpath(path, root)] = hashlib.sha256(
                    stream.read()
                ).hexdigest()
    return snapshot


def logical_database_rows(path):
    connection = sqlite3.connect(path)
    try:
        files = connection.execute(
            "SELECT file_id, path, language, package, lines, sha256, "
            "is_test, is_generated FROM files ORDER BY file_id"
        ).fetchall()
        symbols = connection.execute(
            "SELECT symbol_id, file_id, name, kind, fqn, owner_fqn, params, "
            "param_count, signature, line, end_line, confidence "
            "FROM symbols ORDER BY symbol_id"
        ).fetchall()
        meta = connection.execute(
            "SELECT key, value FROM meta WHERE key IN "
            "('schema_version', 'repo_root') ORDER BY key"
        ).fetchall()
        calls = connection.execute(
            "SELECT call_id, file_id, caller_fqn, caller_kind, line, form, "
            "receiver, name, owner_fqn, target_fqn, confidence, reason, "
            "candidates FROM calls ORDER BY call_id"
        ).fetchall()
        supertypes = connection.execute(
            "SELECT supertype_id, file_id, owner_fqn, line, relation, raw, name, "
            "target_fqn, rule, outcome, candidates FROM supertypes "
            "ORDER BY supertype_id"
        ).fetchall()
        sql_accesses = connection.execute(
            "SELECT access_id, file_id, method_fqn, method_kind, line, verb, "
            "table_name, table_key, access, statement FROM sql_accesses "
            "ORDER BY access_id"
        ).fetchall()
        return files, symbols, meta, calls, supertypes, sql_accesses
    finally:
        connection.close()


class SymbolIndexIntegrationTests(unittest.TestCase):
    def test_cli_index_to_sqlite_to_json_handles_braces_comments_and_multiline_overloads(self):
        source = (
            "package demo;\n"
            "\n"
            "public class BraceService {\n"
            "    public void cancel(\n"
            "        String orderId\n"
            "    ) {\n"
            "        String text = \"} not a brace {\";\n"
            "        /* } comment { */\n"
            "        if (orderId != null) {\n"
            "            text = text + orderId;\n"
            "        }\n"
            "    }\n"
            "\n"
            "    public void cancel(\n"
            "        String orderId,\n"
            "        int reason\n"
            "    ) {\n"
            "        // } comment {\n"
            "        String text = \"{ still not a brace }\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-e2e-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-e2e-out-") as out:
            write_file(root, "src/demo/BraceService.java", source)

            indexed = run_codewiki(
                "index", root, "--out", out, "--jobs", "1"
            )
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            self.assertTrue(os.path.isfile(os.path.join(out, "index.sqlite3")))
            for stage in ("scan", "symbols", "persist", "total"):
                self.assertIn(stage + ":", indexed.stdout)

            queried = run_codewiki(
                "symbol", "BraceService.cancel", "--out", out, "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual("BraceService.cancel", payload["query"])
            self.assertEqual(2, payload["count"])
            self.assertFalse(payload["truncated"])
            self.assertEqual(
                {
                    "fqn", "name", "kind", "package", "owner_fqn", "params",
                    "param_count", "signature", "path", "line", "end_line",
                    "confidence",
                },
                set(payload["results"][0]),
            )
            by_count = {
                result["param_count"]: result for result in payload["results"]
            }
            self.assertEqual(["String"], by_count[1]["params"])
            self.assertEqual(["String", "int"], by_count[2]["params"])
            self.assertEqual(4, by_count[1]["line"])
            self.assertEqual(12, by_count[1]["end_line"])
            self.assertEqual(14, by_count[2]["line"])
            self.assertEqual(20, by_count[2]["end_line"])
            self.assertTrue(all(
                result["fqn"] == "demo.BraceService.cancel"
                and result["path"] == "src/demo/BraceService.java"
                and result["confidence"] == "CONFIRMED"
                for result in payload["results"]
            ))

            class_query = run_codewiki(
                "symbol", "BraceService", "--out", out, "--json"
            )
            self.assertEqual(0, class_query.returncode, class_query.stderr)
            class_payload = json.loads(class_query.stdout)
            self.assertEqual(1, class_payload["count"])
            class_result = class_payload["results"][0]
            self.assertEqual(
                {
                    "fqn", "name", "kind", "package", "owner_fqn", "params",
                    "param_count", "signature", "path", "line", "end_line",
                    "confidence",
                },
                set(class_result),
            )
            self.assertEqual("demo.BraceService", class_result["fqn"])
            self.assertEqual(3, class_result["line"])
            self.assertEqual(21, class_result["end_line"])
            self.assertIsNone(class_result["owner_fqn"])
            self.assertIsNone(class_result["params"])
            self.assertIsNone(class_result["param_count"])

    def test_cli_index_is_byte_immutable_to_the_scanned_repository(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-immutable-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-immutable-out-") as out:
            write_file(
                root,
                "src/Immutable.java",
                "package immutable;\npublic class Immutable {\n"
                "  void run(String value) {\n"
                "    String text = \"}\"; // { }\n"
                "  }\n}\n",
            )
            write_file(root, "README.txt", "not indexed but still must remain\n")
            before = byte_snapshot(root)

            indexed = run_codewiki(
                "index", root, "--out", out, "--jobs", "1", "--quiet"
            )
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            self.assertEqual(before, byte_snapshot(root))

    def test_jobs_one_and_two_produce_identical_persisted_rows(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-parallel-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-jobs-one-") as one, \
                tempfile.TemporaryDirectory(prefix="codewiki-jobs-two-") as two:
            workload = parallel.MIN_FILES + 1
            for index in range(workload):
                write_file(
                    root,
                    "src/pkg%03d/Type%03d.java" % (index % 10, index),
                    "package pkg%03d;\n" % (index % 10)
                    + "public class Type%03d extends Base%03d {\n" % (index, index)
                    + "  void method(String value) {\n"
                    + "    value.trim();\n"
                    + "    String query = \"SELECT * FROM Table%03d\";\n" % index
                    + "  }\n"
                    + "}\n",
                )

            serial = run_codewiki(
                "index", root, "--out", one, "--jobs", "1", "--quiet"
            )
            self.assertEqual(0, serial.returncode, serial.stderr)
            parallel_result = run_codewiki(
                "index", root, "--out", two, "--jobs", "2", "--quiet"
            )
            self.assertEqual(0, parallel_result.returncode, parallel_result.stderr)

            serial_rows = logical_database_rows(os.path.join(one, "index.sqlite3"))
            parallel_rows = logical_database_rows(os.path.join(two, "index.sqlite3"))
            self.assertEqual(serial_rows, parallel_rows)
            self.assertEqual(workload, len(parallel_rows[0]))
            self.assertEqual(workload * 2, len(parallel_rows[1]))
            self.assertEqual(workload, len(parallel_rows[3]))
            self.assertEqual(workload, len(parallel_rows[4]))
            self.assertEqual(workload, len(parallel_rows[5]))
            connection = sqlite3.connect(os.path.join(two, "index.sqlite3"))
            try:
                self.assertEqual(
                    "2",
                    connection.execute(
                        "SELECT value FROM meta WHERE key = 'parallel_jobs'"
                    ).fetchone()[0],
                )
            finally:
                connection.close()

    def test_query_layer_boundary_is_structural_and_database_only(self):
        for package, filenames in (
                (("codewiki", "query"), ("symbols.py", "types.py", "calls.py", "sql.py")),
                (("codewiki", "store"), ("db.py",)),
        ):
            for filename in filenames:
                path = os.path.join(ROOT, *package, filename)
                with open(path, "r", encoding="utf-8") as stream:
                    tree = ast.parse(stream.read(), filename=path)

                imported_modules = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported_modules.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        if node.level == 0:
                            imported_modules.append(node.module or "")
                        else:
                            base_length = len(package) - (node.level - 1)
                            imported_modules.append(".".join(
                                list(package[:base_length])
                                + ([node.module] if node.module else [])
                            ))
                self.assertFalse(
                    any(module == "codewiki.index" or module.startswith("codewiki.index.")
                        for module in imported_modules),
                    (path, imported_modules),
                )
                if package == ("codewiki", "query"):
                    self.assertFalse(any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "open"
                        for node in ast.walk(tree)
                    ))


if __name__ == "__main__":
    unittest.main()
