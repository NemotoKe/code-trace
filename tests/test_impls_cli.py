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


def write_hierarchy(root):
    write_file(root, "src/demo/Base.java", (
        "package demo;\n"
        "public interface Base {}\n"
    ))
    write_file(root, "src/demo/Mid.java", (
        "package demo;\n"
        "public interface Mid extends Base {}\n"
    ))
    write_file(root, "src/demo/Leaf.java", (
        "package demo;\n"
        "public class Leaf extends Mid {}\n"
    ))


class ImplsCliTests(unittest.TestCase):
    def test_json_status_distinguishes_complete_truncated_and_not_indexed(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-out-") as out:
            write_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            complete = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--json"
            ).stdout)
            truncated = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--json", "--limit", "0"
            ).stdout)
            absent = json.loads(run_cli(
                "impls", "demo.Absent", "--out", out, "--json", "--limit", "0"
            ).stdout)

            self.assertEqual("COMPLETE", complete["status"])
            self.assertIsNone(complete["truncation_reason"])
            self.assertEqual([], complete["boundaries"])
            self.assertEqual("TRUNCATED", truncated["status"])
            self.assertTrue(truncated["truncated"])
            self.assertEqual("limit", truncated["truncation_reason"])
            self.assertEqual([], truncated["boundaries"])
            self.assertEqual("NOT_INDEXED", absent["status"])
            self.assertFalse(absent["truncated"])
            self.assertIsNone(absent["truncation_reason"])
            self.assertEqual([], absent["boundaries"])

    def test_human_output_lists_ordered_subtypes_and_count(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-out-") as out:
            write_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            result = run_cli("impls", "demo.Base", "--out", out)

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "demo.Mid interface 1 extends src/demo/Mid.java:2",
                    "demo.Leaf class 2 extends src/demo/Leaf.java:2",
                    "2 subtypes",
                ],
                result.stdout.splitlines(),
            )
            self.assertEqual("", result.stderr)

    def test_direct_returns_only_distance_one_subtypes(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-out-") as out:
            write_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            result = run_cli(
                "impls", "demo.Base", "--out", out, "--direct"
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "demo.Mid interface 1 extends src/demo/Mid.java:2",
                    "1 subtypes",
                ],
                result.stdout.splitlines(),
            )

    def test_limit_keeps_nearest_results_and_reports_truncation(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-out-") as out:
            write_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            result = run_cli(
                "impls", "demo.Base", "--out", out, "--limit", "1"
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "demo.Mid interface 1 extends src/demo/Mid.java:2",
                    "truncated: limit reached",
                    "1 subtypes",
                ],
                result.stdout.splitlines(),
            )

    def test_json_output_has_stable_shape_and_truncation_metadata(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-out-") as out:
            write_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            result = run_cli(
                "impls", "demo.Base", "--out", out, "--json", "--limit", "1"
            )

            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                [
                    "fqn", "direct", "count", "truncated", "results", "status",
                    "truncation_reason", "boundaries",
                ],
                list(payload.keys()),
            )
            self.assertEqual("demo.Base", payload["fqn"])
            self.assertFalse(payload["direct"])
            self.assertEqual(1, payload["count"])
            self.assertTrue(payload["truncated"])
            self.assertEqual("TRUNCATED", payload["status"])
            self.assertEqual("limit", payload["truncation_reason"])
            self.assertEqual([], payload["boundaries"])
            self.assertEqual(
                {
                    "fqn": "demo.Mid",
                    "kind": "interface",
                    "path": "src/demo/Mid.java",
                    "line": 2,
                    "distance": 1,
                    "relation": "extends",
                },
                payload["results"][0],
            )

    def test_empty_result_is_success_in_human_and_json(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-out-") as out:
            write_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            human = run_cli("impls", "demo.NoSuchType", "--out", out)
            self.assertEqual(0, human.returncode, human.stderr)
            self.assertEqual(["0 subtypes"], human.stdout.splitlines())
            self.assertEqual("", human.stderr)

            encoded = run_cli(
                "impls", "demo.NoSuchType", "--out", out, "--json"
            )
            self.assertEqual(0, encoded.returncode, encoded.stderr)
            self.assertEqual(
                {
                    "fqn": "demo.NoSuchType",
                    "direct": False,
                    "count": 0,
                    "truncated": False,
                    "results": [],
                    "status": "NOT_INDEXED",
                    "truncation_reason": None,
                    "boundaries": [],
                },
                json.loads(encoded.stdout),
            )

    def test_missing_or_stale_index_uses_the_standard_error(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-missing-out-") as out:
            missing = run_cli(
                "impls", "demo.Base", "--out", out, "--json"
            )
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)
            self.assertIn("index database missing or stale", missing.stderr)
            self.assertIn("rerun index", missing.stderr)

        with tempfile.TemporaryDirectory(prefix="codewiki-impls-stale-out-") as out:
            write_file(out, "index.sqlite3", "not a sqlite database\n")
            stale = run_cli(
                "impls", "demo.Base", "--out", out, "--json"
            )
            self.assertEqual(2, stale.returncode)
            self.assertEqual("", stale.stdout)
            self.assertIn("index database missing or stale", stale.stderr)
            self.assertIn("rerun index", stale.stderr)


if __name__ == "__main__":
    unittest.main()
