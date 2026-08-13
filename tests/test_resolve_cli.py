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


class ResolveTypeCliTests(unittest.TestCase):
    def test_human_and_json_resolve_type_outputs_are_stable(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-cli-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-cli-out-") as out:
            write_file(root, "src/p/Type.java", "package p;\npublic class Type {}\n")
            write_file(root, "src/app/Use.java", (
                "package app;\nimport p.Type;\npublic class Use {}\n"
            ))
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            self.assertIn("imports form single: 1", indexed.stdout)
            self.assertIn("imports outcome resolved: 1", indexed.stdout)
            self.assertIn("imports outcome excluded: 0", indexed.stdout)
            self.assertIn("internal resolution rate: 100.0%", indexed.stdout)

            human = run_cli(
                "resolve-type", "Type", "--from", "src/app/Use.java", "--out", out
            )
            self.assertEqual(0, human.returncode, human.stderr)
            self.assertIn("resolved FQN: p.Type", human.stdout)
            self.assertIn("rule: 2", human.stdout)
            self.assertIn("outcome: resolved", human.stdout)

            encoded = run_cli(
                "resolve-type", "Type", "--from", "src/app/Use.java",
                "--out", out, "--json",
            )
            self.assertEqual(0, encoded.returncode, encoded.stderr)
            self.assertEqual(
                {
                    "file", "name", "resolved_fqn", "rule", "outcome", "candidates"
                },
                set(json.loads(encoded.stdout)),
            )
            payload = json.loads(encoded.stdout)
            self.assertEqual("p.Type", payload["resolved_fqn"])
            self.assertEqual(2, payload["rule"])
            self.assertEqual("resolved", payload["outcome"])

    def test_cli_reports_ambiguity_external_unresolved_and_no_match_without_error(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-cli-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-cli-out-") as out:
            write_file(root, "src/p/one/Dup.java", "package p.one;\npublic class Dup {}\n")
            write_file(root, "src/p/two/Dup.java", "package p.two;\npublic class Dup {}\n")
            write_file(root, "src/p/missing/Marker.java", "package p.missing;\npublic class Marker {}\n")
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import p.one.*;\n"
                "import p.two.*;\n"
                "import java.util.List;\n"
                "import p.missing.Missing;\n"
                "public class Use {}\n"
            ))
            self.assertEqual(0, run_cli("index", root, "--out", out, "--quiet").returncode)

            ambiguous = run_cli(
                "resolve-type", "Dup", "--from", "src/app/Use.java", "--out", out
            )
            self.assertEqual(0, ambiguous.returncode, ambiguous.stderr)
            self.assertIn("outcome: unresolved", ambiguous.stdout)
            self.assertIn("candidate: p.one.Dup", ambiguous.stdout)
            self.assertIn("candidate: p.two.Dup", ambiguous.stdout)

            external = run_cli(
                "resolve-type", "List", "--from", "src/app/Use.java", "--out", out,
                "--json",
            )
            self.assertEqual(0, external.returncode, external.stderr)
            self.assertEqual("external", json.loads(external.stdout)["outcome"])

            unresolved = run_cli(
                "resolve-type", "Missing", "--from", "src/app/Use.java", "--out", out,
                "--json",
            )
            self.assertEqual(0, unresolved.returncode, unresolved.stderr)
            self.assertEqual("unresolved", json.loads(unresolved.stdout)["outcome"])

            no_match = run_cli(
                "resolve-type", "NoSuchType", "--from", "src/app/Use.java", "--out", out,
                "--json",
            )
            self.assertEqual(0, no_match.returncode, no_match.stderr)
            self.assertEqual([], json.loads(no_match.stdout)["candidates"])

    def test_cli_resolves_missing_java_lang_name_without_a_persisted_row(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-cli-java-lang-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-cli-java-lang-out-") as out:
            write_file(root, "src/app/Use.java", "package app;\npublic class Use {}\n")
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            human = run_cli(
                "resolve-type", "String", "--from", "src/app/Use.java", "--out", out
            )
            self.assertEqual(0, human.returncode, human.stderr)
            self.assertIn("resolved FQN: absent", human.stdout)
            self.assertIn("rule: 7", human.stdout)
            self.assertIn("outcome: external", human.stdout)
            self.assertIn("candidate: java.lang.String", human.stdout)

            encoded = run_cli(
                "resolve-type", "String", "--from", "src/app/Use.java",
                "--out", out, "--json",
            )
            self.assertEqual(0, encoded.returncode, encoded.stderr)
            payload = json.loads(encoded.stdout)
            self.assertEqual(
                {
                    "file", "name", "resolved_fqn", "rule", "outcome", "candidates"
                },
                set(payload),
            )
            self.assertEqual("src/app/Use.java", payload["file"])
            self.assertEqual("String", payload["name"])
            self.assertIsNone(payload["resolved_fqn"])
            self.assertEqual(7, payload["rule"])
            self.assertEqual("external", payload["outcome"])
            self.assertEqual(["java.lang.String"], payload["candidates"])

    def test_cli_repository_type_shadows_java_lang_fallback(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-cli-shadow-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-cli-shadow-out-") as out:
            write_file(root, "src/app/String.java", "package app;\npublic class String {}\n")
            write_file(root, "src/app/Use.java", "package app;\npublic class Use {}\n")
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)

            human = run_cli(
                "resolve-type", "String", "--from", "src/app/Use.java", "--out", out
            )
            self.assertEqual(0, human.returncode, human.stderr)
            self.assertIn("resolved FQN: app.String", human.stdout)
            self.assertIn("rule: 3", human.stdout)
            self.assertIn("outcome: resolved", human.stdout)
            self.assertIn("candidate: app.String", human.stdout)

            encoded = run_cli(
                "resolve-type", "String", "--from", "src/app/Use.java",
                "--out", out, "--json",
            )
            self.assertEqual(0, encoded.returncode, encoded.stderr)
            payload = json.loads(encoded.stdout)
            self.assertEqual("app.String", payload["resolved_fqn"])
            self.assertEqual(3, payload["rule"])
            self.assertEqual("resolved", payload["outcome"])
            self.assertEqual(["app.String"], payload["candidates"])

    def test_cli_reports_all_four_import_outcomes(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-cli-imports-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-cli-imports-out-") as out:
            write_file(root, "src/p/Type.java", "package p;\npublic class Type {}\n")
            write_file(root, "generated/Thing.java", (
                "// Code generated by fixture\n"
                "package generated;\npublic class Thing {}\n"
            ))
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import p.Type;\n"
                "import p.Missing;\n"
                "import java.util.List;\n"
                "import generated.Thing;\n"
                "public class Use {}\n"
            ))
            indexed = run_cli("index", root, "--out", out, "--quiet")
            self.assertEqual(0, indexed.returncode, indexed.stderr)
            for outcome in ("resolved", "unresolved", "external", "excluded"):
                self.assertIn("imports outcome %s: 1" % outcome, indexed.stdout)
            self.assertIn("internal resolution rate: 50.0%", indexed.stdout)

    def test_cli_invalid_file_and_missing_database_are_actionable_errors(self):
        with tempfile.TemporaryDirectory(prefix="codewiki-cli-out-") as out:
            missing = run_cli(
                "resolve-type", "Type", "--from", "Use.java", "--out", out, "--json"
            )
            self.assertEqual(2, missing.returncode)
            self.assertEqual("", missing.stdout)
            self.assertIn("rerun index", missing.stderr.lower())

        with tempfile.TemporaryDirectory(prefix="codewiki-cli-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-cli-out-") as out:
            write_file(root, "Use.java", "package p;\npublic class Use {}\n")
            self.assertEqual(0, run_cli("index", root, "--out", out, "--quiet").returncode)
            invalid = run_cli(
                "resolve-type", "Type", "--from", "Missing.java", "--out", out, "--json"
            )
            self.assertEqual(2, invalid.returncode)
            self.assertEqual("", invalid.stdout)
            self.assertIn("not present in index", invalid.stderr)


if __name__ == "__main__":
    unittest.main()
