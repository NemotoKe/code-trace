from __future__ import annotations

import unittest


class JavaSupertypeResolutionTests(unittest.TestCase):
    PATH = "src/app/Use.java"

    def _ref(self, name):
        from codewiki.index.supertypes import SupertypeRef

        return SupertypeRef(self.PATH, "app.Use", 1, "extends", name, name)

    def _resolve(self, name, types=(), imports=(), packages=(),
                 analyzable_packages=None):
        from codewiki.index.resolution import build_lookup, resolve_supertype

        file_packages = {self.PATH: "app"}
        package_names = {"app"}
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
        return resolve_supertype(
            self._ref(name), file_packages, types, imports_by_file, lookup=lookup
        )

    def _type(self, fqn, package, path=None, name=None, owner_fqn=None):
        from codewiki.index.resolution import TypeInfo

        return TypeInfo(
            path or fqn.replace(".", "/") + ".java",
            name or fqn.rsplit(".", 1)[-1],
            fqn,
            package,
            owner_fqn,
        )

    def _single_import(self, fqn):
        from codewiki.index.imports import ImportRecord

        return ImportRecord(
            self.PATH, 1, 1, "import %s;" % fqn, fqn, "single", False, False
        )

    def _wildcard_import(self, package):
        from codewiki.index.imports import ImportRecord

        return ImportRecord(
            self.PATH, 1, 1, "import %s.*;" % package, package,
            "wildcard", False, True,
        )

    def test_already_qualified_fqn_resolves_with_rule_5(self):
        result = self._resolve(
            "com.acme.db.OrderDao",
            [self._type("com.acme.db.OrderDao", "com.acme.db")],
        )

        self.assertEqual("resolved", result.outcome)
        self.assertEqual(5, result.rule)
        self.assertEqual("com.acme.db.OrderDao", result.resolved_fqn)
        self.assertEqual(["com.acme.db.OrderDao"], result.candidates)

    def test_outer_qualified_nested_type_resolves_with_rule_6(self):
        result = self._resolve(
            "Outer.MyContext",
            [
                self._type("com.acme.Outer", "com.acme", name="Outer"),
                self._type(
                    "com.acme.Outer.MyContext", "com.acme",
                    name="MyContext", owner_fqn="com.acme.Outer",
                ),
            ],
            imports=[self._single_import("com.acme.Outer")],
        )

        self.assertEqual("resolved", result.outcome)
        self.assertEqual(6, result.rule)
        self.assertEqual("com.acme.Outer.MyContext", result.resolved_fqn)
        self.assertEqual(["com.acme.Outer.MyContext"], result.candidates)

    def test_rule_6_does_not_resolve_top_level_type_from_package_collision(self):
        result = self._resolve(
            "Outer.Inner",
            [
                self._type("p.Outer", "p", name="Outer"),
                self._type("p.Outer.Inner", "p.Outer", name="Inner"),
            ],
            imports=[self._single_import("p.Outer")],
        )

        self.assertEqual("unresolved", result.outcome)
        self.assertEqual(6, result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(["p.Outer.Inner"], result.candidates)

    def test_missing_nested_type_reports_constructed_candidate(self):
        result = self._resolve(
            "Outer.MyContext",
            [self._type("com.acme.Outer", "com.acme", name="Outer")],
            imports=[self._single_import("com.acme.Outer")],
        )

        self.assertEqual("unresolved", result.outcome)
        self.assertEqual(6, result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(["com.acme.Outer.MyContext"], result.candidates)

    def test_simple_name_is_exactly_existing_type_resolution(self):
        from codewiki.index.resolution import (
            build_lookup,
            resolve_type,
            resolve_supertype,
        )

        types = [self._type("com.acme.Base", "com.acme")]
        imports = [self._single_import("com.acme.Base")]
        file_packages = {self.PATH: "app"}
        lookup = build_lookup(
            types, ["app", "com.acme"],
            analyzable_packages=["app", "com.acme"],
        )
        imports_by_file = {self.PATH: imports}

        expected = resolve_type(
            self.PATH, "Base", file_packages, types, imports_by_file, lookup
        )
        actual = resolve_supertype(
            self._ref("Base"), file_packages, types, imports_by_file, lookup
        )

        self.assertEqual(expected, actual)
        self.assertEqual(expected.as_dict(), actual.as_dict())

    def test_missing_qualified_type_in_analyzed_package_is_unresolved(self):
        result = self._resolve(
            "com.acme.db.Missing",
            [self._type("com.acme.db.Present", "com.acme.db")],
        )

        self.assertEqual("unresolved", result.outcome)
        self.assertIsNone(result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(["com.acme.db.Missing"], result.candidates)

    def test_missing_qualified_type_without_repository_package_is_external(self):
        result = self._resolve("java.util.AbstractList")

        self.assertEqual("external", result.outcome)
        self.assertIsNone(result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(["java.util.AbstractList"], result.candidates)

    def test_missing_qualified_type_in_excluded_package_is_excluded(self):
        result = self._resolve(
            "com.acme.generated.Missing",
            packages=["com.acme.generated"],
            analyzable_packages=["app"],
        )

        self.assertEqual("excluded", result.outcome)
        self.assertIsNone(result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(["com.acme.generated.Missing"], result.candidates)

    def test_unresolved_outer_does_not_invent_a_nested_fqn(self):
        result = self._resolve("Outer.Inner")

        self.assertEqual("external", result.outcome)
        self.assertIsNone(result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(["Outer.Inner"], result.candidates)

    def test_ambiguous_outer_reports_qualified_candidates_as_unresolved(self):
        result = self._resolve(
            "Outer.Inner",
            [
                self._type("a.Outer", "a", name="Outer"),
                self._type(
                    "a.Outer.Inner", "a", name="Inner", owner_fqn="a.Outer",
                ),
                self._type("b.Outer", "b", name="Outer"),
                self._type(
                    "b.Outer.Inner", "b", name="Inner", owner_fqn="b.Outer",
                ),
            ],
            imports=[self._wildcard_import("a"), self._wildcard_import("b")],
        )

        self.assertEqual("unresolved", result.outcome)
        self.assertEqual(6, result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(
            ["a.Outer.Inner", "b.Outer.Inner"], result.candidates
        )

    def test_ambiguous_external_outer_reports_qualified_candidates_as_external(self):
        result = self._resolve(
            "Outer.Inner",
            imports=[
                self._wildcard_import("third.party.alpha"),
                self._wildcard_import("third.party.beta"),
            ],
        )

        self.assertEqual("external", result.outcome)
        self.assertEqual(6, result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(
            [
                "third.party.alpha.Outer.Inner",
                "third.party.beta.Outer.Inner",
            ],
            result.candidates,
        )

    def test_ambiguous_excluded_outer_reports_qualified_candidates_as_excluded(self):
        result = self._resolve(
            "Outer.Inner",
            imports=[
                self._wildcard_import("vendor.alpha"),
                self._wildcard_import("vendor.beta"),
            ],
            packages=["vendor.alpha", "vendor.beta"],
            analyzable_packages=["app"],
        )

        self.assertEqual("excluded", result.outcome)
        self.assertEqual(6, result.rule)
        self.assertIsNone(result.resolved_fqn)
        self.assertEqual(
            ["vendor.alpha.Outer.Inner", "vendor.beta.Outer.Inner"],
            result.candidates,
        )
