from __future__ import annotations

import json
import os
import sqlite3
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


def supertype_rows(out):
    connection = sqlite3.connect(os.path.join(out, "index.sqlite3"))
    try:
        rows = connection.execute(
            "SELECT f.path, s.owner_fqn, s.line, s.relation, s.raw, s.name, "
            "s.target_fqn, s.rule, s.outcome, s.candidates "
            "FROM supertypes AS s JOIN files AS f USING(file_id) "
            "ORDER BY f.path, s.line, s.relation, s.raw"
        ).fetchall()
        return [row[:-1] + (json.loads(row[-1]),) for row in rows]
    finally:
        connection.close()


def meta_keys(out):
    connection = sqlite3.connect(os.path.join(out, "index.sqlite3"))
    try:
        return [row[0] for row in connection.execute(
            "SELECT key FROM meta ORDER BY key"
        )]
    finally:
        connection.close()


class JavaTypeHierarchyIntegrationTests(unittest.TestCase):
    def assert_indexed(self, root, out, jobs):
        result = run_cli(
            "index", root, "--out", out, "--jobs", str(jobs), "--quiet"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(
            os.path.isfile(os.path.join(out, "index.sqlite3")),
            result.stdout,
        )
        return result

    def test_cli_index_and_impls_keep_shortest_distance_and_stable_rows(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-hierarchy-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-hierarchy-out-one-") as out_one, \
                tempfile.TemporaryDirectory(prefix="codewiki-hierarchy-out-two-") as out_two:
            write_file(
                root,
                "src/hierarchy/Base.java",
                "package hierarchy;\n\npublic interface Base {}\n",
            )
            write_file(
                root,
                "src/hierarchy/Mid.java",
                "package hierarchy;\n\npublic interface Mid extends Base {}\n",
            )
            write_file(
                root,
                "src/hierarchy/Leaf.java",
                "package hierarchy;\n\n"
                "public interface Leaf extends\n"
                "        Mid,\n"
                "        Base {}\n",
            )
            write_file(
                root,
                "src/hierarchy/GrandLeaf.java",
                "package hierarchy;\n\n"
                "public class GrandLeaf implements Leaf {}\n",
            )

            first = self.assert_indexed(root, out_one, jobs=1)
            second = self.assert_indexed(root, out_two, jobs=2)

            self.assertIn("supertypes found: 4", first.stdout)
            self.assertIn("supertypes outcome resolved: 4", first.stdout)
            self.assertEqual(supertype_rows(out_one), supertype_rows(out_two))
            self.assertEqual(
                [
                    (
                        "src/hierarchy/GrandLeaf.java", "hierarchy.GrandLeaf", 3,
                        "implements", "Leaf", "Leaf", "hierarchy.Leaf", 3,
                        "resolved", ["hierarchy.Leaf"],
                    ),
                    (
                        "src/hierarchy/Leaf.java", "hierarchy.Leaf", 4,
                        "extends", "Mid", "Mid", "hierarchy.Mid", 3,
                        "resolved", ["hierarchy.Mid"],
                    ),
                    (
                        "src/hierarchy/Leaf.java", "hierarchy.Leaf", 5,
                        "extends", "Base", "Base", "hierarchy.Base", 3,
                        "resolved", ["hierarchy.Base"],
                    ),
                    (
                        "src/hierarchy/Mid.java", "hierarchy.Mid", 3,
                        "extends", "Base", "Base", "hierarchy.Base", 3,
                        "resolved", ["hierarchy.Base"],
                    ),
                ],
                supertype_rows(out_one),
            )
            for out in (out_one, out_two):
                keys = meta_keys(out)
                self.assertFalse(
                    set(keys).intersection({
                        "scan", "symbols", "imports", "supertypes", "persist", "total",
                    }),
                    keys,
                )

            queried = run_cli("impls", "hierarchy.Base", "--out", out_one)
            self.assertEqual(0, queried.returncode, queried.stderr)
            self.assertEqual(
                [
                    "hierarchy.Leaf interface 1 extends src/hierarchy/Leaf.java:3",
                    "hierarchy.Mid interface 1 extends src/hierarchy/Mid.java:3",
                    "hierarchy.GrandLeaf class 2 implements src/hierarchy/GrandLeaf.java:3",
                    "3 subtypes",
                ],
                queried.stdout.splitlines(),
            )
            self.assertEqual("", queried.stderr)

    def test_cli_index_resolves_supertype_that_shadows_java_lang(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-shadow-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-shadow-out-") as out:
            write_file(
                root,
                "src/shadow/Thread.java",
                "package shadow;\n\npublic class Thread {}\n",
            )
            write_file(
                root,
                "src/consumer/Child.java",
                "package consumer;\n\n"
                "import shadow.Thread;\n\n"
                "public class Child extends Thread {}\n",
            )

            indexed = self.assert_indexed(root, out, jobs=1)
            self.assertIn("supertypes outcome resolved: 1", indexed.stdout)
            self.assertEqual(
                [
                    (
                        "src/consumer/Child.java", "consumer.Child", 5,
                        "extends", "Thread", "Thread", "shadow.Thread", 2,
                        "resolved", ["shadow.Thread"],
                    ),
                ],
                supertype_rows(out),
            )

            queried = run_cli(
                "impls", "shadow.Thread", "--out", out, "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            self.assertEqual(
                {
                    "fqn": "shadow.Thread",
                    "direct": False,
                    "count": 1,
                    "truncated": False,
                    "results": [{
                        "fqn": "consumer.Child",
                        "kind": "class",
                        "path": "src/consumer/Child.java",
                        "line": 5,
                        "distance": 1,
                        "relation": "extends",
                    }],
                },
                json.loads(queried.stdout),
            )

    def test_cli_index_resolves_nested_type_from_another_package(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-nested-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-nested-out-") as out:
            write_file(
                root,
                "src/outer/Outer.java",
                "package outer;\n\n"
                "public class Outer {\n"
                "    public static class Inner {}\n"
                "}\n",
            )
            write_file(
                root,
                "src/consumer/Child.java",
                "package consumer;\n\n"
                "import outer.Outer;\n\n"
                "public class Child extends Outer.Inner {}\n",
            )

            indexed = self.assert_indexed(root, out, jobs=1)
            self.assertIn("supertypes outcome resolved: 1", indexed.stdout)
            self.assertEqual(
                [
                    (
                        "src/consumer/Child.java", "consumer.Child", 5,
                        "extends", "Outer.Inner", "Outer.Inner",
                        "outer.Outer.Inner", 6, "resolved",
                        ["outer.Outer.Inner"],
                    ),
                ],
                supertype_rows(out),
            )

            queried = run_cli(
                "impls", "outer.Outer.Inner", "--out", out, "--json"
            )
            self.assertEqual(0, queried.returncode, queried.stderr)
            payload = json.loads(queried.stdout)
            self.assertEqual("outer.Outer.Inner", payload["fqn"])
            self.assertEqual(1, payload["count"])
            self.assertEqual(
                {
                    "fqn": "consumer.Child",
                    "kind": "class",
                    "path": "src/consumer/Child.java",
                    "line": 5,
                    "distance": 1,
                    "relation": "extends",
                },
                payload["results"][0],
            )

    def test_cli_index_keeps_ambiguous_supertype_unresolved_with_candidates(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-ambiguous-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-ambiguous-out-") as out:
            write_file(
                root,
                "src/one/Duplicate.java",
                "package one;\n\npublic class Duplicate {}\n",
            )
            write_file(
                root,
                "src/two/Duplicate.java",
                "package two;\n\npublic class Duplicate {}\n",
            )
            write_file(
                root,
                "src/use/Child.java",
                "package use;\n\n"
                "import one.*;\n"
                "import two.*;\n\n"
                "public class Child extends Duplicate {}\n",
            )

            indexed = self.assert_indexed(root, out, jobs=1)
            self.assertIn("supertypes outcome unresolved: 1", indexed.stdout)
            self.assertIn("supertype resolution rate: 0.0%", indexed.stdout)
            self.assertEqual(
                [
                    (
                        "src/use/Child.java", "use.Child", 6,
                        "extends", "Duplicate", "Duplicate", None, 4,
                        "unresolved", ["one.Duplicate", "two.Duplicate"],
                    ),
                ],
                supertype_rows(out),
            )
            connection = sqlite3.connect(os.path.join(out, "index.sqlite3"))
            try:
                self.assertEqual(
                    0,
                    connection.execute(
                        "SELECT count(*) FROM supertypes AS st "
                        "LEFT JOIN symbols AS target ON target.fqn = st.target_fqn "
                        "WHERE st.outcome = 'resolved' AND target.fqn IS NULL"
                    ).fetchone()[0],
                )
            finally:
                connection.close()

    def test_cli_index_does_not_turn_type_like_noise_into_supertypes(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-noise-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-noise-out-") as out:
            write_file(
                root,
                "src/noise/Tag.java",
                "package noise;\n\npublic @interface Tag {}\n",
            )
            write_file(
                root,
                "src/noise/Bound.java",
                "package noise;\n\npublic class Bound {}\n",
            )
            write_file(
                root,
                "src/noise/ComponentType.java",
                "package noise;\n\npublic class ComponentType {}\n",
            )
            write_file(
                root,
                "src/noise/Marker.java",
                "package noise;\n\npublic interface Marker<T> {}\n",
            )
            write_file(
                root,
                "src/noise/PermitA.java",
                "package noise;\n\npublic final class PermitA {}\n",
            )
            write_file(
                root,
                "src/noise/PermitB.java",
                "package noise;\n\npublic final class PermitB {}\n",
            )
            write_file(
                root,
                "src/noise/Root.java",
                "package noise;\n\n"
                "@Tag\n"
                "public sealed interface Root<T extends Bound> permits PermitA, PermitB {\n"
                "    String text = \"extends Fake implements Missing\";\n"
                "    // extends AlsoMissing\n"
                "}\n",
            )
            write_file(
                root,
                "src/noise/Data.java",
                "package noise;\n\n"
                "@Tag\n"
                "public record Data<T extends Bound>(ComponentType component)\n"
                "        implements Marker<Bound>, java.io.Serializable {\n"
                "    String text = \"implements NotASupertype\";\n"
                "}\n",
            )
            write_file(
                root,
                "src/noise/Plain.java",
                "package noise;\n\n"
                "public class Plain {\n"
                "    // class Fake extends Missing\n"
                "    String value = \"implements Missing\";\n"
                "}\n",
            )

            indexed = self.assert_indexed(root, out, jobs=1)
            self.assertIn("supertypes found: 2", indexed.stdout)
            self.assertIn("supertypes outcome resolved: 1", indexed.stdout)
            self.assertIn("supertypes outcome external: 1", indexed.stdout)
            self.assertIn("supertype resolution rate: 100.0%", indexed.stdout)
            self.assertEqual(
                [
                    (
                        "src/noise/Data.java", "noise.Data", 5,
                        "implements", "Marker<Bound>", "Marker", "noise.Marker", 3,
                        "resolved", ["noise.Marker"],
                    ),
                    (
                        "src/noise/Data.java", "noise.Data", 5,
                        "implements", "java.io.Serializable", "java.io.Serializable",
                        None, None, "external", ["java.io.Serializable"],
                    ),
                ],
                supertype_rows(out),
            )

    def test_impls_json_miss_has_stable_shape_after_real_index(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-miss-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-miss-out-") as out:
            write_file(
                root,
                "src/demo/Base.java",
                "package demo;\n\npublic interface Base {}\n",
            )
            indexed = self.assert_indexed(root, out, jobs=1)
            self.assertIn("files scanned: 1", indexed.stdout)

            result = run_cli(
                "impls", "demo.DoesNotExist", "--out", out, "--json"
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stderr)
            self.assertEqual(
                {
                    "fqn": "demo.DoesNotExist",
                    "direct": False,
                    "count": 0,
                    "truncated": False,
                    "results": [],
                },
                json.loads(result.stdout),
            )


if __name__ == "__main__":
    unittest.main()
