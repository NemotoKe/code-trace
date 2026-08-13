from __future__ import annotations

import unittest


class JavaDeclarationTests(unittest.TestCase):
    def _extract(self, source):
        from codewiki.index.declarations import extract
        from codewiki.index.symbols import extract as extract_symbols

        symbols = extract_symbols("src/Orders.java", "java", source)
        return extract("src/Orders.java", "java", source, symbols)

    def test_method_parameters(self):
        source = (
            "class Orders {\n"
            "    void cancel(String orderId, int reason) {\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [
                ("Orders.cancel", "method", "orderId", "String", 2, "parameter"),
                ("Orders.cancel", "method", "reason", "int", 2, "parameter"),
            ],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_local_declaration(self):
        source = (
            "class Orders {\n"
            "    void build() {\n"
            "        OrderDao dao = new OrderDaoImpl();\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders.build", "method", "dao", "OrderDao", 3, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_field_declaration(self):
        source = (
            "class Orders {\n"
            "    private final OrderDao dao;\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders", "class", "dao", "OrderDao", 2, "field")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_generic_type_arguments_are_stripped(self):
        source = (
            "import java.util.List;\n"
            "class Orders {\n"
            "    void load() {\n"
            "        List<Order> items = new ArrayList<>();\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders.load", "method", "items", "List", 4, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_enhanced_for_declaration(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        for (Order o : orders) {\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders.load", "method", "o", "Order", 3, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_try_resource_declaration(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        try (InputStream in = open()) {\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders.load", "method", "in", "InputStream", 3, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_catch_parameter_is_local(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        try {\n"
            "        } catch (IOException e) {\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders.load", "method", "e", "IOException", 4, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_qualified_generic_type_is_stripped(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        Map.Entry<K, V> entry = it.next();\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders.load", "method", "entry", "Map.Entry", 3, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_array_marker_is_kept(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        String[] names = loadNames();\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders.load", "method", "names", "String[]", 3, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_multiple_declarators_share_the_written_type(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        int a = 1, b = 2;\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("a", "int", 3), ("b", "int", 3)],
            [(item.name, item.type_name, item.line) for item in declarations],
        )
        self.assertTrue(all(item.kind == "local" for item in declarations))

    def test_var_has_no_written_type(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        var dao = factory.create();\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_assignment_is_not_a_declaration(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        dao = other;\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_return_is_not_a_declaration(self):
        source = (
            "class Orders {\n"
            "    String load(String orderId) {\n"
            "        return orderId;\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("orderId", "String", "parameter")],
            [(item.name, item.type_name, item.kind) for item in declarations],
        )

    def test_if_expression_is_not_a_declaration(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        if (dao != null) {\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_string_contents_are_not_declarations(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        String s = \"OrderDao dao = x;\";\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("s", "String", "local")],
            [(item.name, item.type_name, item.kind) for item in declarations],
        )

    def test_line_comment_contents_are_not_declarations(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        // OrderDao dao = x;\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_field_and_local_shadowing_are_both_recorded(self):
        source = (
            "class Orders {\n"
            "    private OrderDao dao;\n"
            "    void save() {\n"
            "        OrderDao dao = makeDao();\n"
            "        dao.save();\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders", "class", "dao", "OrderDao", 2, "field"),
             ("Orders.save", "method", "dao", "OrderDao", 4, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_local_in_nested_type_method_uses_innermost_method(self):
        source = (
            "class Outer {\n"
            "    class Inner {\n"
            "        void run() {\n"
            "            Order order = load();\n"
            "        }\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Outer.Inner.run", "method", "order", "Order", 4, "local")],
            [
                (item.scope_fqn, item.scope_kind, item.name, item.type_name,
                 item.line, item.kind)
                for item in declarations
            ],
        )

    def test_non_java_is_empty_and_identical_runs_are_deterministic(self):
        from codewiki.index.declarations import extract
        from codewiki.index.symbols import extract as extract_symbols

        source = (
            "class Orders {\n"
            "    void load(String id) {\n"
            "        Order order = find(id);\n"
            "    }\n"
            "}\n"
        )
        symbols = extract_symbols("Orders.java", "java", source)

        first = extract("Orders.java", "java", source, symbols)
        second = extract("Orders.java", "java", source, symbols)

        self.assertEqual(first, second)
        self.assertEqual([], extract("Orders.py", "python", "Order x\n", []))

    def test_multiline_parameters_keep_each_parameter_line(self):
        source = (
            "class Orders {\n"
            "    void cancel(\n"
            "        String orderId,\n"
            "        int reason\n"
            "    ) {\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("orderId", "String", 3), ("reason", "int", 4)],
            [(item.name, item.type_name, item.line) for item in declarations],
        )

    def test_block_comments_and_text_blocks_are_noise(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        String sql = \"\"\"\n"
            "            OrderDao fake = x;\n"
            "            \"\"\";\n"
            "        /* OrderDao hidden = x; */\n"
            "        OrderDao dao = makeDao();\n"
            "    }\n"
            "}\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("sql", "String", 3), ("dao", "OrderDao", 7)],
            [(item.name, item.type_name, item.line) for item in declarations],
        )

    def test_same_line_field_preceding_method_keeps_type_scope(self):
        source = (
            "class Orders { OrderDao dao; void load() { int count = 1; } }\n"
        )

        declarations = self._extract(source)

        self.assertEqual(
            [("Orders", "class", "dao", "field"),
             ("Orders.load", "method", "count", "local")],
            [(item.scope_fqn, item.scope_kind, item.name, item.kind)
             for item in declarations],
        )


if __name__ == "__main__":
    unittest.main()
