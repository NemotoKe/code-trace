from __future__ import annotations

import unittest


class JavaAnnotationExtractorTests(unittest.TestCase):
    def _extract(self, source):
        from codewiki.index.annotation_refs import extract
        from codewiki.index.symbols import extract as extract_symbols

        path = "src/demo/OrderService.java"
        symbols = extract_symbols(path, "java", source)
        return extract(path, "java", source, symbols)

    def test_fixture_records_type_and_method_annotations_in_source_order(self):
        source = (
            "package p;\n"
            "\n"
            "@Service\n"
            "@Transactional(readOnly = true)\n"
            "public class OrderService {\n"
            "\n"
            "    @Override\n"
            "    @GetMapping(\n"
            "        value = \"/orders/{id}\"\n"
            "    )\n"
            "    public Order find(@Nonnull String id) {\n"
            "        // @NotAnAnnotation\n"
            "        String s = \"@AlsoNot\";\n"
            "        return null;\n"
            "    }\n"
            "\n"
            "    public void plain() {}\n"
            "}\n"
        )

        self.assertEqual(
            [
                ("p.OrderService", "class", "Service", 3, "@Service"),
                ("p.OrderService", "class", "Transactional", 4,
                 "@Transactional(readOnly = true)"),
                ("p.OrderService.find", "method", "Override", 7,
                 "@Override"),
                ("p.OrderService.find", "method", "GetMapping", 8,
                 "@GetMapping( value = \"/orders/{id}\" )"),
            ],
            [
                (ref.owner_fqn, ref.owner_kind, ref.name, ref.line, ref.raw)
                for ref in self._extract(source)
            ],
        )

    def test_stacked_annotations_on_one_class_are_separate_rows(self):
        refs = self._extract(
            "@First\n"
            "@second\n"
            "class Example {}\n"
        )

        self.assertEqual(
            [("Example", "class", "First"),
             ("Example", "class", "second")],
            [(ref.owner_fqn, ref.owner_kind, ref.name) for ref in refs],
        )

    def test_parenthesised_annotation_keeps_comma_string_and_nested_parentheses(self):
        refs = self._extract(
            '@Route(value = "a,b", predicate = check(foo(bar)))\n'
            "class Example {}\n"
        )

        self.assertEqual(
            [('@Route(value = "a,b", predicate = check(foo(bar)))',
              "Route")],
            [(ref.raw, ref.name) for ref in refs],
        )

    def test_parameter_annotation_is_ignored(self):
        refs = self._extract(
            "class Example {\n"
            "    void run(@Nonnull String value) {}\n"
            "}\n"
        )

        self.assertEqual([], refs)

    def test_comments_and_string_literals_cannot_create_annotations(self):
        refs = self._extract(
            "/* @BlockComment */\n"
            "class Example {\n"
            "    // @LineComment\n"
            "    String value = \"@StringLiteral\";\n"
            "    void run() {}\n"
            "}\n"
        )

        self.assertEqual([], refs)

    def test_non_java_input_is_empty(self):
        from codewiki.index.annotation_refs import extract

        self.assertEqual(
            [], extract("Example.kt", "kotlin", "@A class Example", [])
        )

    def test_package_import_exposes_annotation_refs_module(self):
        from codewiki.index import annotation_refs

        self.assertTrue(hasattr(annotation_refs, "extract"))


if __name__ == "__main__":
    unittest.main()
