from __future__ import annotations

from collections import defaultdict
import unittest


class JavaCallGraphTests(unittest.TestCase):
    PATH = "src/Use.java"

    def _analyze(self, source):
        return self._analyze_files(((self.PATH, source),))

    def _analyze_files(self, files):
        from codewiki.index.calls import extract as extract_calls
        from codewiki.index.declarations import extract as extract_declarations
        from codewiki.index.imports import parse_imports
        from codewiki.index.resolution import (
            build_lookup, resolve_supertype, type_infos,
        )
        from codewiki.index.supertypes import extract as extract_supertypes
        from codewiki.index.symbols import extract as extract_symbols
        from codewiki.index.symbols import package_of

        all_symbols = []
        declarations = []
        sites = []
        file_packages = {}
        imports_by_file = {}
        for path, source in files:
            symbols = extract_symbols(path, "java", source)
            all_symbols.extend(symbols)
            declarations.extend(
                extract_declarations(path, "java", source, symbols)
            )
            sites.extend(extract_calls(path, "java", source, symbols))
            file_packages[path] = package_of(source)
            imports_by_file[path] = parse_imports(path, source)

        types = type_infos(all_symbols)
        lookup = build_lookup(
            types,
            file_packages.values(),
            analyzable_packages=file_packages.values(),
        )
        supertypes_by_owner = defaultdict(list)
        for path, source in files:
            symbols = [item for item in all_symbols if item.path == path]
            for ref in extract_supertypes(path, "java", source, symbols):
                resolved = resolve_supertype(
                    ref, file_packages, types, imports_by_file, lookup=lookup,
                )
                if resolved.outcome == "resolved" and resolved.resolved_fqn is not None:
                    supertypes_by_owner[ref.owner_fqn].append(
                        resolved.resolved_fqn
                    )
        members_by_owner = defaultdict(list)
        fields_by_owner = defaultdict(list)
        for symbol in all_symbols:
            if symbol.owner_fqn and symbol.kind == "method":
                members_by_owner[symbol.owner_fqn].append(symbol)
        for declaration in declarations:
            if declaration.kind == "field":
                fields_by_owner[declaration.scope_fqn].append(declaration)
        return (
            sites,
            declarations,
            file_packages,
            types,
            imports_by_file,
            lookup,
            dict(members_by_owner),
            dict(fields_by_owner),
            {
                owner: tuple(ancestors)
                for owner, ancestors in supertypes_by_owner.items()
            },
        )

    def _resolve_receivers(self, source):
        return self._resolve_files(((self.PATH, source),))

    def _resolve_files(self, files):
        from codewiki.index.callgraph import resolve_receiver_call

        (
            sites,
            declarations,
            file_packages,
            types,
            imports_by_file,
            lookup,
            members_by_owner,
            fields_by_owner,
            supertypes_by_owner,
        ) = self._analyze_files(files)
        resolved = []
        for site in sites:
            if site.form != "receiver":
                continue
            resolved.append(resolve_receiver_call(
                site, declarations, file_packages, types,
                imports_by_file, lookup, members_by_owner,
                supertypes_by_owner, fields_by_owner,
            ))
        return resolved, declarations

    def test_local_shadows_inherited_field(self):
        files = (
            (
                "src/p/A.java",
                "package p;\n"
                "class A { BaseDao dao; }\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A {\n"
                "    void run() {\n"
                "        LocalDao dao = null;\n"
                "        dao.save();\n"
                "    }\n"
                "}\n",
            ),
            (
                "src/p/BaseDao.java",
                "package p;\n"
                "class BaseDao { void save() {} }\n",
            ),
            (
                "src/p/LocalDao.java",
                "package p;\n"
                "class LocalDao { void save() {} }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            ("p.LocalDao", ("p.LocalDao.save",), "single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].reason,
            ),
        )

    def test_nearer_field_wins_over_inherited_field(self):
        files = (
            (
                "src/p/A.java",
                "package p;\n"
                "class A { BaseDao dao; }\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A {\n"
                "    ChildDao dao;\n"
                "    void run() { dao.save(); }\n"
                "}\n",
            ),
            (
                "src/p/BaseDao.java",
                "package p;\n"
                "class BaseDao { void save() {} }\n",
            ),
            (
                "src/p/ChildDao.java",
                "package p;\n"
                "class ChildDao { void save() {} }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            ("p.ChildDao", ("p.ChildDao.save",), "single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].reason,
            ),
        )

    def test_inherited_field_resolves_from_another_file(self):
        files = (
            (
                "src/base/A.java",
                "package base;\n"
                "import dep.Dao;\n"
                "public class A { Dao dao; }\n",
            ),
            (
                "src/sub/B.java",
                "package sub;\n"
                "import base.A;\n"
                "public class B extends A {\n"
                "    void run() { dao.save(); }\n"
                "}\n",
            ),
            (
                "src/dep/Dao.java",
                "package dep;\n"
                "public class Dao { void save() {} }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            ("dep.Dao", ("dep.Dao.save",), "CONFIRMED", "inherited_field_single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_nearest_ancestor_field_level_wins_without_merging(self):
        files = (
            (
                "src/p/Grand.java",
                "package p;\n"
                "class Grand { GrandDao dao; }\n",
            ),
            (
                "src/p/A.java",
                "package p;\n"
                "class A extends Grand { BaseDao dao; }\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A { void run() { dao.save(); } }\n",
            ),
            (
                "src/p/BaseDao.java",
                "package p;\n"
                "class BaseDao { void save() {} }\n",
            ),
            (
                "src/p/GrandDao.java",
                "package p;\n"
                "class GrandDao { void save() {} }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            ("p.BaseDao", ("p.BaseDao.save",), "inherited_field_single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].reason,
            ),
        )

    def test_inherited_field_with_overloaded_member_is_possible(self):
        files = (
            (
                "src/p/A.java",
                "package p;\n"
                "class A { Dao dao; }\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A { void run() { dao.save(); } }\n",
            ),
            (
                "src/p/Dao.java",
                "package p;\n"
                "class Dao {\n"
                "    void save() {}\n"
                "    void save(int value) {}\n"
                "}\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            ("p.Dao", ("p.Dao.save",), "POSSIBLE", "inherited_field_overloaded"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_inherited_field_with_absent_member_is_unresolved(self):
        files = (
            (
                "src/p/A.java",
                "package p;\n"
                "class A { Dao dao; }\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A { void run() { dao.missing(); } }\n",
            ),
            (
                "src/p/Dao.java",
                "package p;\n"
                "class Dao { void save() {} }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            ("p.Dao", (), "UNRESOLVED", "inherited_field_member_absent"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_inherited_field_with_unresolved_type_is_unresolved(self):
        files = (
            (
                "src/p/A.java",
                "package p;\n"
                "class A { MissingDao dao; }\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A { void run() { dao.save(); } }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            (None, (), "UNRESOLVED", "inherited_field_type_unresolved"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_no_ancestor_field_stays_no_declaration(self):
        files = (
            (
                "src/p/A.java",
                "package p;\n"
                "class A {}\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A { void run() { dao.save(); } }\n",
            ),
            (
                "src/p/Dao.java",
                "package p;\n"
                "class Dao { void save() {} }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            (None, (), "UNRESOLVED", "no_declaration"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_inherited_field_type_uses_inherited_member_walk(self):
        files = (
            (
                "src/p/A.java",
                "package p;\n"
                "class A { Dao dao; }\n",
            ),
            (
                "src/p/B.java",
                "package p;\n"
                "class B extends A { void run() { dao.save(); } }\n",
            ),
            (
                "src/p/Dao.java",
                "package p;\n"
                "class Dao extends BaseDao {}\n",
            ),
            (
                "src/p/BaseDao.java",
                "package p;\n"
                "class BaseDao { void save() {} }\n",
            ),
        )

        resolutions, _declarations = self._resolve_files(files)

        self.assertEqual(
            ("p.Dao", ("p.BaseDao.save",), "CONFIRMED", "inherited_field_single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_field_then_local_shadowing_chooses_the_visible_declaration(self):
        source = (
            "package p;\n"
            "class T {\n"
            "    private FieldDao dao;\n"
            "    void m() {\n"
            "        dao.save(\"a\");\n"
            "        LocalDao dao = other();\n"
            "        dao.save(\"b\");\n"
            "    }\n"
            "}\n"
            "class FieldDao { void save(String value) {} }\n"
            "class LocalDao { void save(String value) {} }\n"
        )

        resolutions, declarations = self._resolve_receivers(source)

        self.assertEqual(
            [("field", "FieldDao", 3), ("local", "LocalDao", 6)],
            [
                (item.kind, item.type_name, item.line)
                for item in declarations
                if item.name == "dao"
            ],
        )
        self.assertEqual(
            [(5, "p.FieldDao", ("p.FieldDao.save",)),
             (7, "p.LocalDao", ("p.LocalDao.save",))],
            [
                (item.site.line, item.owner_fqn, item.targets)
                for item in resolutions
            ],
        )

    def test_latest_same_name_local_before_call_wins(self):
        source = (
            "package p;\n"
            "class Caller {\n"
            "    void run() {\n"
            "        {\n"
            "            FirstDao dao = null;\n"
            "            dao.save();\n"
            "        }\n"
            "        {\n"
            "            SecondDao dao = null;\n"
            "            dao.save();\n"
            "        }\n"
            "    }\n"
            "}\n"
            "class FirstDao { void save() {} }\n"
            "class SecondDao { void save() {} }\n"
        )

        resolutions, declarations = self._resolve_receivers(source)

        self.assertEqual(
            [("FirstDao", 5), ("SecondDao", 9)],
            [
                (item.type_name, item.line)
                for item in declarations
                if item.name == "dao"
            ],
        )
        self.assertEqual(
            [(6, "p.FirstDao"), (10, "p.SecondDao")],
            [(item.site.line, item.owner_fqn) for item in resolutions],
        )

    def test_non_receiver_site_stays_unresolved(self):
        source = (
            "package p;\n"
            "class Caller { void run(Dao dao) { dao.save(); } }\n"
            "class Dao { void save() {} }\n"
        )
        from codewiki.index.callgraph import resolve_receiver_call
        from codewiki.index.calls import CallSite

        (
            _sites,
            _declarations,
            file_packages,
            types,
            imports_by_file,
            lookup,
            members_by_owner,
            _fields_by_owner,
            _supertypes_by_owner,
        ) = self._analyze(source)
        site = CallSite(
            self.PATH, "p.Caller.run", "method", 2,
            "bare", "dao", "save",
        )

        result = resolve_receiver_call(
            site, _declarations, file_packages, types,
            imports_by_file, lookup, members_by_owner,
        )

        self.assertEqual(None, result.owner_fqn)
        self.assertEqual((), result.targets)
        self.assertEqual("UNRESOLVED", result.confidence)
        self.assertEqual("no_declaration", result.reason)

    def test_appended_field_refreshes_declaration_index(self):
        source = (
            "package p;\n"
            "class Caller {\n"
            "    void run() { dao.save(); }\n"
            "}\n"
            "class Dao { void save() {} }\n"
        )
        from codewiki.index.callgraph import resolve_receiver_call
        from codewiki.index.declarations import Declaration

        (
            sites,
            declarations,
            file_packages,
            types,
            imports_by_file,
            lookup,
            members_by_owner,
            _fields_by_owner,
            _supertypes_by_owner,
        ) = self._analyze(source)
        site = next(item for item in sites if item.form == "receiver")

        before = resolve_receiver_call(
            site, declarations, file_packages, types,
            imports_by_file, lookup, members_by_owner,
        )
        declarations.append(Declaration(
            self.PATH, "p.Caller", "class", "dao", "Dao", 1, "field",
        ))
        after = resolve_receiver_call(
            site, declarations, file_packages, types,
            imports_by_file, lookup, members_by_owner,
        )

        self.assertEqual((None, (), "no_declaration"),
                         (before.owner_fqn, before.targets, before.reason))
        self.assertEqual("p.Dao", after.owner_fqn)
        self.assertEqual(("p.Dao.save",), after.targets)

    def test_field_can_be_declared_after_the_method(self):
        source = (
            "package p;\n"
            "class T {\n"
            "    void m() { dao.save(); }\n"
            "    FieldDao dao;\n"
            "}\n"
            "class FieldDao { void save() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual("p.FieldDao", resolutions[0].owner_fqn)
        self.assertEqual("single_member", resolutions[0].reason)

    def test_outer_field_is_used_when_inner_type_has_no_field(self):
        source = (
            "package p;\n"
            "class Outer {\n"
            "    OuterDao dao;\n"
            "    class Inner {\n"
            "        void run() { dao.save(); }\n"
            "    }\n"
            "}\n"
            "class OuterDao { void save() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual("p.Outer.Inner.run", resolutions[0].site.enclosing_fqn)
        self.assertEqual("p.OuterDao", resolutions[0].owner_fqn)
        self.assertEqual(("p.OuterDao.save",), resolutions[0].targets)

    def test_method_name_matching_nested_type_uses_actual_enclosing_type(self):
        source = (
            "package p;\n"
            "class Outer {\n"
            "    OuterDao dao;\n"
            "    class Inner {\n"
            "        InnerDao dao;\n"
            "    }\n"
            "    void Inner() { dao.save(); }\n"
            "}\n"
            "class OuterDao { void save() {} }\n"
            "class InnerDao { void save() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual("method", resolutions[0].site.enclosing_kind)
        self.assertEqual("p.OuterDao", resolutions[0].owner_fqn)
        self.assertEqual(("p.OuterDao.save",), resolutions[0].targets)

    def test_single_member_is_confirmed(self):
        source = (
            "package p;\n"
            "class Caller { void run(Dao dao) { dao.save(); } }\n"
            "class Dao { void save() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.Dao", ("p.Dao.save",), "CONFIRMED", "single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_overloaded_members_are_possible_with_distinct_targets(self):
        source = (
            "package p;\n"
            "class Caller { void run(Dao dao) { dao.cancel(); } }\n"
            "class Dao {\n"
            "    void cancel(String value) {}\n"
            "    void cancel(String value, int reason) {}\n"
            "}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual("p.Dao", resolutions[0].owner_fqn)
        self.assertEqual(("p.Dao.cancel",), resolutions[0].targets)
        self.assertEqual("POSSIBLE", resolutions[0].confidence)
        self.assertEqual("overloaded", resolutions[0].reason)

    def test_inherited_single_member_is_confirmed(self):
        source = (
            "package p;\n"
            "class Caller { void run(C value) { value.run(); } }\n"
            "class A { void run() {} }\n"
            "class B extends A {}\n"
            "class C extends B {}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.C", ("p.A.run",), "CONFIRMED", "inherited_single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_same_nearest_ancestor_level_collects_all_members(self):
        source = (
            "package p;\n"
            "class Caller { void run(C value) { value.run(); } }\n"
            "interface L { void run(); }\n"
            "interface R { void run(); }\n"
            "class C implements L, R {}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            (
                "p.C",
                ("p.L.run", "p.R.run"),
                "POSSIBLE",
                "inherited_overloaded",
            ),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_inherited_overloaded_members_are_possible_with_deduplicated_targets(self):
        source = (
            "package p;\n"
            "class Caller { void run(B value) { value.run(); } }\n"
            "class A {\n"
            "    void run() {}\n"
            "    void run(int value) {}\n"
            "}\n"
            "class B extends A {}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.B", ("p.A.run",), "POSSIBLE", "inherited_overloaded"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_owner_override_wins_over_an_inherited_member(self):
        source = (
            "package p;\n"
            "class Caller { void run(B value) { value.run(); } }\n"
            "class A { void run() {} }\n"
            "class B extends A { void run() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.B", ("p.B.run",), "CONFIRMED", "single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_nearest_ancestor_level_wins_without_merging_candidates(self):
        source = (
            "package p;\n"
            "class Caller { void run(C value) { value.run(); } }\n"
            "class A { void run() {} }\n"
            "class B extends A {\n"
            "    void run() {}\n"
            "    void run(int value) {}\n"
            "}\n"
            "class C extends B {}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.C", ("p.B.run",), "POSSIBLE", "inherited_overloaded"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_resolved_owner_without_member_is_unresolved(self):
        source = (
            "package p;\n"
            "class Caller { void run(Dao dao) { dao.missing(); } }\n"
            "class Dao { void save() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.Dao", (), "UNRESOLVED", "member_absent"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_unresolved_type_has_no_owner_or_targets(self):
        source = (
            "package p;\n"
            "class Caller { void run(MissingDao dao) { dao.save(); } }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            (None, (), "UNRESOLVED", "type_unresolved"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_missing_declaration_is_unresolved(self):
        source = (
            "package p;\n"
            "class Caller { void run() { dao.save(); } }\n"
            "class Dao { void save() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            (None, (), "UNRESOLVED", "no_declaration"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_type_receiver_with_one_member_is_confirmed_as_static(self):
        source = (
            "package p;\n"
            "class Caller { void run() { helper.help(); } }\n"
            "class helper { void help() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.helper", ("p.helper.help",), "CONFIRMED", "static_single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_type_receiver_with_overloaded_members_is_possible(self):
        source = (
            "package p;\n"
            "class Caller { void run() { helper.help(); } }\n"
            "class helper {\n"
            "    void help() {}\n"
            "    void help(int value) {}\n"
            "}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.helper", ("p.helper.help",), "POSSIBLE", "static_overloaded"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_type_receiver_without_member_is_unresolved(self):
        source = (
            "package p;\n"
            "class Caller { void run() { helper.missing(); } }\n"
            "class helper { void help() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.helper", (), "UNRESOLVED", "static_member_absent"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_static_inherited_single_member_is_confirmed(self):
        source = (
            "package p;\n"
            "class Caller { void run() { B.help(); } }\n"
            "class A { static void help() {} }\n"
            "class B extends A {}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.B", ("p.A.help",), "CONFIRMED", "static_inherited_single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_static_inherited_overloaded_members_are_possible_with_deduplicated_targets(self):
        source = (
            "package p;\n"
            "class Caller { void run() { B.help(); } }\n"
            "class A {\n"
            "    static void help() {}\n"
            "    static void help(int value) {}\n"
            "}\n"
            "class B extends A {}\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.B", ("p.A.help",), "POSSIBLE", "static_inherited_overloaded"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_iter_ancestors_yields_nearest_and_deeper_levels(self):
        from codewiki.index.callgraph import iter_ancestors

        supertypes_by_owner = {
            "p.Start": ("p.Near",),
            "p.Near": ("p.Far",),
        }

        self.assertEqual(
            [("p.Near",), ("p.Far",)],
            list(iter_ancestors("p.Start", supertypes_by_owner)),
        )

    def test_iter_ancestors_is_breadth_first_and_terminates_on_a_cycle(self):
        from codewiki.index.callgraph import iter_ancestors

        supertypes_by_owner = {
            "p.Start": ("p.Left", "p.Right"),
            "p.Left": ("p.Bottom",),
            "p.Right": ("p.Bottom",),
            "p.Bottom": ("p.Start",),
        }

        self.assertEqual(
            [("p.Left", "p.Right"), ("p.Bottom",)],
            list(iter_ancestors("p.Start", supertypes_by_owner)),
        )

    def test_unresolved_supertype_edge_is_not_walked(self):
        source = (
            "package p;\n"
            "class Caller { void run(B value) { value.run(); } }\n"
            "class B extends Missing {}\n"
            "class A { void run() {} }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            ("p.B", (), "UNRESOLVED", "member_absent"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_external_type_receiver_is_not_internal(self):
        source = (
            "package p;\n"
            "import java.util.Collections;\n"
            "class Caller { void run() { Collections.emptyList(); } }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            (None, (), "UNRESOLVED", "receiver_not_internal"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_unknown_type_receiver_stays_no_declaration(self):
        source = (
            "package p;\n"
            "class Caller { void run() { Zzz.nothing(); } }\n"
        )

        resolutions, _declarations = self._resolve_receivers(source)

        self.assertEqual(
            (None, (), "UNRESOLVED", "no_declaration"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_visible_variable_shadows_type_receiver(self):
        source = (
            "package p;\n"
            "class Holder { public static void help() {} }\n"
            "class T {\n"
            "    void m() {\n"
            "        Holder Holder = null;\n"
            "        Holder.help();\n"
            "    }\n"
            "}\n"
        )

        resolutions, declarations = self._resolve_receivers(source)

        self.assertEqual(
            [("local", "Holder")],
            [
                (item.kind, item.type_name)
                for item in declarations
                if item.name == "Holder"
            ],
        )
        self.assertEqual(
            ("p.Holder", ("p.Holder.help",), "CONFIRMED", "single_member"),
            (
                resolutions[0].owner_fqn,
                resolutions[0].targets,
                resolutions[0].confidence,
                resolutions[0].reason,
            ),
        )

    def test_imported_parameter_uses_combined_repository_lookup(self):
        from codewiki.index.callgraph import resolve_receiver_call
        from codewiki.index.calls import extract as extract_calls
        from codewiki.index.declarations import extract as extract_declarations
        from codewiki.index.imports import parse_imports
        from codewiki.index.resolution import build_lookup, type_infos
        from codewiki.index.symbols import extract as extract_symbols
        from codewiki.index.symbols import package_of

        files = (
            (
                "src/app/Caller.java",
                "package app;\n"
                "import p.Dao;\n"
                "\n"
                "public class Caller {\n"
                "    void run(Dao dao) {\n"
                "        dao.save();\n"
                "    }\n"
                "}\n",
            ),
            (
                "src/p/Dao.java",
                "package p;\n"
                "public class Dao {\n"
                "    public void save() {}\n"
                "}\n",
            ),
        )

        all_symbols = []
        all_declarations = []
        all_sites = []
        file_packages = {}
        imports_by_file = {}
        for path, source in files:
            symbols = extract_symbols(path, "java", source)
            all_symbols.extend(symbols)
            all_declarations.extend(
                extract_declarations(path, "java", source, symbols)
            )
            all_sites.extend(extract_calls(path, "java", source, symbols))
            file_packages[path] = package_of(source)
            imports_by_file[path] = parse_imports(path, source)

        types = type_infos(all_symbols)
        lookup = build_lookup(
            types,
            file_packages.values(),
            analyzable_packages=file_packages.values(),
        )
        members_by_owner = defaultdict(list)
        for symbol in all_symbols:
            if symbol.owner_fqn and symbol.kind == "method":
                members_by_owner[symbol.owner_fqn].append(symbol)

        caller_sites = [
            site for site in all_sites
            if site.path == "src/app/Caller.java"
            and site.form == "receiver"
            and site.receiver == "dao"
            and site.name == "save"
        ]
        self.assertEqual(1, len(caller_sites))
        self.assertEqual(
            ["p.Dao"],
            [record.name for record in imports_by_file["src/app/Caller.java"]],
        )

        result = resolve_receiver_call(
            caller_sites[0], all_declarations, file_packages, types,
            imports_by_file, lookup, dict(members_by_owner),
        )

        self.assertEqual("p.Dao", result.owner_fqn)
        self.assertEqual(("p.Dao.save",), result.targets)
        self.assertEqual("CONFIRMED", result.confidence)
        self.assertEqual("single_member", result.reason)


if __name__ == "__main__":
    unittest.main()
