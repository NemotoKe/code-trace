from __future__ import annotations

import unittest


class JavaImportParserTests(unittest.TestCase):
    def test_parses_all_java_import_forms_in_source_order(self):
        from codewiki.index.imports import parse_imports

        source = (
            "package demo;\n"
            "import a.b.Type;\n"
            "import a.b.*;\n"
            "import static a.b.Codes.PAID;\n"
            "import static a.b.Codes.*;\n"
        )

        records = parse_imports("src/demo/Use.java", source)

        self.assertEqual(
            ["single", "wildcard", "static_single", "static_wildcard"],
            [record.form for record in records],
        )
        self.assertEqual(
            [
                (2, "import a.b.Type;", "a.b.Type"),
                (3, "import a.b.*;", "a.b"),
                (4, "import static a.b.Codes.PAID;", "a.b.Codes.PAID"),
                (5, "import static a.b.Codes.*;", "a.b.Codes"),
            ],
            [(record.line, record.raw, record.name) for record in records],
        )
        self.assertEqual(
            "src/demo/Use.java", records[0].path
        )
        self.assertEqual(
            [False, False, True, True],
            [record.is_static for record in records],
        )
        self.assertEqual(
            [False, True, False, True],
            [record.is_wildcard for record in records],
        )

    def test_ignores_comments_and_java_literals(self):
        from codewiki.index.imports import parse_imports

        source = (
            "/* import fake.block.Type; */\n"
            "String text = \"import fake.string.Type;\";\n"
            "char quote = '/'; // import fake.line.Type;\n"
            "import real.Type; /* import fake.trailing.Type; */\n"
            "// import fake.comment.Type;\n"
        )

        records = parse_imports("Use.java", source)

        self.assertEqual(1, len(records))
        self.assertEqual("real.Type", records[0].name)
        self.assertEqual(4, records[0].line)
        self.assertEqual("import real.Type;", records[0].raw)

    def test_allows_comments_between_import_tokens_without_leaking_trailing_comments(self):
        from codewiki.index.imports import parse_imports

        records = parse_imports(
            "Use.java",
            "/* before */ import /* before */ a /* middle */ . Type; /* after */\n"
            "import static a.b.Codes.*; // after\n",
        )

        self.assertEqual(
            [("a.Type", "single"), ("a.b.Codes", "static_wildcard")],
            [(record.name, record.form) for record in records],
        )
        self.assertEqual(
            ["import /* before */ a /* middle */ . Type;", "import static a.b.Codes.*;"],
            [record.raw for record in records],
        )

    def test_parses_multiple_import_statements_on_one_line(self):
        from codewiki.index.imports import parse_imports

        records = parse_imports(
            "Use.java", "import b.Second; import a.First;\n"
        )

        self.assertEqual(
            [(1, "b.Second"), (1, "a.First")],
            [(record.line, record.name) for record in records],
        )

    def test_accepts_a_missing_semicolon_without_crossing_the_line(self):
        from codewiki.index.imports import parse_imports

        records = parse_imports(
            "Use.java", "import a.Type\nnot an import a.Other\n"
        )

        self.assertEqual(1, len(records))
        self.assertEqual("import a.Type", records[0].raw)


if __name__ == "__main__":
    unittest.main()
