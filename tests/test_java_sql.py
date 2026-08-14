from __future__ import annotations

import unittest


class JavaSqlTests(unittest.TestCase):
    def test_table_accesses_case_table(self):
        from codewiki.index.sql import TableAccess, table_accesses

        cases = [
            (
                "SELECT * FROM hfj_spidx_token",
                "select",
                (TableAccess("hfj_spidx_token", "READ"),),
            ),
            (
                "SELECT d FROM TagDefinition d WHERE d.myId IN "
                "(SELECT DISTINCT t.myTagId FROM ResourceTag t "
                "WHERE t.myResourceType = :res)",
                "select",
                (
                    TableAccess("TagDefinition", "READ"),
                    TableAccess("ResourceTag", "READ"),
                ),
            ),
            (
                "SELECT r FROM ResourceTable r LEFT JOIN FETCH "
                "r.myParamsToken WHERE r.myPid IN ( :IDS )",
                "select",
                (TableAccess("ResourceTable", "READ"),),
            ),
            (
                "insert into HFJ_RESOURCE (RES_VERSION, HAS_TAGS) "
                "values (?, ?)",
                "insert",
                (TableAccess("HFJ_RESOURCE", "WRITE"),),
            ),
            (
                "UPDATE Batch2JobInstanceEntity e SET e.myStatus = :status "
                "WHERE e.myId = :id",
                "update",
                (TableAccess("Batch2JobInstanceEntity", "WRITE"),),
            ),
            (
                "DELETE FROM Batch2WorkChunkEntity e "
                "WHERE e.myInstanceId = :instanceId",
                "delete",
                (TableAccess("Batch2WorkChunkEntity", "WRITE"),),
            ),
            (
                "MERGE INTO orders o USING staging s ON (o.id = s.id) "
                "WHEN MATCHED THEN UPDATE SET o.status = s.status",
                "merge",
                (
                    TableAccess("orders", "WRITE"),
                    TableAccess("staging", "READ"),
                ),
            ),
            (
                "SELECT * FROM (",
                "select",
                (),
            ),
            (
                "Update succeeded.",
                "update",
                (),
            ),
            (
                "DELETE audit_rows WHERE id IN (SELECT id FROM audit)",
                "delete",
                (TableAccess("audit", "READ"),),
            ),
            (
                "DELETE FROM orders WHERE id IN (SELECT id FROM audit)",
                "delete",
                (
                    TableAccess("orders", "WRITE"),
                    TableAccess("audit", "READ"),
                ),
            ),
            (
                "DELETE FROM a JOIN b ON a.id=b.id",
                "delete",
                (
                    TableAccess("a", "WRITE"),
                    TableAccess("b", "READ"),
                ),
            ),
            (
                "UPDATE orders SET s = (SELECT s FROM audit)",
                "update",
                (TableAccess("orders", "WRITE"),),
            ),
            (
                "MERGE INTO orders o USING staging s ON (o.id=s.id)",
                "merge",
                (
                    TableAccess("orders", "WRITE"),
                    TableAccess("staging", "READ"),
                ),
            ),
            (
                "SELECT x FROM a WHERE y IN (SELECT z FROM b)",
                "select",
                (
                    TableAccess("a", "READ"),
                    TableAccess("b", "READ"),
                ),
            ),
            (
                "insert into HFJ_RESOURCE (RES_VERSION) values (?)",
                "insert",
                (TableAccess("HFJ_RESOURCE", "WRITE"),),
            ),
        ]

        for statement, verb, expected in cases:
            with self.subTest(statement=statement, verb=verb):
                self.assertEqual(expected, table_accesses(statement, verb))

    def test_tables_extracts_plain_select_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("hfj_spidx_token",),
            tables("SELECT * FROM hfj_spidx_token", "select"),
        )

    def test_tables_extracts_qualified_select_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("app.orders",),
            tables("SELECT * FROM app.orders", "select"),
        )

    def test_tables_extracts_double_quoted_select_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables('SELECT * FROM "orders"', "select"),
        )

    def test_tables_extracts_backtick_quoted_select_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables("SELECT * FROM `orders`", "select"),
        )

    def test_tables_extracts_bracket_quoted_select_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables("SELECT * FROM [orders]", "select"),
        )

    def test_tables_ignores_select_table_alias(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("ResourceTable",),
            tables("SELECT r FROM ResourceTable r WHERE ...", "select"),
        )

    def test_tables_excludes_fetch_alias_path(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("ResourceTable",),
            tables(
                "SELECT r FROM ResourceTable r "
                "LEFT JOIN FETCH r.myParamsToken",
                "select",
            ),
        )

    def test_tables_extracts_insert_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("HFJ_RESOURCE",),
            tables("INSERT INTO HFJ_RESOURCE (A, B) VALUES (?, ?)", "insert"),
        )

    def test_tables_extracts_update_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables("UPDATE orders o SET o.status = ?", "update"),
        )

    def test_tables_extracts_delete_target(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("Batch2WorkChunkEntity",),
            tables(
                "DELETE FROM Batch2WorkChunkEntity e "
                "WHERE e.myInstanceId = :id",
                "delete",
            ),
        )

    def test_tables_extracts_merge_target_and_using_source(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders", "staging"),
            tables("MERGE INTO orders USING staging ON (...)", "merge"),
        )

    def test_tables_ignores_quoted_and_commented_control_words(self):
        from codewiki.index.sql import tables

        cases = [
            (
                "MERGE INTO target ON note = 'USING fake'",
                "merge",
                ("target",),
            ),
            (
                'MERGE INTO target ON note = "USING fake"',
                "merge",
                ("target",),
            ),
            (
                "INSERT /* INTO fake */ INTO target VALUES (?)",
                "insert",
                ("target",),
            ),
            (
                "MERGE INTO target /* USING fake */ USING source ON ...",
                "merge",
                ("target", "source"),
            ),
        ]

        for statement, verb, expected in cases:
            with self.subTest(statement=statement, verb=verb):
                self.assertEqual(expected, tables(statement, verb))

    def test_tables_extracts_join_source(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders", "order_items"),
            tables(
                "SELECT * FROM orders o JOIN order_items i "
                "ON o.id = i.order_id",
                "select",
            ),
        )

    def test_tables_extracts_nested_select_source(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("TagDefinition", "ResourceTag"),
            tables(
                "SELECT d FROM TagDefinition d "
                "WHERE d.myId IN "
                "(SELECT t.myTagId FROM ResourceTag t)",
                "select",
            ),
        )

    def test_tables_extracts_derived_table_source(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables("SELECT * FROM (SELECT id FROM orders) t", "select"),
        )

    def test_tables_rejects_join_alias_path(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables("SELECT * FROM orders o JOIN o.items i", "select"),
        )

    def test_tables_rejects_later_declared_alias_path(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables("SELECT * FROM o.items JOIN orders o ON ...", "select"),
        )

    def test_tables_filters_alias_paths_across_source_forms(self):
        from codewiki.index.sql import tables

        cases = [
            (
                "SELECT * FROM app.orders AS O JOIN o.Items AS I "
                "JOIN i.parts p",
                "select",
                ("app.orders",),
            ),
            (
                'SELECT * FROM "orders" o JOIN o.items i',
                "select",
                ("orders",),
            ),
            (
                "UPDATE app.orders AS o SET o.status = ?",
                "update",
                ("app.orders",),
            ),
            (
                "MERGE INTO orders AS o USING o.items i ON ...",
                "merge",
                ("orders",),
            ),
        ]

        for statement, verb, expected in cases:
            with self.subTest(statement=statement, verb=verb):
                self.assertEqual(expected, tables(statement, verb))

    def test_tables_extracts_comma_sources(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders", "order_items"),
            tables("SELECT * FROM orders, order_items", "select"),
        )

    def test_tables_deduplicates_repeated_join_source(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders",),
            tables(
                "SELECT * FROM orders o JOIN orders o2 ON o.id = o2.id",
                "select",
            ),
        )

    def test_tables_preserves_distinct_case_spellings(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders", "ORDERS"),
            tables(
                "SELECT * FROM orders JOIN ORDERS "
                "ON orders.id = ORDERS.id",
                "select",
            ),
        )

    def test_tables_rejects_malformed_and_bind_source_fragments(self):
        from codewiki.index.sql import tables

        cases = [
            "SELECT * FROM foo-bar",
            "SELECT * FROM foo/bar",
            "SELECT * FROM foo?",
            "SELECT * FROM $1",
            "SELECT * FROM " + "$" + "{name}",
            "SELECT * FROM foo bar-baz",
        ]

        for statement in cases:
            with self.subTest(statement=statement):
                self.assertEqual((), tables(statement, "select"))

    def test_tables_collects_comma_sources_after_join_conditions(self):
        from codewiki.index.sql import tables

        cases = [
            "SELECT * FROM a JOIN b ON a.id = b.id, c",
            "SELECT * FROM a LEFT JOIN b ON a.id = b.id, c",
            (
                "SELECT * FROM a JOIN (SELECT * FROM b) q "
                "ON 1 = 1, c"
            ),
        ]

        for statement in cases:
            with self.subTest(statement=statement):
                self.assertEqual(
                    ("a", "b", "c"), tables(statement, "select"),
                )

    def test_tables_rejects_missing_non_plain_and_keyword_targets(self):
        from codewiki.index.sql import tables

        cases = [
            ("SELECT * FROM", "select", ()),
            (
                "SELECT * FROM (SELECT * FROM actual_table)",
                "select",
                ("actual_table",),
            ),
            ("SELECT * FROM (VALUES (?))", "select", ()),
            ("SELECT * FROM ?", "select", ()),
            ("SELECT * FROM :table_name", "select", ()),
            ("SELECT * FROM WHERE id = ?", "select", ()),
            ("SELECT * FROM NATURAL", "select", ()),
            ("SELECT * FROM DUAL", "select", ()),
            ("SELECT * FROM schema . orders", "select", ()),
            ("INSERT INTO (SELECT * FROM actual_table)", "insert", ()),
            ("INSERT INTO VALUES (?)", "insert", ()),
            ("UPDATE SET status = ?", "update", ()),
            ("UPDATE ? SET status = ?", "update", ()),
            ("DELETE FROM WHERE id = ?", "delete", ()),
        ]

        for statement, verb, expected in cases:
            with self.subTest(statement=statement, verb=verb):
                self.assertEqual(expected, tables(statement, verb))

    def test_tables_rejects_named_source_keywords(self):
        from codewiki.index.sql import tables

        keywords = [
            "SELECT", "WHERE", "SET", "VALUES", "ON", "USING", "JOIN",
            "LEFT", "RIGHT", "INNER", "OUTER", "FULL", "CROSS", "FETCH",
            "NATURAL", "AS", "DUAL",
        ]

        for keyword in keywords:
            with self.subTest(keyword=keyword):
                self.assertEqual(
                    (), tables("SELECT * FROM " + keyword, "select"),
                )

    def test_tables_preserves_lexical_order_across_nested_and_joined_sources(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("orders", "order_items", "shipments", "audit_log"),
            tables(
                "SELECT * FROM orders o "
                "JOIN (SELECT id FROM order_items) items ON ... "
                "JOIN shipments s ON ... "
                "WHERE o.id IN (SELECT id FROM audit_log)",
                "select",
            ),
        )

    def test_tables_filters_alias_paths_from_derived_and_comma_sources(self):
        from codewiki.index.sql import tables

        cases = [
            (
                "SELECT * FROM (SELECT id FROM orders) q "
                "JOIN q.items i",
                ("orders",),
            ),
            (
                "SELECT * FROM orders o, o.items i, order_items i2",
                ("orders", "order_items"),
            ),
        ]

        for statement, expected in cases:
            with self.subTest(statement=statement):
                self.assertEqual(expected, tables(statement, "select"))

    def test_tables_strips_quote_layers_and_deduplicates_returned_spellings(self):
        from codewiki.index.sql import tables

        self.assertEqual(
            ("Orders", "ORDERS"),
            tables(
                'SELECT * FROM "Orders" '
                "JOIN `Orders` o ON ... "
                "JOIN [Orders] o2 ON ... "
                "JOIN ORDERS o3 ON ...",
                "select",
            ),
        )

    def test_tables_refuses_invalid_join_sources(self):
        from codewiki.index.sql import tables

        cases = [
            ("SELECT * FROM orders JOIN (VALUES (?))", ("orders",)),
            ("SELECT * FROM orders JOIN ?", ("orders",)),
            ("SELECT * FROM orders JOIN :source", ("orders",)),
            ("SELECT * FROM orders JOIN", ("orders",)),
            ("SELECT * FROM orders JOIN WHERE id = ?", ("orders",)),
        ]

        for statement, expected in cases:
            with self.subTest(statement=statement):
                self.assertEqual(expected, tables(statement, "select"))

    def test_tables_refuses_invalid_into_and_update_targets(self):
        from codewiki.index.sql import tables

        cases = [
            ("INSERT INTO (VALUES (?))", "insert", ()),
            ("INSERT INTO ?", "insert", ()),
            ("INSERT INTO :target", "insert", ()),
            ("INSERT INTO", "insert", ()),
            ("INSERT INTO SELECT id FROM orders", "insert", ()),
            ("UPDATE (SELECT id FROM orders) SET status = ?", "update", ()),
            ("UPDATE ? SET status = ?", "update", ()),
            ("UPDATE :target SET status = ?", "update", ()),
            ("UPDATE", "update", ()),
            ("UPDATE SET status = ?", "update", ()),
        ]

        for statement, verb, expected in cases:
            with self.subTest(statement=statement, verb=verb):
                self.assertEqual(expected, tables(statement, verb))

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
