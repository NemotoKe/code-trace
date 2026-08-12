from __future__ import annotations

import unittest


class BasicJavaSymbolTests(unittest.TestCase):
    def test_extracts_package_type_and_method_with_brace_end(self):
        from codewiki.index.symbols import extract

        source = (
            "package com.acme;\n"
            "public class OrderService {\n"
            "    public void cancel(String orderId) {\n"
            "        if (orderId == null) { return; }\n"
            "    }\n"
            "}\n"
        )
        symbols = extract("src/OrderService.java", "java", source)
        by_name = {(symbol.name, symbol.kind): symbol for symbol in symbols}
        self.assertEqual("com.acme", symbols[0].package)
        self.assertEqual("com.acme.OrderService", by_name[("OrderService", "class")].fqn)
        method = by_name[("cancel", "method")]
        self.assertEqual("com.acme.OrderService.cancel", method.fqn)
        self.assertEqual("com.acme.OrderService", method.owner_fqn)
        self.assertEqual(["String"], method.params)
        self.assertEqual(1, method.param_count)
        self.assertEqual(3, method.line)
        self.assertEqual(5, method.end_line)
        self.assertEqual("CONFIRMED", method.confidence)

    def test_syntax_without_package_has_type_and_method(self):
        from codewiki.index.symbols import extract

        symbols = extract(
            "NoPackage.java",
            "java",
            "class NoPackage {\n  int size() { return 1; }\n}\n",
        )
        self.assertEqual(
            ["NoPackage", "NoPackage.size"],
            [symbol.fqn for symbol in symbols],
        )

    def test_package_declaration_inside_block_comment_is_ignored(self):
        from codewiki.index.symbols import extract

        source = (
            "/*\n"
            "package fake;\n"
            "*/\n"
            "package real;\n"
            "class A {}\n"
        )
        symbols = extract("A.java", "java", source)
        self.assertEqual("real", symbols[0].package)
        self.assertEqual("real.A", symbols[0].fqn)


if __name__ == "__main__":
    unittest.main()
