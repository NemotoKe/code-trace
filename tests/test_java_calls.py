from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


class JavaCallTests(unittest.TestCase):
    def _extract(self, source):
        from codewiki.index.calls import extract
        from codewiki.index.symbols import extract as extract_symbols

        symbols = extract_symbols("src/Orders.java", "java", source)
        return extract("src/Orders.java", "java", source, symbols)

    def _chained_sites(self, source):
        return [
            (call.form, call.name, call.receiver)
            for call in self._extract(source)
            if call.form == "chained"
        ]

    @staticmethod
    def _bare_site(enclosing_fqn, name, enclosing_kind="method"):
        from codewiki.index.calls import CallSite

        return CallSite(
            "src/A.java", enclosing_fqn, enclosing_kind, 1,
            "bare", None, name,
        )

    @staticmethod
    def _chained_site(receiver, name, line=1):
        from codewiki.index.calls import CallSite

        return CallSite(
            "src/Use.java", "com.acme.Use.run", "method", line,
            "chained", receiver, name,
        )

    @staticmethod
    def _member(owner_fqn, name, fqn=None):
        from codewiki.index.symbols import Symbol

        return Symbol(
            "src/A.java", name, "method",
            fqn or owner_fqn + "." + name,
            owner_fqn, "com.acme", [], 0, name + "()", 1, 1,
            "CONFIRMED",
        )

    @staticmethod
    def _returning_member(owner_fqn, name, return_type_name,
                          path="src/Repo.java", fqn=None, signature=None):
        from codewiki.index.symbols import Symbol

        return Symbol(
            path, name, "method", fqn or owner_fqn + "." + name,
            owner_fqn, "com.acme", [], 0,
            signature or "public %s %s()" % (return_type_name, name),
            1, 1, "CONFIRMED",
        )

    def test_chained_resolution_uses_return_type_and_inheritance(self):
        from codewiki.index.callgraph import CallResolution, resolve_chained_call
        from codewiki.index.resolution import TypeInfo, build_lookup
        from codewiki.index.calls import CallSite

        types = [
            TypeInfo("src/Repo.java", "Repo", "com.acme.Repo", "com.acme", None),
            TypeInfo("src/Row.java", "Row", "com.acme.Row", "com.acme", None),
            TypeInfo("src/Base.java", "Base", "com.acme.Base", "com.acme", None),
        ]
        file_packages = {
            "src/Use.java": "com.acme",
            "src/Repo.java": "com.acme",
            "src/Row.java": "com.acme",
            "src/Base.java": "com.acme",
        }
        imports_by_file = {path: [] for path in file_packages}
        lookup = build_lookup(
            types, file_packages.values(),
            analyzable_packages=file_packages.values(),
        )

        previous_site = CallSite(
            "src/Use.java", "com.acme.Use.run", "method", 1,
            "receiver", "repo", "find",
        )
        previous = CallResolution(
            previous_site, "com.acme.Repo", ("com.acme.Repo.find",),
            "CONFIRMED", "single_member",
        )
        previous_key = ("src/Use.java", "com.acme.Use.run", 1, "find")
        repo_find = self._returning_member(
            "com.acme.Repo", "find", "Row",
            fqn="com.acme.Repo.find",
        )

        def resolve(members, supertypes=None):
            return resolve_chained_call(
                self._chained_site("find", "save"),
                {previous_key: previous},
                {repo_find.fqn: repo_find},
                file_packages, types, imports_by_file, lookup,
                members, supertypes,
            )

        single = resolve({
            "com.acme.Row": [
                self._returning_member("com.acme.Row", "save", "void"),
            ],
        })
        overloaded = resolve({
            "com.acme.Row": [
                self._returning_member("com.acme.Row", "save", "void",
                                        fqn="com.acme.Row.save"),
                self._returning_member("com.acme.Row", "save", "void",
                                        fqn="com.acme.Row.save(int)"),
            ],
        })
        inherited = resolve(
            {"com.acme.Base": [
                self._returning_member("com.acme.Base", "save", "void"),
            ]},
            {"com.acme.Row": ("com.acme.Base",)},
        )

        self.assertEqual(
            ("com.acme.Row", ("com.acme.Row.save",), "CONFIRMED",
             "chained_single_member"),
            (single.owner_fqn, single.targets, single.confidence, single.reason),
        )
        self.assertEqual(
            ("com.acme.Row", ("com.acme.Row.save", "com.acme.Row.save(int)"),
             "POSSIBLE", "chained_overloaded"),
            (overloaded.owner_fqn, overloaded.targets,
             overloaded.confidence, overloaded.reason),
        )
        self.assertEqual(
            ("com.acme.Row", ("com.acme.Base.save",), "CONFIRMED",
             "chained_inherited_single_member"),
            (inherited.owner_fqn, inherited.targets,
             inherited.confidence, inherited.reason),
        )

    def test_chained_resolution_reports_contract_failures(self):
        from codewiki.index.callgraph import CallResolution, resolve_chained_call
        from codewiki.index.resolution import TypeInfo, build_lookup
        from codewiki.index.calls import CallSite

        types = [
            TypeInfo("src/Repo.java", "Repo", "com.acme.Repo", "com.acme", None),
            TypeInfo("src/Row.java", "Row", "com.acme.Row", "com.acme", None),
        ]
        file_packages = {
            "src/Use.java": "com.acme",
            "src/Repo.java": "com.acme",
            "src/Row.java": "com.acme",
        }
        imports_by_file = {path: [] for path in file_packages}
        lookup = build_lookup(
            types, file_packages.values(),
            analyzable_packages=file_packages.values(),
        )

        def previous(name="find", confidence="CONFIRMED", targets=None,
                     symbol=None):
            previous_site = CallSite(
                "src/Use.java", "com.acme.Use.run", "method", 1,
                "receiver", "repo", name,
            )
            resolution = CallResolution(
                previous_site, "com.acme.Repo", tuple(targets or (
                    "com.acme.Repo." + name,
                )), confidence, "single_member",
            )
            return (
                resolution,
                {("src/Use.java", "com.acme.Use.run", 1, name): resolution},
                {resolution.targets[0]: symbol} if symbol is not None else {},
            )

        def resolve(site, resolution, previous_map, symbols, members=None):
            return resolve_chained_call(
                site, previous_map, symbols, file_packages, types,
                imports_by_file, lookup, members or {},
            )

        return_unknown = self._returning_member(
            "com.acme.Repo", "findUnknown", "ignored",
            fqn="com.acme.Repo.findUnknown",
            signature="public ??? findUnknown()",
        )
        unknown_resolution, unknown_map, unknown_symbols = previous(
            name="findUnknown", symbol=return_unknown,
        )
        unknown = resolve(
            self._chained_site("findUnknown", "save"), unknown_resolution,
            unknown_map, unknown_symbols,
        )

        external = self._returning_member(
            "com.acme.Repo", "findExternal", "String",
            fqn="com.acme.Repo.findExternal",
        )
        external_resolution, external_map, external_symbols = previous(
            name="findExternal", symbol=external,
        )
        external_result = resolve(
            self._chained_site("findExternal", "save"), external_resolution,
            external_map, external_symbols,
        )

        absent_member = self._returning_member(
            "com.acme.Repo", "findAbsent", "Row",
            fqn="com.acme.Repo.findAbsent",
        )
        absent_resolution, absent_map, absent_symbols = previous(
            name="findAbsent", symbol=absent_member,
        )
        absent = resolve(
            self._chained_site("findAbsent", "save"), absent_resolution,
            absent_map, absent_symbols,
        )

        unresolved_resolution, unresolved_map, unresolved_symbols = previous(
            confidence="UNRESOLVED",
        )
        unresolved = resolve(
            self._chained_site("find", "save"), unresolved_resolution,
            unresolved_map, unresolved_symbols,
        )
        multiple_resolution, multiple_map, multiple_symbols = previous(
            targets=("com.acme.Repo.find", "com.acme.Repo.find(int)"),
        )
        multiple = resolve(
            self._chained_site("find", "save"), multiple_resolution,
            multiple_map, multiple_symbols,
        )
        none_receiver = resolve(
            self._chained_site(None, "save"), None, {}, {},
        )

        for result, expected in (
            (unknown, (None, "chained_return_type_unknown")),
            (external_result, (None, "chained_return_type_not_internal")),
            (unresolved, (None, "chained_receiver_unresolved")),
            (multiple, (None, "chained_receiver_unresolved")),
            (none_receiver, (None, "form_not_resolved")),
        ):
            self.assertEqual(expected[0], result.owner_fqn)
            self.assertEqual((), result.targets)
            self.assertEqual("UNRESOLVED", result.confidence)
            self.assertEqual(expected[1], result.reason)
        self.assertEqual(
            ("com.acme.Row", (), "UNRESOLVED", "chained_member_absent"),
            (absent.owner_fqn, absent.targets, absent.confidence, absent.reason),
        )

    def test_pipeline_resolves_chained_calls_from_previous_return_types(self):
        from codewiki.index import pipeline

        files = {
            "src/com/acme/Repo.java": (
                "package com.acme;\n"
                "public class Repo {\n"
                "    public Row find() { return null; }\n"
                "    public Unique findUnique() { return null; }\n"
                "    public Child findChild() { return null; }\n"
                "    public ChildOverloaded findChildOverloaded() { return null; }\n"
                "    public Row findAbsent() { return null; }\n"
                "    public String findExternal() { return null; }\n"
                "    public ??? findUnknown() { return null; }\n"
                "}\n"
            ),
            "src/com/acme/Row.java": (
                "package com.acme;\n"
                "public class Row {\n"
                "    public void save() {}\n"
                "    public void save(int value) {}\n"
                "}\n"
            ),
            "src/com/acme/Unique.java": (
                "package com.acme;\n"
                "public class Unique { public void save() {} }\n"
            ),
            "src/com/acme/Base.java": (
                "package com.acme;\n"
                "public class Base {\n"
                "    public void inherited() {}\n"
                "    public void overloaded() {}\n"
                "    public void overloaded(int value) {}\n"
                "}\n"
            ),
            "src/com/acme/Child.java": (
                "package com.acme;\n"
                "public class Child extends Base {}\n"
            ),
            "src/com/acme/ChildOverloaded.java": (
                "package com.acme;\n"
                "public class ChildOverloaded extends Base {}\n"
            ),
            "src/app/Use.java": (
                "package app;\n"
                "import com.acme.Repo;\n"
                "class Use {\n"
                "    private Repo repo;\n"
                "    void run() {\n"
                "        repo.find().save();\n"
                "        repo.findUnique().save();\n"
                "        repo.findChild().inherited();\n"
                "        repo.findChildOverloaded().overloaded();\n"
                "        repo.findAbsent().missing();\n"
                "        unknown.find().save();\n"
                "        repo.findExternal().save();\n"
                "        repo.findUnknown().save();\n"
                "        new Repo().save();\n"
                "    }\n"
                "}\n"
            ),
        }

        with tempfile.TemporaryDirectory(prefix="codewiki-chained-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-chained-out-") as out:
            for relative_path, contents in files.items():
                path = os.path.join(root, relative_path)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(contents)
            result = pipeline.run(root, out, jobs=1)

            connection = sqlite3.connect(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT line, receiver, name, owner_fqn, confidence, reason "
                    "FROM calls WHERE form = 'chained' ORDER BY line"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                (6, "find", "save", "com.acme.Row", "POSSIBLE",
                 "chained_overloaded"),
                (7, "findUnique", "save", "com.acme.Unique", "CONFIRMED",
                 "chained_single_member"),
                (8, "findChild", "inherited", "com.acme.Child", "CONFIRMED",
                 "chained_inherited_single_member"),
                (9, "findChildOverloaded", "overloaded", "com.acme.ChildOverloaded",
                 "POSSIBLE", "chained_inherited_overloaded"),
                (10, "findAbsent", "missing", "com.acme.Row", "UNRESOLVED",
                 "chained_member_absent"),
                (11, "find", "save", None, "UNRESOLVED",
                 "chained_receiver_unresolved"),
                (12, "findExternal", "save", None, "UNRESOLVED",
                 "chained_return_type_not_internal"),
                (13, "findUnknown", "save", None, "UNRESOLVED",
                 "chained_return_type_unknown"),
                (14, None, "save", None, "UNRESOLVED", "form_not_resolved"),
            ],
            rows,
        )

    def test_pipeline_distinguishes_bare_calls_with_unresolved_supertypes(self):
        from codewiki.index import pipeline

        files = {
            "src/com/acme/Base.java": (
                "package com.acme;\n"
                "public class Base { public void known() {} }\n"
            ),
            "src/com/acme/Internal.java": (
                "package com.acme;\n"
                "public class Internal extends Base {\n"
                "    void a() { known(); }\n"
                "    void b() { nosuch(); }\n"
                "}\n"
            ),
            "src/com/acme/External.java": (
                "package com.acme;\n"
                "import javax.servlet.http.HttpServlet;\n"
                "public class External extends HttpServlet {\n"
                "    void c() { doGet(); }\n"
                "    void d() { nosuch(); }\n"
                "}\n"
            ),
            "src/com/acme/Plain.java": (
                "package com.acme;\n"
                "public class Plain { void e() { missing(); } }\n"
            ),
        }

        with tempfile.TemporaryDirectory(prefix="codewiki-bare-supertype-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-bare-supertype-out-") as out:
            for relative_path, contents in files.items():
                path = os.path.join(root, relative_path)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as stream:
                    stream.write(contents)
            result = pipeline.run(root, out, jobs=1)

            connection = sqlite3.connect(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT caller_fqn, name, owner_fqn, target_fqn, "
                    "confidence, reason FROM calls "
                    "WHERE form = 'bare' ORDER BY caller_fqn"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                ("com.acme.External.c", "doGet", "com.acme.External", None,
                 "UNRESOLVED", "bare_supertype_not_internal"),
                ("com.acme.External.d", "nosuch", "com.acme.External", None,
                 "UNRESOLVED", "bare_supertype_not_internal"),
                ("com.acme.Internal.a", "known", "com.acme.Internal",
                 "com.acme.Base.known", "CONFIRMED",
                 "bare_inherited_single_member"),
                ("com.acme.Internal.b", "nosuch", "com.acme.Internal", None,
                 "UNRESOLVED", "bare_member_absent"),
                ("com.acme.Plain.e", "missing", "com.acme.Plain", None,
                 "UNRESOLVED", "bare_member_absent"),
            ],
            rows,
        )

    def test_bare_resolution_finds_direct_member(self):
        from codewiki.index.callgraph import resolve_bare_call

        site = self._bare_site("com.acme.A.m", "helper")
        result = resolve_bare_call(
            site,
            {"com.acme.A": [self._member("com.acme.A", "helper")]},
        )

        self.assertEqual(
            ("com.acme.A", ("com.acme.A.helper",), "CONFIRMED",
             "bare_single_member"),
            (result.owner_fqn, result.targets, result.confidence, result.reason),
        )

    def test_bare_resolution_reports_overload_and_absent_member(self):
        from codewiki.index.callgraph import resolve_bare_call

        overloaded = resolve_bare_call(
            self._bare_site("com.acme.A.m", "helper"),
            {
                "com.acme.A": [
                    self._member("com.acme.A", "helper", "com.acme.A.helper(int)"),
                    self._member("com.acme.A", "helper", "com.acme.A.helper"),
                ],
            },
        )
        absent = resolve_bare_call(
            self._bare_site("com.acme.A.m", "nosuch"),
            {"com.acme.A": []},
        )

        self.assertEqual(
            ("com.acme.A",
             ("com.acme.A.helper", "com.acme.A.helper(int)"),
             "POSSIBLE", "bare_overloaded"),
            (overloaded.owner_fqn, overloaded.targets,
             overloaded.confidence, overloaded.reason),
        )
        self.assertEqual(
            ("com.acme.A", (), "UNRESOLVED", "bare_member_absent"),
            (absent.owner_fqn, absent.targets, absent.confidence, absent.reason),
        )

    def test_bare_resolution_uses_inherited_members(self):
        from codewiki.index.callgraph import resolve_bare_call

        result = resolve_bare_call(
            self._bare_site("com.acme.A.m", "helper"),
            {
                "com.acme.Base": [self._member("com.acme.Base", "helper")],
            },
            {"com.acme.A": ("com.acme.Base",)},
        )

        self.assertEqual(
            ("com.acme.A", ("com.acme.Base.helper",), "CONFIRMED",
             "bare_inherited_single_member"),
            (result.owner_fqn, result.targets, result.confidence, result.reason),
        )

    def test_bare_resolution_reports_inherited_overload(self):
        from codewiki.index.callgraph import resolve_bare_call

        result = resolve_bare_call(
            self._bare_site("com.acme.A.m", "helper"),
            {
                "com.acme.Base": [
                    self._member("com.acme.Base", "helper", "com.acme.Base.helper"),
                    self._member(
                        "com.acme.Base", "helper", "com.acme.Base.helper(int)",
                    ),
                ],
            },
            {"com.acme.A": ("com.acme.Base",)},
        )

        self.assertEqual(
            ("com.acme.A",
             ("com.acme.Base.helper", "com.acme.Base.helper(int)"),
             "POSSIBLE", "bare_inherited_overloaded"),
            (result.owner_fqn, result.targets, result.confidence, result.reason),
        )

    def test_bare_resolution_uses_innermost_nested_enclosing_type(self):
        from codewiki.index.callgraph import resolve_bare_call

        result = resolve_bare_call(
            self._bare_site("com.acme.A.Inner.m", "helper"),
            {
                "com.acme.A.Inner": [
                    self._member("com.acme.A.Inner", "helper"),
                ],
            },
        )

        self.assertEqual("com.acme.A.Inner", result.owner_fqn)
        self.assertEqual(("com.acme.A.Inner.helper",), result.targets)
        self.assertEqual("CONFIRMED", result.confidence)
        self.assertEqual("bare_single_member", result.reason)

    def test_receiver_call(self):
        source = (
            "class Orders {\n"
            "    void saveOne(String id) {\n"
            "        dao.save(id);\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual(
            {
                "path": "src/Orders.java",
                "enclosing_fqn": "Orders.saveOne",
                "enclosing_kind": "method",
                "line": 3,
                "form": "receiver",
                "receiver": "dao",
                "name": "save",
            },
            calls[0].__dict__,
        )

    def test_explicit_type_argument_keeps_named_receiver(self):
        source = (
            "class Orders {\n"
            "    void saveOne() {\n"
            "        Dao.<String>save();\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual(
            {
                "path": "src/Orders.java",
                "enclosing_fqn": "Orders.saveOne",
                "enclosing_kind": "method",
                "line": 3,
                "form": "receiver",
                "receiver": "Dao",
                "name": "save",
            },
            calls[0].__dict__,
        )

    def test_explicit_type_argument_keeps_variable_receiver(self):
        source = (
            "class Orders {\n"
            "    void saveOne() {\n"
            "        dao.<String>save();\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(
            [("receiver", "dao", "save")],
            [(call.form, call.receiver, call.name) for call in calls],
        )

    def test_explicit_type_argument_keeps_chained_call(self):
        source = (
            "class Orders {\n"
            "    void saveOne() {\n"
            "        getBean().<String>save();\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(
            [("bare", None, "getBean"), ("chained", "getBean", "save")],
            [(call.form, call.receiver, call.name) for call in calls],
        )

    def test_explicit_type_argument_keeps_class_receiver(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        Collections.<String>emptyList();\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(
            [("receiver", "Collections", "emptyList")],
            [(call.form, call.receiver, call.name) for call in calls],
        )

    def test_comparison_is_not_an_explicit_type_argument(self):
        source = (
            "class Orders {\n"
            "    void check() {\n"
            "        if (a < b && c > d(e));\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(
            [("bare", None, "d")],
            [(call.form, call.receiver, call.name) for call in calls],
        )
        self.assertEqual(
            [],
            [(call.form, call.receiver, call.name) for call in calls
             if call.name == "d" and call.form in ("receiver", "chained")],
        )

    def test_bare_call(self):
        source = (
            "class Orders {\n"
            "    void saveOne(String id) {\n"
            "        save(id);\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual("bare", calls[0].form)
        self.assertIsNone(calls[0].receiver)
        self.assertEqual("save", calls[0].name)
        self.assertEqual("Orders.saveOne", calls[0].enclosing_fqn)
        self.assertEqual("method", calls[0].enclosing_kind)

    def test_chained_expression_has_bare_and_chained_sites(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        getBean(X.class).doThing();\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(
            [("bare", None, "getBean"), ("chained", "getBean", "doThing")],
            [(call.form, call.receiver, call.name) for call in calls],
        )
        self.assertEqual(["Orders.load", "Orders.load"],
                         [call.enclosing_fqn for call in calls])

    def test_chained_receiver_is_previous_call_name(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        a.b().c();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual(
            [("chained", "c", "b")],
            self._chained_sites(source),
        )

    def test_chained_receiver_after_bare_call(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        foo().bar();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual(
            [("chained", "bar", "foo")],
            self._chained_sites(source),
        )

    def test_chained_receiver_tracks_each_link(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        a.b().c().d();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual(
            [("chained", "c", "b"), ("chained", "d", "c")],
            self._chained_sites(source),
        )

    def test_chained_receiver_after_member_call(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        list.get(0).name();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual(
            [("chained", "name", "get")],
            self._chained_sites(source),
        )

    def test_chained_receiver_counts_nested_argument_parentheses(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        a.b(x.y()).c();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual(
            [("chained", "c", "b")],
            self._chained_sites(source),
        )

    def test_chained_receiver_is_none_after_cast_expression(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        ((Foo) x).m();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual(
            [("chained", "m", None)],
            self._chained_sites(source),
        )

    def test_chained_receiver_is_none_after_new_expression(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        new Foo().bar();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual(
            [("chained", "bar", None)],
            self._chained_sites(source),
        )

    def test_chained_receiver_requires_close_paren_before_dot(self):
        source = (
            "class Orders {\n"
            "    void run() {\n"
            "        log(a).b();\n"
            "        System.out.println(\"x\");\n"
            "        log(a).b();\n"
            "        arr[0].size();\n"
            "        log(a).b();\n"
            "        \"abc\".length();\n"
            "    }\n"
            "}\n"
        )

        chained = [
            (call.name, call.receiver)
            for call in self._extract(source)
            if call.form == "chained"
            and call.name in ("println", "size", "length")
        ]

        self.assertEqual(
            [("println", None), ("size", None), ("length", None)],
            chained,
        )

    def test_method_reference_is_a_separate_site(self):
        source = (
            "class Orders {\n"
            "    void visit() {\n"
            "        list.forEach(Foo::bar);\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(
            [("receiver", "list", "forEach"),
             ("method_ref", "Foo", "bar")],
            [(call.form, call.receiver, call.name) for call in calls],
        )
        self.assertEqual(["Orders.visit", "Orders.visit"],
                         [call.enclosing_fqn for call in calls])

    def test_constructor_method_reference_is_a_constructor_site(self):
        source = (
            "class Orders {\n"
            "    void build() {\n"
            "        Supplier<Foo> s = Foo::new;\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual(
            {
                "path": "src/Orders.java",
                "enclosing_fqn": "Orders.build",
                "enclosing_kind": "method",
                "line": 3,
                "form": "constructor",
                "receiver": None,
                "name": "Foo",
            },
            calls[0].__dict__,
        )

    def test_array_constructor_method_reference_is_ignored(self):
        source = (
            "class Orders {\n"
            "    void build() {\n"
            "        IntFunction<int[]> factory = int[]::new;\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_constructor_call_is_not_a_bare_call(self):
        source = (
            "class Orders {\n"
            "    void build() {\n"
            "        new OrderDao();\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual("constructor", calls[0].form)
        self.assertIsNone(calls[0].receiver)
        self.assertEqual("OrderDao", calls[0].name)
        self.assertEqual("Orders.build", calls[0].enclosing_fqn)

    def test_if_clause_is_not_a_call(self):
        source = (
            "class Orders {\n"
            "    void check(boolean x) {\n"
            "        if (x) {\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_catch_clause_is_not_a_call(self):
        source = (
            "class Orders {\n"
            "    void check() {\n"
            "        try {\n"
            "        } catch (IOException e) {\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_while_clause_keeps_only_receiver_call(self):
        source = (
            "class Orders {\n"
            "    void check() {\n"
            "        while (it.hasNext()) {\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual("receiver", calls[0].form)
        self.assertEqual("it", calls[0].receiver)
        self.assertEqual("hasNext", calls[0].name)

    def test_annotation_arguments_are_not_calls(self):
        source = (
            "class Orders {\n"
            "    @Test(expected = E.class)\n"
            "    void check() {\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_method_declaration_is_not_a_call_to_itself(self):
        source = (
            "class Orders {\n"
            "    public void cancel(String id) {\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_string_contents_are_not_calls(self):
        source = (
            "class Orders {\n"
            "    void text() {\n"
            "        String s = \"dao.save(x)\";\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_line_comment_contents_are_not_calls(self):
        source = (
            "class Orders {\n"
            "    void text() {\n"
            "        // dao.save(x)\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_field_initializer_blocks_and_nested_members_use_innermost_symbol(self):
        source = (
            "package p;\n"
            "class Outer {\n"
            "    Object field = make();\n"
            "    static { initialize(); }\n"
            "    { instanceInitialize(); }\n"
            "    void outer() { run(); }\n"
            "    class Inner {\n"
            "        void inner() { work(); }\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(
            [(3, "p.Outer", "class", "make"),
             (4, "p.Outer", "class", "initialize"),
             (5, "p.Outer", "class", "instanceInitialize"),
             (6, "p.Outer.outer", "method", "run"),
             (8, "p.Outer.Inner.inner", "method", "work")],
            [(call.line, call.enclosing_fqn, call.enclosing_kind, call.name)
             for call in calls],
        )

    def test_text_block_contents_are_not_calls(self):
        source = (
            "class Orders {\n"
            "    String sql = \"\"\"\n"
            "        create table HFJ_IDX_CMB_TOK (\n"
            "            id integer\n"
            "        );\n"
            "        \"\"\";\n"
            "    void load() {\n"
            "        execute();\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual(8, calls[0].line)
        self.assertEqual("execute", calls[0].name)
        self.assertEqual("Orders.load", calls[0].enclosing_fqn)

    def test_non_java_is_empty_and_identical_runs_are_deterministic(self):
        from codewiki.index.calls import extract
        from codewiki.index.symbols import extract as extract_symbols

        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        first(); second();\n"
            "    }\n"
            "}\n"
        )
        symbols = extract_symbols("Orders.java", "java", source)

        first = extract("Orders.java", "java", source, symbols)
        second = extract("Orders.java", "java", source, symbols)

        self.assertEqual(first, second)
        self.assertEqual([], extract("Orders.py", "python", "first()\n", []))

    def test_multiline_receiver_uses_member_invocation_line(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        dao\n"
            "            .save(id);\n"
            "    }\n"
            "}\n"
        )

        calls = self._extract(source)

        self.assertEqual(1, len(calls))
        self.assertEqual(4, calls[0].line)
        self.assertEqual("receiver", calls[0].form)
        self.assertEqual("dao", calls[0].receiver)
        self.assertEqual("save", calls[0].name)


if __name__ == "__main__":
    unittest.main()
