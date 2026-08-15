from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

from codewiki.index import pipeline
from codewiki.query.sql import ColumnAccessResult, column_accesses


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


class ColumnSqlQueryTests(unittest.TestCase):
    def test_column_accesses_matches_casefolds_filters_and_unknown_columns(self):
        source = (
            "package p;\n"
            "class Repository {\n"
            "    void zed() {\n"
            "        String sql = \"UPDATE Orders SET Status = ?\";\n"
            "    }\n"
            "    void alpha() {\n"
            "        String sql = \"UPDATE ORDERS SET status = ?\";\n"
            "    }\n"
            "}\n"
        )
        reader = (
            "package p;\n"
            "class ZReader {\n"
            "    void read() {\n"
            "        String sql = \"SELECT STATUS FROM Orders\";\n"
            "    }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-column-query-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-column-query-out-") as out:
            write_file(root, "src/p/Repository.java", source)
            write_file(root, "src/p/ZReader.java", reader)
            result = pipeline.run(root, out, jobs=1)

            expected = [
                ColumnAccessResult(
                    "p.Repository.zed", "method", "src/p/Repository.java", 4,
                    "update", "Orders", "Status", "WRITE",
                    "UPDATE Orders SET Status = ?",
                ),
                ColumnAccessResult(
                    "p.Repository.alpha", "method", "src/p/Repository.java", 7,
                    "update", "ORDERS", "status", "WRITE",
                    "UPDATE ORDERS SET status = ?",
                ),
                ColumnAccessResult(
                    "p.ZReader.read", "method", "src/p/ZReader.java", 4,
                    "select", "Orders", "STATUS", "READ",
                    "SELECT STATUS FROM Orders",
                ),
            ]
            self.assertEqual(
                expected, column_accesses(result.db_path, "oRdErS", "sTaTuS")
            )
            self.assertEqual(
                expected[:2], column_accesses(
                    result.db_path, "ORDERS", "STATUS", "WRITE"
                )
            )
            self.assertEqual(
                expected[2:], column_accesses(
                    result.db_path, "orders", "status", "READ"
                )
            )
            self.assertEqual([], column_accesses(
                result.db_path, "orders", "not_indexed"
            ))
            self.assertEqual(
                {
                    "method_fqn": "p.Repository.zed",
                    "method_kind": "method",
                    "path": "src/p/Repository.java",
                    "line": 4,
                    "verb": "update",
                    "table_name": "Orders",
                    "column_name": "Status",
                    "access": "WRITE",
                    "statement": "UPDATE Orders SET Status = ?",
                },
                expected[0].as_dict(),
            )


class ColumnCliIntegrationTests(unittest.TestCase):
    def test_cli_index_then_column_json_write_limit_text_and_argument_error(self):
        long_statement = (
            "UPDATE HFJ_RESOURCE SET STATUS = ?, RES_VER = ?, "
            "RES_PARTITION_ID = ?, RES_DELETED_AT = ?, RES_UPDATED = ?, "
            "RES_TYPE = ? WHERE RES_ID = ? AND RES_VERSION = ?"
        )
        long_method_fqn = (
            "p.ResourceWriterWithAnExcessivelyLongName."
            "firstWithAnExcessivelyLongName"
        )
        long_resource_path = (
            "src/p/ResourceWriterWithAnExcessivelyLongName.java"
        )
        with tempfile.TemporaryDirectory(prefix="codewiki-column-cli-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-column-cli-out-") as out:
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
            write_file(
                root,
                "src/p/ZOrderReader.java",
                "package p;\n"
                "class ZOrderReader {\n"
                "    void findById() {\n"
                "        String sql = \"SELECT STATUS FROM ORDERS WHERE ID = ?\";\n"
                "    }\n"
                "}\n",
            )

            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            queried = run_cli("column", "ORDERS.STATUS", "--out", out, "--json")
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual(
                [
                    "table", "column", "access", "count", "truncated",
                    "read", "write", "results",
                ],
                list(payload.keys()),
            )
            self.assertEqual(
                {
                    "table": "ORDERS",
                    "column": "STATUS",
                    "access": None,
                    "count": 2,
                    "truncated": False,
                    "read": 1,
                    "write": 1,
                },
                {key: payload[key] for key in (
                    "table", "column", "access", "count", "truncated",
                    "read", "write",
                )},
            )
            self.assertEqual("WRITE", payload["results"][0]["access"])
            self.assertEqual("READ", payload["results"][1]["access"])
            self.assertEqual(
                "UPDATE ORDERS SET STATUS = ? WHERE ID = ?",
                payload["results"][0]["statement"],
            )

            write_only = run_cli(
                "column", "ORDERS.STATUS", "--out", out, "--write", "--json"
            )
            self.assertEqual(0, write_only.returncode, write_only.stderr)
            write_payload = json.loads(write_only.stdout)
            self.assertEqual("WRITE", write_payload["access"])
            self.assertEqual(1, write_payload["count"])
            self.assertEqual(0, write_payload["read"])
            self.assertEqual(1, write_payload["write"])
            self.assertEqual(["WRITE"], [
                item["access"] for item in write_payload["results"]
            ])

            limited = run_cli(
                "column", "HFJ_RESOURCE.STATUS", "--out", out, "--write",
                "--json", "--limit", "1",
            )
            self.assertEqual(0, limited.returncode, limited.stderr)
            limited_payload = json.loads(limited.stdout)
            self.assertEqual("HFJ_RESOURCE", limited_payload["table"])
            self.assertEqual("STATUS", limited_payload["column"])
            self.assertEqual(1, limited_payload["count"])
            self.assertTrue(limited_payload["truncated"])
            self.assertEqual(0, limited_payload["read"])
            self.assertEqual(1, limited_payload["write"])
            self.assertEqual(long_method_fqn, limited_payload["results"][0]["method_fqn"])
            self.assertEqual(long_statement, limited_payload["results"][0]["statement"])

            human = run_cli(
                "column", "HFJ_RESOURCE.STATUS", "--out", out, "--write",
                "--limit", "1",
            )
            self.assertEqual(0, human.returncode, human.stderr)
            human_lines = human.stdout.splitlines()
            self.assertTrue(human_lines[0].startswith(
                "WRITE  update  %s  %s:4  " % (
                    long_method_fqn, long_resource_path,
                )
            ))
            self.assertIn("  ".join(long_method_fqn.split()), human_lines[0])
            self.assertIn(long_statement[:100], human_lines[0])
            self.assertNotIn(long_statement[100:], human_lines[0])
            self.assertEqual("truncated: limit reached", human_lines[1])
            self.assertEqual("1 accesses (0 read, 1 write)", human_lines[2])

            invalid = run_cli("column", "ORDERS", "--out", out)
            self.assertEqual(2, invalid.returncode)
            self.assertIn("TABLE.COLUMN", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
