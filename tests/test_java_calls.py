from __future__ import annotations

import unittest


class JavaCallTests(unittest.TestCase):
    def _extract(self, source):
        from codewiki.index.calls import extract
        from codewiki.index.symbols import extract as extract_symbols

        symbols = extract_symbols("src/Orders.java", "java", source)
        return extract("src/Orders.java", "java", source, symbols)

    @staticmethod
    def _bare_site(enclosing_fqn, name, enclosing_kind="method"):
        from codewiki.index.calls import CallSite

        return CallSite(
            "src/A.java", enclosing_fqn, enclosing_kind, 1,
            "bare", None, name,
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
            [("bare", None, "getBean"), ("chained", None, "save")],
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
            [("bare", None, "getBean"), ("chained", None, "doThing")],
            [(call.form, call.receiver, call.name) for call in calls],
        )
        self.assertEqual(["Orders.load", "Orders.load"],
                         [call.enclosing_fqn for call in calls])

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
