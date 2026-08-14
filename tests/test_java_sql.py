from __future__ import annotations

import unittest


class JavaSqlTests(unittest.TestCase):
    def _extract(self, source, path="src/Orders.java", language="java"):
        from codewiki.index.sql import extract
        from codewiki.index.symbols import extract as extract_symbols

        symbols = extract_symbols(path, language, source)
        return extract(path, language, source, symbols)

    def test_plain_uppercase_select_literal(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            '        String s = "SELECT id FROM orders";\n'
            "    }\n"
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(
            [{
                "path": "src/Orders.java",
                "enclosing_fqn": "Orders.load",
                "enclosing_kind": "method",
                "line": 3,
                "statement": "SELECT id FROM orders",
                "verb": "select",
            }],
            [literal.__dict__ for literal in literals],
        )

    def test_lowercase_select_literal(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            '        String s = "select id from orders";\n'
            "    }\n"
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(1, len(literals))
        self.assertEqual("select id from orders", literals[0].statement)
        self.assertEqual("select", literals[0].verb)

    def test_leading_whitespace_update_literal(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            '        String s = "  UPDATE orders SET status = ?";\n'
            "    }\n"
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(1, len(literals))
        self.assertEqual("  UPDATE orders SET status = ?", literals[0].statement)
        self.assertEqual("update", literals[0].verb)

    def test_keyword_without_following_whitespace_is_not_sql(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            '        String s = "DELETEFROM orders";\n'
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_sql_keyword_must_begin_the_literal(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            '        String s = "the SELECT clause";\n'
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_deleted_text_is_not_delete_sql(self):
        source = (
            "class Orders {\n"
            "    void load(int n) {\n"
            '        String s = "Deleted " + n + " rows";\n'
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_sql_in_line_comment_is_ignored(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            "        // SELECT id FROM orders\n"
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_text_block_select_literal(self):
        source = (
            "class Orders {\n"
            '    String s = """\n'
            "        SELECT id FROM orders\n"
            '        """;\n'
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(1, len(literals))
        self.assertEqual("select", literals[0].verb)
        self.assertEqual("\n        SELECT id FROM orders\n        ",
                         literals[0].statement)
        self.assertEqual(2, literals[0].line)
        self.assertEqual("Orders", literals[0].enclosing_fqn)
        self.assertEqual("class", literals[0].enclosing_kind)

    def test_concatenated_literals_are_one_statement(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            '        String sql = "SELECT id FROM orders "\n'
            '                   + "WHERE status = ? "\n'
            '                   + "AND created > ?";\n'
            "    }\n"
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(1, len(literals))
        self.assertEqual("SELECT id FROM orders WHERE status = ? AND created > ?",
                         literals[0].statement)
        self.assertEqual(3, literals[0].line)
        self.assertEqual("select", literals[0].verb)

    def test_concatenation_stops_at_dynamic_expression(self):
        source = (
            "class Orders {\n"
            "    void load(String tableName) {\n"
            '        String sql = "SELECT id FROM " + tableName + " WHERE status = ?";\n'
            "    }\n"
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(1, len(literals))
        self.assertEqual("SELECT id FROM ", literals[0].statement)
        self.assertEqual(3, literals[0].line)
        self.assertEqual("select", literals[0].verb)

    def test_remaining_supported_verbs_are_recorded(self):
        source = (
            "class Orders {\n"
            '    void add() { String s = "INSERT INTO orders VALUES (?)"; }\n'
            '    void change() { String s = "UPDATE orders SET status = ?"; }\n'
            '    void remove() { String s = "DELETE FROM orders WHERE id = ?"; }\n'
            '    void combine() { String s = "MERGE INTO orders USING updates"; }\n'
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(
            ["insert", "update", "delete", "merge"],
            [literal.verb for literal in literals],
        )

    def test_required_sql_shape_rejects_prose_and_bare_fragments(self):
        source = (
            "class Orders {\n"
            "    void load() {\n"
            '        String updateProse = "Update succeeded.";\n'
            '        String updateJob = "Update job {} to status {} if in status {}: {}";\n'
            '        String deleteProse = "Delete succeeded: Resource was already deleted";\n'
            '        String mergeProse = "Merge operation completed successfully.";\n'
            '        String selectFragment = "SELECT (";\n'
            '        String selectNoFrom = "SELECT id orders";\n'
            '        String updateNoSet = "UPDATE orders WHERE id = ?";\n'
            '        String deleteNoFrom = "DELETE orders WHERE id = ?";\n'
            '        String insertNoInto = "INSERT orders VALUES (?)";\n'
            '        String mergeNoInto = "MERGE orders USING updates";\n'
            '        String setting = "UPDATE orders SETTING status = ?";\n'
            '        String fromage = "SELECT * FROMAGE orders";\n'
            '        String intoage = "INSERT INTOAGE orders VALUES (?)";\n'
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_required_sql_shapes_keep_real_statements(self):
        source = (
            "class Orders {\n"
            '    void add() { String s = "insert into HFJ_RESOURCE (...)"; }\n'
            '    void read() { String s = "SELECT * FROM hfj_spidx_token"; }\n'
            '    void change() { String s = "UPDATE orders SET status = ?"; }\n'
            '    void remove() { String s = "DELETE FROM orders WHERE id = ?"; }\n'
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(
            ["insert", "select", "update", "delete"],
            [literal.verb for literal in literals],
        )
        self.assertEqual(
            [
                "insert into HFJ_RESOURCE (...)",
                "SELECT * FROM hfj_spidx_token",
                "UPDATE orders SET status = ?",
                "DELETE FROM orders WHERE id = ?",
            ],
            [literal.statement for literal in literals],
        )

    def test_dynamic_prefix_without_required_shape_is_dropped(self):
        source = (
            "class Orders {\n"
            "    void load(String columns) {\n"
            '        String sql = "SELECT id " + columns + " FROM orders";\n'
            "    }\n"
            "}\n"
        )

        self.assertEqual([], self._extract(source))

    def test_block_comments_and_string_comment_markers_are_handled(self):
        source = (
            "class Orders {\n"
            "    /* SELECT ignored */\n"
            "    void load() {\n"
            '        String notSql = "// SELECT ignored";\n'
            '        String sql = "SELECT id FROM orders";\n'
            "    }\n"
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(1, len(literals))
        self.assertEqual("SELECT id FROM orders", literals[0].statement)

    def test_non_java_input_returns_no_literals(self):
        self.assertEqual([], self._extract(
            'class Orders { String s = "SELECT id FROM orders"; }',
            language="kotlin",
        ))

    def test_nested_method_and_type_attribution_uses_innermost_symbol(self):
        source = (
            "class Outer {\n"
            "    class Inner {\n"
            "        String field = \"SELECT id FROM orders\";\n"
            "        void load() {\n"
            '            String s = "SELECT id FROM orders";\n'
            "        }\n"
            "    }\n"
            "}\n"
        )

        literals = self._extract(source)

        self.assertEqual(
            [("Outer.Inner", "class"), ("Outer.Inner.load", "method")],
            [(literal.enclosing_fqn, literal.enclosing_kind)
             for literal in literals],
        )


if __name__ == "__main__":
    unittest.main()
