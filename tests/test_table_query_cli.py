from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from codewiki.index import pipeline
from codewiki.query.sql import TableAccessResult, accesses


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


class SqlQueryTests(unittest.TestCase):
    def test_accesses_matches_casefolds_filters_and_orders_rows(self):
        source = (
            "package p;\n"
            "class Repository {\n"
            "    void zed() {\n"
            "        String first = \"SELECT * FROM HFJ_RESOURCE\";\n"
            "        String second = \"UPDATE hfj_resource SET STATUS = ?\";\n"
            "    }\n"
            "    void alpha() {\n"
            "        String third = \"INSERT INTO hFj_ReSoUrCe (ID) VALUES (?)\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-sql-query-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-sql-query-out-") as out:
            write_file(root, "src/p/Repository.java", source)
            result = pipeline.run(root, out, jobs=1)

            expected = [
                TableAccessResult(
                    "p.Repository.zed", "method", "src/p/Repository.java", 4,
                    "select", "HFJ_RESOURCE", "READ", "SELECT * FROM HFJ_RESOURCE",
                ),
                TableAccessResult(
                    "p.Repository.zed", "method", "src/p/Repository.java", 5,
                    "update", "hfj_resource", "WRITE",
                    "UPDATE hfj_resource SET STATUS = ?",
                ),
                TableAccessResult(
                    "p.Repository.alpha", "method", "src/p/Repository.java", 8,
                    "insert", "hFj_ReSoUrCe", "WRITE",
                    "INSERT INTO hFj_ReSoUrCe (ID) VALUES (?)",
                ),
            ]
            self.assertEqual(expected, accesses(result.db_path, "hFj_ReSoUrCe"))
            self.assertEqual(expected, accesses(result.db_path, "HFJ_RESOURCE"))
            self.assertEqual(
                [expected[0]], accesses(result.db_path, "hfj_resource", "READ")
            )
            self.assertEqual(
                expected[1:], accesses(result.db_path, "HFJ_RESOURCE", "WRITE")
            )
            self.assertEqual([], accesses(result.db_path, "not_in_the_index"))
            self.assertEqual(
                {
                    "method_fqn": "p.Repository.zed",
                    "method_kind": "method",
                    "path": "src/p/Repository.java",
                    "line": 4,
                    "verb": "select",
                    "table_name": "HFJ_RESOURCE",
                    "access": "READ",
                    "statement": "SELECT * FROM HFJ_RESOURCE",
                },
                expected[0].as_dict(),
            )


class TableCliIntegrationTests(unittest.TestCase):
    def test_cli_index_then_table_json_and_write_limit(self):
        long_statement = (
            "UPDATE HFJ_RESOURCE SET LAST_UPDATED = ?, RES_VER = ?, "
            "RES_DELETED_AT = ?, RES_PARTITION_ID = ? WHERE RES_ID = ? "
            "AND RES_UPDATED = ? AND RES_TYPE = ?"
        )
        long_method_fqn = (
            "p.ResourceWriterWithAnExcessivelyLongName."
            "firstWithAnExcessivelyLongName"
        )
        long_resource_path = "src/a/very/long/path/for/sql/ResourceWriter.java"
        with tempfile.TemporaryDirectory(prefix="codewiki-table-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-table-out-") as out:
            write_file(
                root,
                "src/p/OrderRepository.java",
                "package p;\n"
                "class OrderRepository {\n"
                "    void markPaid() {\n"
                "        String sql = \"UPDATE ORDERS SET STATUS = ? WHERE ID = ?\";\n"
                "    }\n"
                "}\n",
            )
            write_file(
                root,
                "src/p/OrderReader.java",
                "package p;\n"
                "class OrderReader {\n"
                "    void findById() {\n"
                "        String sql = \"SELECT * FROM Orders WHERE ID = ?\";\n"
                "    }\n"
                "}\n",
            )
            write_file(
                root,
                long_resource_path,
                "package p;\n"
                "class ResourceWriterWithAnExcessivelyLongName {\n"
                "    void firstWithAnExcessivelyLongName() {\n"
                "        String sql = \"%s\";\n"
                "    }\n"
                "    void second() {\n"
                "        String sql = \"UPDATE hfj_resource SET STATUS = ? WHERE ID = ?\";\n"
                "    }\n"
                "}\n" % long_statement,
            )

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("table", "ORDERS", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(
                [
                    "table", "access", "count", "truncated", "read", "write",
                    "results",
                ],
                list(payload.keys()),
            )
            self.assertEqual(
                {
                    "table": "ORDERS",
                    "access": None,
                    "count": 2,
                    "truncated": False,
                    "read": 1,
                    "write": 1,
                },
                {key: payload[key] for key in (
                    "table", "access", "count", "truncated", "read", "write",
                )},
            )
            self.assertEqual(
                {
                    "method_fqn": "p.OrderReader.findById",
                    "method_kind": "method",
                    "path": "src/p/OrderReader.java",
                    "line": 4,
                    "verb": "select",
                    "table_name": "Orders",
                    "access": "READ",
                    "statement": "SELECT * FROM Orders WHERE ID = ?",
                },
                payload["results"][0],
            )
            self.assertEqual(
                {
                    "method_fqn": "p.OrderRepository.markPaid",
                    "method_kind": "method",
                    "path": "src/p/OrderRepository.java",
                    "line": 4,
                    "verb": "update",
                    "table_name": "ORDERS",
                    "access": "WRITE",
                    "statement": "UPDATE ORDERS SET STATUS = ? WHERE ID = ?",
                },
                payload["results"][1],
            )

            limited = run_cli(
                "table", "hFj_ReSoUrCe", "--out", out, "--write", "--json",
                "--limit", "1",
            )
            self.assertEqual(0, limited.returncode, limited.stderr)
            limited_payload = json.loads(limited.stdout)
            self.assertEqual("hFj_ReSoUrCe", limited_payload["table"])
            self.assertEqual("WRITE", limited_payload["access"])
            self.assertEqual(1, limited_payload["count"])
            self.assertTrue(limited_payload["truncated"])
            self.assertEqual(0, limited_payload["read"])
            self.assertEqual(1, limited_payload["write"])
            self.assertEqual(long_statement, limited_payload["results"][0]["statement"])

            human = run_cli(
                "table", "HFJ_RESOURCE", "--out", out, "--write", "--limit", "1"
            )
            self.assertEqual(0, human.returncode, human.stderr)
            human_lines = human.stdout.splitlines()
            self.assertIn(
                long_method_fqn + "  " + long_resource_path + ":4  ",
                human_lines[0],
            )
            self.assertIn(long_statement[:100], human_lines[0])
            self.assertNotIn(long_statement[100:], human_lines[0])
            self.assertEqual("truncated: limit reached", human_lines[1])
            self.assertEqual("1 accesses (0 read, 1 write)", human_lines[2])

            invalid = run_cli(
                "table", "ORDERS", "--out", out, "--read", "--write"
            )
            self.assertEqual(2, invalid.returncode)
            self.assertIn("not allowed with argument", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
