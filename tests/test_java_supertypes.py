from __future__ import annotations

import unittest


class JavaSupertypeExtractorTests(unittest.TestCase):
    def _extract(self, source):
        from codewiki.index.symbols import extract as extract_symbols
        from codewiki.index.supertypes import extract

        path = "src/demo/Example.java"
        symbols = extract_symbols(path, "java", source)
        return extract(path, "java", source, symbols)

    def test_class_generic_extends_is_one_raw_supertype(self):
        refs = self._extract("class Foo extends Base<Bar, Baz> {\n}\n")

        self.assertEqual(
            [("Foo", "extends", "Base<Bar, Baz>", "Base", 1)],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_type_parameter_bound_is_not_a_supertype(self):
        refs = self._extract(
            "class Foo<T extends Comparable<T>> extends Base {\n}\n"
        )

        self.assertEqual(
            [("Foo", "extends", "Base", "Base", 1)],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_implements_generic_and_simple_types_are_two_entries(self):
        refs = self._extract(
            "class Foo<K, V> implements Map<K, V>, Serializable {\n}\n"
        )

        self.assertEqual(
            [
                ("Foo", "implements", "Map<K, V>", "Map", 1),
                ("Foo", "implements", "Serializable", "Serializable", 1),
            ],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_permits_list_is_not_part_of_extends(self):
        refs = self._extract(
            "sealed class Foo extends Base permits A, B {\n}\n"
        )

        self.assertEqual(
            [("Foo", "extends", "Base", "Base", 1)],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_interface_extends_has_one_entry_per_interface(self):
        refs = self._extract("interface I extends A, B {\n}\n")

        self.assertEqual(
            [
                ("I", "extends", "A", "A", 1),
                ("I", "extends", "B", "B", 1),
            ],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_enum_implements_is_extracted(self):
        refs = self._extract("enum E implements I { ALPHA, BETA }\n")

        self.assertEqual(
            [("E", "implements", "I", "I", 1)],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_record_components_are_not_supertypes(self):
        refs = self._extract(
            "record R(int a, String b) implements I {\n}\n"
        )

        self.assertEqual(
            [("R", "implements", "I", "I", 1)],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_annotation_type_declares_no_supertype(self):
        refs = self._extract("@interface Ann {\n}\n")

        self.assertEqual([], refs)

    def test_class_without_clauses_has_no_supertypes(self):
        refs = self._extract("class Foo {\n}\n")

        self.assertEqual([], refs)

    def test_multiline_header_uses_name_lines_and_keeps_clause_order(self):
        refs = self._extract(
            "public class OrderServiceImpl\n"
            "        extends AbstractService<Order>\n"
            "        implements OrderService,\n"
            "                   AutoCloseable {\n"
            "}\n"
        )

        self.assertEqual(
            [
                ("OrderServiceImpl", "extends",
                 "AbstractService<Order>", "AbstractService", 2),
                ("OrderServiceImpl", "implements",
                 "OrderService", "OrderService", 3),
                ("OrderServiceImpl", "implements",
                 "AutoCloseable", "AutoCloseable", 4),
            ],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_comments_cannot_create_a_fake_clause(self):
        refs = self._extract(
            "public class Foo /* extends Bogus */ implements Bar {\n}\n"
        )

        self.assertEqual(
            [("Foo", "implements", "Bar", "Bar", 1)],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_nested_type_uses_its_own_owner_fqn(self):
        refs = self._extract(
            "package com.acme;\n"
            "public class Outer extends A {\n"
            "    static class Inner implements B {}\n"
            "}\n"
        )

        self.assertEqual(
            [
                ("com.acme.Outer", "extends", "A", "A", 2),
                ("com.acme.Outer.Inner", "implements", "B", "B", 3),
            ],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_raw_keeps_qualified_type_arguments_and_name_strips_them(self):
        refs = self._extract(
            "class Foo implements com.acme.Base<String, java.util.List<Integer>> {\n"
            "}\n"
        )

        self.assertEqual(
            [(
                "Foo", "implements",
                "com.acme.Base<String, java.util.List<Integer>>",
                "com.acme.Base", 1,
            )],
            [
                (ref.owner_fqn, ref.relation, ref.raw, ref.name, ref.line)
                for ref in refs
            ],
        )

    def test_non_java_input_is_empty(self):
        from codewiki.index.supertypes import extract

        self.assertEqual(
            [], extract("Example.kt", "kotlin", "class Foo : Bar", [])
        )

    def test_output_is_source_order_independent_of_symbol_input_order(self):
        from codewiki.index.symbols import extract as extract_symbols
        from codewiki.index.supertypes import extract

        path = "Example.java"
        source = "class Outer extends A { class Inner implements B {} }\n"
        symbols = extract_symbols(path, "java", source)
        refs = extract(path, "java", source, list(reversed(symbols)))

        self.assertEqual(
            [("Outer", "extends", "A"),
             ("Outer.Inner", "implements", "B")],
            [(ref.owner_fqn, ref.relation, ref.name) for ref in refs],
        )


if __name__ == "__main__":
    unittest.main()
