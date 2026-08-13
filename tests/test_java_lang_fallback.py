from __future__ import annotations

import unittest


class JavaLangFallbackTests(unittest.TestCase):
    PATH = "src/app/Use.java"

    def _type(self, fqn, package, path=None, name=None, owner_fqn=None):
        from codewiki.index.resolution import TypeInfo

        return TypeInfo(
            path or fqn.replace(".", "/") + ".java",
            name or fqn.rsplit(".", 1)[-1],
            fqn,
            package,
            owner_fqn,
        )

    def _wildcard_import(self, package):
        from codewiki.index.imports import ImportRecord

        return ImportRecord(
            self.PATH, 2, 1, "import %s.*;" % package, package,
            "wildcard", False, True,
        )

    def _single_import(self, fqn):
        from codewiki.index.imports import ImportRecord

        return ImportRecord(
            self.PATH, 2, 1, "import %s;" % fqn, fqn,
            "single", False, False,
        )

    def _resolve(self, name, types=(), imports=(), packages=(),
                 analyzable_packages=None, current_package="app"):
        from codewiki.index.resolution import build_lookup, resolve_type

        file_packages = {self.PATH: current_package}
        package_names = {current_package}
        package_names.update(item.package for item in types if item.package)
        package_names.update(packages)
        if analyzable_packages is None:
            analyzed = package_names
        else:
            analyzed = set(analyzable_packages)
        lookup = build_lookup(
            types, package_names, analyzable_packages=analyzed
        )
        imports_by_file = {self.PATH: list(imports)}
        return resolve_type(
            self.PATH, name, file_packages, types, imports_by_file, lookup=lookup
        )

    def test_missing_java_lang_type_after_analyzed_wildcard_is_external(self):
        result = self._resolve(
            "RuntimeException",
            types=[self._type("com.acme.Existing", "com.acme")],
            imports=[self._wildcard_import("com.acme")],
        )

        self.assertEqual("external", result.outcome)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(7, result.rule)
        self.assertEqual(
            ["java.lang.RuntimeException"], result.candidates
        )

    def test_missing_java_lang_type_without_import_is_external(self):
        result = self._resolve("RuntimeException")

        self.assertEqual("external", result.outcome)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(7, result.rule)
        self.assertEqual(
            ["java.lang.RuntimeException"], result.candidates
        )

    def test_same_package_package_shadows_java_lang_fallback(self):
        result = self._resolve(
            "Package",
            types=[self._type("com.acme.Package", "com.acme")],
            packages=["com.acme"],
            current_package="com.acme",
        )

        self.assertEqual("resolved", result.outcome)
        self.assertEqual("com.acme.Package", result.resolved_fqn)
        self.assertEqual(3, result.rule)
        self.assertEqual(["com.acme.Package"], result.candidates)

    def test_explicit_import_thread_shadows_java_lang_fallback(self):
        result = self._resolve(
            "Thread",
            types=[self._type("com.other.Thread", "com.other")],
            imports=[self._single_import("com.other.Thread")],
        )

        self.assertEqual("resolved", result.outcome)
        self.assertEqual("com.other.Thread", result.resolved_fqn)
        self.assertEqual(2, result.rule)
        self.assertEqual(["com.other.Thread"], result.candidates)
