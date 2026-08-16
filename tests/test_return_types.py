from __future__ import annotations

import unittest

from codewiki.index.symbols import Symbol


def make_symbol(kind, signature):
    return Symbol(
        "src/Example.java",
        "example",
        kind,
        "example.Example.example",
        "example.Example",
        "example",
        [],
        0,
        signature,
        1,
        1,
        "CONFIRMED",
    )


class ReturnTypeTests(unittest.TestCase):
    def test_r1_contract(self):
        from codewiki.index.returntypes import return_type

        cases = [
            ("method", "void run() {", "void"),
            (
                "method",
                "public static boolean isLoggable(String a, int b) {",
                "boolean",
            ),
            (
                "method",
                "protected final synchronized String name() {",
                "String",
            ),
            ("method", "public List<String> names() {", "List"),
            (
                "method",
                "public <T> List<T> map(Function<T> f) {",
                "List",
            ),
            ("method", "public Map.Entry<K, V> entry() {", "Map.Entry"),
            ("method", "public int[] values() {", "int[]"),
            ("method", "@Override public String toString() {", "String"),
            ("constructor", "public Foo(int x) {", None),
        ]

        for kind, signature, expected in cases:
            with self.subTest(kind=kind, signature=signature):
                self.assertEqual(expected, return_type(make_symbol(kind, signature)))

    def test_rules_and_malformed_signatures(self):
        from codewiki.index.returntypes import return_type

        self.assertEqual(
            "Map.Entry[][]",
            return_type(make_symbol(
                "method",
                "@Name(value = \"x\") @Other public protected private "
                "static final abstract synchronized native default strictfp "
                "transient volatile <T extends Comparable<T>> "
                "Map.Entry<K, V>[][] entry() {",
            )),
        )

        for signature in ("", "public {", "public static {", "public class Foo {"):
            with self.subTest(signature=signature):
                self.assertIsNone(return_type(make_symbol("method", signature)))

    def test_non_methods_and_type_use_annotations(self):
        from codewiki.index.returntypes import return_type

        cases = [
            (
                "record",
                "public record CanonicalUrlParts("
                "String url, Optional<String> versionId) {",
                None,
            ),
            (
                "constructor",
                "public record CanonicalUrlParts("
                "String url, Optional<String> versionId) {",
                None,
            ),
            ("class", "public class Foo {", None),
            (
                "method",
                "public <T> @Nonnull Optional<T> getAdapter("
                "Object theObject, Class<T> theTargetType) {",
                "Optional",
            ),
            (
                "method",
                "default <T> @Nonnull Optional<T> getAdapter("
                "@Nonnull Class<T> theTargetType) {",
                "Optional",
            ),
        ]

        for kind, signature, expected in cases:
            with self.subTest(kind=kind, signature=signature):
                self.assertEqual(expected, return_type(make_symbol(kind, signature)))


if __name__ == "__main__":
    unittest.main()
