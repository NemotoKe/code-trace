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


def write_five_subtype_hierarchy(root):
    write_file(root, "src/demo/Base.java", (
        "package demo;\n"
        "public interface Base {}\n"
    ))
    for number in range(1, 6):
        write_file(root, "src/demo/Sub%d.java" % number, (
            "package demo;\n"
            "public class Sub%d implements Base {}\n" % number
        ))


def write_eleven_subtype_hierarchy(root):
    write_file(root, "src/demo/Base.java", (
        "package demo;\n"
        "public interface Base {}\n"
    ))
    for number in range(1, 12):
        write_file(root, "src/demo/Sub%d.java" % number, (
            "package demo;\n"
            "public class Sub%d implements Base {}\n" % number
        ))


class ImplsCliTests(unittest.TestCase):
    def test_profile_controls_implementation_limit_and_explicit_override(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-profile-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-profile-out-") as out:
            write_eleven_subtype_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            default = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--json"
            ).stdout)
            detailed = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--profile", "detailed",
                "--json"
            ).stdout)
            normal = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--profile", "normal",
                "--json"
            ).stdout)
            normal_then_explicit = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--profile", "normal",
                "--implementation-limit", "12", "--json"
            ).stdout)
            explicit_then_normal = json.loads(run_cli(
                "impls", "demo.Base", "--out", out,
                "--implementation-limit", "12", "--profile", "normal", "--json"
            ).stdout)

            self.assertEqual(11, default["count"])
            self.assertFalse(default["truncated"])
            self.assertIsNone(default["truncation_reason"])
            self.assertIsNone(default["profile"])
            self.assertEqual(default["results"], detailed["results"])
            self.assertEqual("detailed", detailed["profile"])
            self.assertEqual(10, normal["count"])
            self.assertTrue(normal["truncated"])
            self.assertEqual("candidates", normal["truncation_reason"])
            self.assertEqual("normal", normal["profile"])
            self.assertEqual(11, normal_then_explicit["count"])
            self.assertFalse(normal_then_explicit["truncated"])
            self.assertIsNone(normal_then_explicit["truncation_reason"])
            self.assertEqual("normal", normal_then_explicit["profile"])
            self.assertEqual(
                normal_then_explicit["results"], explicit_then_normal["results"]
            )

    def test_normal_profile_does_not_truncate_a_small_subtype_graph(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-profile-small-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-profile-small-out-") as out:
            write_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            payload = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--profile", "normal",
                "--json"
            ).stdout)

            self.assertEqual("COMPLETE", payload["status"])
            self.assertFalse(payload["truncated"])
            self.assertIsNone(payload["truncation_reason"])

    def test_implementation_limit_bounds_search_and_precedes_display_limit(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-impls-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-impls-out-") as out:
            write_five_subtype_hierarchy(root)
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            unbounded = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--json"
            ).stdout)
            limited_result = run_cli(
                "impls", "demo.Base", "--out", out, "--json",
                "--implementation-limit", "3",
            )
            limited = json.loads(limited_result.stdout)
            boundary = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--json",
                "--implementation-limit", "5",
            ).stdout)
            zero = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--json",
                "--implementation-limit", "0",
            ).stdout)
            both = json.loads(run_cli(
                "impls", "demo.Base", "--out", out, "--json",
                "--implementation-limit", "3", "--limit", "1",
            ).stdout)
            human = run_cli(
                "impls", "demo.Base", "--out", out,
                "--implementation-limit", "3",
            )

            self.assertEqual(
                ["demo.Sub1", "demo.Sub2", "demo.Sub3", "demo.Sub4", "demo.Sub5"],
                [item["fqn"] for item in unbounded["results"]],
            )
            self.assertEqual(0, limited_result.returncode, limited_result.stderr)
            self.assertTrue(limited["truncated"])
            self.assertEqual("TRUNCATED", limited["status"])
            self.assertEqual("candidates", limited["truncation_reason"])
            self.assertEqual(
                ["demo.Sub1", "demo.Sub2", "demo.Sub3"],
                [item["fqn"] for item in limited["results"]],
            )
            self.assertFalse(boundary["truncated"])
            self.assertIsNone(boundary["truncation_reason"])
            self.assertEqual(unbounded["results"], boundary["results"])
            self.assertTrue(zero["truncated"])
            self.assertEqual("candidates", zero["truncation_reason"])
            self.assertEqual([], zero["results"])
            self.assertEqual(1, both["count"])
            self.assertTrue(both["truncated"])
            self.assertEqual("candidates", both["truncation_reason"])
            self.assertNotIn("truncated: limit reached", human.stdout)
            self.assertEqual("3 subtypes", human.stdout.splitlines()[-1])

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
                    "truncation_reason", "boundaries", "profile",
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
                    "profile": None,
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
