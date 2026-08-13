from __future__ import annotations

import unittest


class JavaTextBlockMaskingTests(unittest.TestCase):
    def _assert_masks(self, cases):
        from codewiki.index.symbols import strip_noise
        from codewiki.index.supertypes import _mask_line

        state = False
        for line, expected_strip, expected_mask, expected_state in cases:
            stripped, next_state = strip_noise(line, state)
            masked, mask_state = _mask_line(line, state)
            self.assertEqual(expected_strip, stripped, line)
            self.assertEqual(expected_mask, masked, line)
            self.assertEqual(expected_state, next_state, line)
            self.assertEqual(expected_state, mask_state, line)
            self.assertIs(int, type(next_state), line)
            self.assertIs(int, type(mask_state), line)
            self.assertEqual(len(line), len(masked), line)
            state = next_state

    def test_multiline_text_block_suppresses_declarations_and_hapi_phantoms(self):
        from codewiki.index.symbols import extract
        from codewiki.index.supertypes import extract as extract_supertypes

        self._assert_masks([
            ('String s = """', "String s =  ", "String s =    ", 2),
            ("class Fake {", "", "            ", 2),
            ('""";', " ;", "   ;", 0),
        ])

        source = (
            "class Real {\n"
            '    String input = """\n'
            "        class Fake extends Bogus {\n"
            "            void fake() {}\n"
            '    """;\n'
            "}\n"
        )
        symbols = extract("Real.java", "java", source)
        self.assertEqual(["Real"], [symbol.name for symbol in symbols])
        refs = extract_supertypes("Real.java", "java", source, symbols)
        self.assertEqual([], refs)

        # These are the source lines from the measured HAPI FHIR failure.
        hapi_source = (
            "public class SqlUtilTest {\n"
            "\tpublic void testParseCreateTableStatementPrimaryKey_PostgresFormat(String theLine) {\n"
            '\t\tString input = """\n'
            "\t\t\tcreate table HFJ_IDX_CMB_TOK_NU (\n"
            "\t\t\t    PID bigint not null,\n"
            "\t\t\t    IDX_STRING varchar(500) not null,\n"
            '\t\t""";\n'
            "\t}\n"
            "}\n"
        )
        hapi_symbols = extract("SqlUtilTest.java", "java", hapi_source)
        hapi_names = {symbol.name for symbol in hapi_symbols}
        self.assertNotIn("HFJ_IDX_CMB_TOK_NU", hapi_names)
        self.assertNotIn("varchar", hapi_names)

    def test_ordinary_string_literal_keeps_existing_behavior(self):
        self._assert_masks([
            (
                'String s = "just a string";',
                "String s =  ;",
                "String s =                ;",
                0,
            ),
        ])

    def test_invalid_same_line_triple_quotes_are_not_a_text_block(self):
        self._assert_masks([
            (
                'String s = """abc""";',
                "String s =    ;",
                "String s =          ;",
                0,
            ),
        ])

    def test_escaped_triple_quotes_do_not_close_a_text_block(self):
        escaped_delimiter = r'he said \""" '
        self._assert_masks([
            ('String q = """', "String q =  ", "String q =    ", 2),
            (escaped_delimiter, "", " " * len(escaped_delimiter), 2),
            ("still text", "", "          ", 2),
            ('""";', " ;", "   ;", 0),
        ])

    def test_closing_delimiter_on_its_own_line_ends_the_text_block(self):
        self._assert_masks([
            ('x = """', "x =  ", "x =    ", 2),
            ("class Fake {", "", "            ", 2),
            ('"""', " ", "   ", 0),
            ("class Real {}", "class Real {}", "class Real {}", 0),
        ])

    def test_code_after_same_line_closing_delimiter_is_visible_again(self):
        self._assert_masks([
            ('x = """', "x =  ", "x =    ", 2),
            ("class Fake {", "", "            ", 2),
            ('""" + suffix;', "  + suffix;", "    + suffix;", 0),
            ("void after() {}", "void after() {}", "void after() {}", 0),
        ])

    def test_plain_quotes_inside_text_block_do_not_close_it(self):
        from codewiki.index.symbols import extract, strip_noise

        source = (
            "package p;\n"
            "public class T {\n"
            '    String json = """\n'
            '        {"name": "x"}\n'
            "        void ghost(String a) {\n"
            '        {"end": "y"}\n'
            '        """;\n'
            "    void real() {}\n"
            "}\n"
        )

        state = False
        cleaned, state = strip_noise('    String json = """', state)
        self.assertEqual("    String json =  ", cleaned)
        self.assertEqual(2, state)
        cleaned, state = strip_noise('        {"name": "x"}', state)
        self.assertEqual("", cleaned)
        self.assertEqual(2, state)
        cleaned, state = strip_noise('        """;', state)
        self.assertEqual(" ;", cleaned)
        self.assertEqual(0, state)

        symbols = extract("T.java", "java", source)
        self.assertEqual(
            ["T", "real"],
            [symbol.name for symbol in symbols],
        )
        self.assertNotIn("ghost", {symbol.name for symbol in symbols})


if __name__ == "__main__":
    unittest.main()
