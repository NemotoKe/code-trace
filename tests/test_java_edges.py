from __future__ import annotations

import unittest


class JavaEdgeSymbolTests(unittest.TestCase):
    SOURCE = (
        "package com.acme;\n"
        "public class OrderService {\n"
        "    public OrderService() {}\n"
        "    public OrderService(String source) {}\n"
        "    public void cancel(String orderId) {}\n"
        "    public void cancel(String orderId, int reason) {}\n"
        "    static class Audit {\n"
        "        class Entry {\n"
        "            void record(String value) {}\n"
        "        }\n"
        "    }\n"
        "    public void multiline(\n"
        "        String orderId,\n"
        "        int reason\n"
        "    ) {\n"
        "    }\n"
        "    public void noise() {\n"
        "        new FakeThing();\n"
        "        String text = \"} class FakeType { void fake() {} }\";\n"
        "        // class CommentType { void commented() {} }\n"
        "    }\n"
        "}\n"
    )

    def test_nested_types_have_full_parent_chain_and_member_owner(self):
        from codewiki.index.symbols import extract

        symbols = extract("src/OrderService.java", "java", self.SOURCE)
        by_name = {(symbol.name, symbol.kind, symbol.line): symbol for symbol in symbols}
        audit = by_name[("Audit", "class", 7)]
        entry = by_name[("Entry", "class", 8)]
        record = by_name[("record", "method", 9)]
        self.assertEqual("com.acme.OrderService.Audit", audit.fqn)
        self.assertEqual("com.acme.OrderService", audit.owner_fqn)
        self.assertEqual("com.acme.OrderService.Audit.Entry", entry.fqn)
        self.assertEqual("com.acme.OrderService.Audit", entry.owner_fqn)
        self.assertEqual("com.acme.OrderService.Audit.Entry.record", record.fqn)
        self.assertEqual("com.acme.OrderService.Audit.Entry", record.owner_fqn)

    def test_constructors_and_overloads_are_distinct_and_parsed(self):
        from codewiki.index.symbols import extract

        symbols = extract("src/OrderService.java", "java", self.SOURCE)
        constructors = [symbol for symbol in symbols if symbol.kind == "constructor"]
        cancels = [symbol for symbol in symbols if symbol.name == "cancel"]
        self.assertEqual(2, len(constructors))
        self.assertEqual([0, 1], sorted(symbol.param_count for symbol in constructors))
        self.assertEqual(2, len(cancels))
        self.assertEqual({1, 2}, {symbol.param_count for symbol in cancels})
        self.assertEqual({("String",), ("String", "int")}, {
            tuple(symbol.params) for symbol in cancels
        })

    def test_multiline_parameters_are_recovered_from_complete_declaration(self):
        from codewiki.index.symbols import extract

        symbols = extract("src/OrderService.java", "java", self.SOURCE)
        multiline = [symbol for symbol in symbols if symbol.name == "multiline"]
        self.assertEqual(1, len(multiline))
        self.assertEqual(["String", "int"], multiline[0].params)
        self.assertEqual(2, multiline[0].param_count)
        self.assertEqual("CONFIRMED", multiline[0].confidence)
        self.assertIn("String orderId", multiline[0].signature)

    def test_java_declaration_guards_reject_calls_and_keep_valid_declarations(self):
        from codewiki.index.symbols import extract

        phantom_source = (
            "class A {\n"
            "  void m() {\n"
            "    retVal.putIfAbsent(\n"
            "        ManagedBeanSettings.BEAN_CONTAINER, new SpringBeanContainer(factory));\n"
            "        ManagedBeanSettings.BEAN_CONTAINER, new  SpringBeanContainer(factory));\n"
            "        ManagedBeanSettings.BEAN_CONTAINER, new\tSpringBeanContainer(factory));\n"
            "        ManagedBeanSettings.BEAN_CONTAINER, new /* comment */ SpringBeanContainer(factory));\n"
            "  }\n"
            "}\n"
        )
        phantom_names = {symbol.name for symbol in extract("A.java", "java", phantom_source)}
        self.assertNotIn("SpringBeanContainer", phantom_names)

        source = (
            "class Guards {\n"
            "  void calls() {\n"
            "    return foo();\n"
            "    throw new IllegalStateException();\n"
            "  }\n"
            "  public Response delete() { return null; }\n"
            "}\n"
            "interface Contract {\n"
            "  void doIt(String a) throws Exception;\n"
            "}\n"
        )
        symbols = extract("Guards.java", "java", source)
        names = {symbol.name for symbol in symbols}
        self.assertNotIn("foo", names)
        self.assertNotIn("IllegalStateException", names)
        delete = next(symbol for symbol in symbols if symbol.name == "delete")
        self.assertEqual("method", delete.kind)
        do_it = next(symbol for symbol in symbols if symbol.name == "doIt")
        self.assertEqual(["String"], do_it.params)
        self.assertEqual(1, do_it.param_count)
        self.assertEqual("CONFIRMED", do_it.confidence)

    def test_multiline_parameters_preserve_nested_types_and_modifiers(self):
        from codewiki.index.symbols import extract

        source = (
            "class Shapes {\n"
            "  void nested(\n"
            "      Map<Class<? extends IBase>, BaseRuntimeElement<?>> value\n"
            "  ) {}\n"
            "  void decorated(\n"
            "      @Nonnull String x,\n"
            "      final String[] names,\n"
            "      String... rest\n"
            "  ) {}\n"
            "  void zero(\n"
            "  ) {}\n"
            "  void broken(\n"
            "      String value\n"
            "}\n"
        )
        symbols = extract("Shapes.java", "java", source)
        by_name = {symbol.name: symbol for symbol in symbols}
        self.assertEqual(
            ["Map<Class<? extends IBase>, BaseRuntimeElement<?>>"],
            by_name["nested"].params,
        )
        self.assertEqual(1, by_name["nested"].param_count)
        self.assertEqual("CONFIRMED", by_name["nested"].confidence)
        self.assertEqual(
            ["String", "String[]", "String..."],
            by_name["decorated"].params,
        )
        self.assertEqual(3, by_name["decorated"].param_count)
        self.assertEqual("CONFIRMED", by_name["decorated"].confidence)
        self.assertEqual([], by_name["zero"].params)
        self.assertEqual(0, by_name["zero"].param_count)
        self.assertEqual("CONFIRMED", by_name["zero"].confidence)
        self.assertIsNone(by_name["broken"].params)
        self.assertIsNone(by_name["broken"].param_count)
        self.assertEqual("POSSIBLE", by_name["broken"].confidence)

    def test_parameter_annotations_are_removed_from_qualified_nested_and_type_use_forms(self):
        from codewiki.index.symbols import extract

        source = (
            "class AnnotatedParameters {\n"
            "  void annotated(\n"
            "      @javax.annotation.Nullable String value,\n"
            "      @Ann(a=f(1, 2), b=3) Map<String, Integer> values,\n"
            "      String @A names[],\n"
            "      String @pkg.TypeUse(value = {1, 2})... rest\n"
            "  ) {}\n"
            "}\n"
        )
        annotated = next(
            symbol for symbol in extract("AnnotatedParameters.java", "java", source)
            if symbol.name == "annotated"
        )
        self.assertEqual(
            ["String", "Map<String, Integer>", "String[]", "String..."],
            annotated.params,
        )
        self.assertEqual(4, annotated.param_count)
        self.assertEqual("CONFIRMED", annotated.confidence)

    def test_unbalanced_annotation_or_generic_nesting_stays_possible(self):
        from codewiki.index.symbols import extract

        source = (
            "class MalformedParameters {\n"
            "  void annotation(\n"
            "      @Ann(a=f(1, 2) String value\n"
            "  ) {}\n"
            "  void generic(\n"
            "      Map<String value\n"
            "  ) {}\n"
            "}\n"
        )
        methods = {
            symbol.name: symbol
            for symbol in extract("MalformedParameters.java", "java", source)
            if symbol.kind == "method"
        }
        self.assertEqual({"annotation", "generic"}, set(methods))
        for method in methods.values():
            self.assertIsNone(method.params)
            self.assertIsNone(method.param_count)
            self.assertEqual("POSSIBLE", method.confidence)

    def test_unbalanced_parenthesis_nesting_stays_possible(self):
        from codewiki.index.symbols import extract

        source = (
            "class MalformedParentheses {\n"
            "  void extraClose(String value)) {}\n"
            "}\n"
        )
        method = next(
            symbol for symbol in extract("MalformedParentheses.java", "java", source)
            if symbol.name == "extraClose"
        )
        self.assertIsNone(method.params)
        self.assertIsNone(method.param_count)
        self.assertEqual("POSSIBLE", method.confidence)

    def test_multiline_parameter_parsing_uses_uncapped_text(self):
        from codewiki.index.symbols import MAX_SIGNATURE, extract

        parameters = ",\n".join(
            "      String value%d" % index for index in range(40)
        )
        source = "class Long {\n  void many(\n%s\n  ) {}\n}\n" % parameters
        many = next(symbol for symbol in extract("Long.java", "java", source)
                    if symbol.name == "many")
        self.assertEqual(["String"] * 40, many.params)
        self.assertEqual(40, many.param_count)
        self.assertEqual("CONFIRMED", many.confidence)
        self.assertLessEqual(len(many.signature), MAX_SIGNATURE)

    def test_comments_strings_and_constructor_calls_are_not_symbols(self):
        from codewiki.index.symbols import extract

        symbols = extract("src/OrderService.java", "java", self.SOURCE)
        names = {symbol.name for symbol in symbols}
        self.assertNotIn("FakeThing", names)
        self.assertNotIn("FakeType", names)
        self.assertNotIn("CommentType", names)
        self.assertNotIn("commented", names)

    def test_all_required_java_type_kinds_and_top_level_fqns(self):
        from codewiki.index.symbols import extract

        source = (
            "package com.types;\n"
            "interface Gateway {}\n"
            "enum State { OPEN, CLOSED }\n"
            "record Entry(String value) {}\n"
            "@interface Marker {}\n"
        )
        symbols = extract("Types.java", "java", source)
        self.assertEqual(
            {
                ("Gateway", "interface", "com.types.Gateway"),
                ("State", "enum", "com.types.State"),
                ("Entry", "record", "com.types.Entry"),
                ("Marker", "annotation", "com.types.Marker"),
            },
            {(symbol.name, symbol.kind, symbol.fqn) for symbol in symbols},
        )

    def test_package_private_constructor_is_not_lost(self):
        from codewiki.index.symbols import extract

        symbols = extract("Plain.java", "java", "class Plain {\n  Plain(int value) {}\n}\n")
        constructors = [symbol for symbol in symbols if symbol.kind == "constructor"]
        self.assertEqual(1, len(constructors))
        self.assertEqual(["int"], constructors[0].params)

    def test_parameter_types_keep_generic_commas_and_java_type_shapes(self):
        from codewiki.index.symbols import extract

        source = (
            "class Shapes {\n"
            "  void convert(final Map<String, Integer> values, String[] names, int... flags) {}\n"
            "}\n"
        )
        symbols = extract("Shapes.java", "java", source)
        convert = next(symbol for symbol in symbols if symbol.name == "convert")
        self.assertEqual(
            ["Map<String, Integer>", "String[]", "int..."], convert.params
        )
        self.assertEqual(3, convert.param_count)
        self.assertEqual("void convert(final Map<String, Integer> values, String[] names, int... flags) {}",
                         convert.signature)

    def test_same_line_method_annotation_is_supported(self):
        from codewiki.index.symbols import extract

        symbols = extract(
            "Annotated.java", "java",
            "class Annotated {\n"
            "  @Override public String toString() { return \"x\"; }\n"
            "}\n",
        )
        method = next(symbol for symbol in symbols if symbol.name == "toString")
        self.assertEqual("Annotated.toString", method.fqn)

    def test_one_line_top_level_type_contains_member_method(self):
        from codewiki.index.symbols import extract

        symbols = extract(
            "A.java", "java", "package p;\npublic class A { void m() {} }\n"
        )
        method = next(symbol for symbol in symbols if symbol.name == "m")
        self.assertEqual("p.A.m", method.fqn)
        self.assertEqual("p.A", method.owner_fqn)
        self.assertEqual(2, method.line)
        self.assertEqual(2, method.end_line)
        self.assertEqual([], method.params)
        self.assertEqual("CONFIRMED", method.confidence)

    def test_one_line_nested_type_contains_member_with_parent_fqn(self):
        from codewiki.index.symbols import extract

        source = (
            "package p;\n"
            "class Outer {\n"
            "  class Inner { void n() {} }\n"
            "}\n"
        )
        symbols = extract("Outer.java", "java", source)
        method = next(symbol for symbol in symbols if symbol.name == "n")
        self.assertEqual("p.Outer.Inner.n", method.fqn)
        self.assertEqual("p.Outer.Inner", method.owner_fqn)
        self.assertEqual(3, method.line)
        self.assertEqual(3, method.end_line)

    def test_multiple_one_line_members_keep_individual_signatures_and_params(self):
        from codewiki.index.symbols import extract

        symbols = extract(
            "A.java", "java", "class A { void a() {} void b(int value) {} }\n"
        )
        methods = {symbol.name: symbol for symbol in symbols if symbol.kind == "method"}
        self.assertEqual([], methods["a"].params)
        self.assertEqual(["int"], methods["b"].params)
        self.assertEqual("void a() {}", methods["a"].signature)
        self.assertEqual("void b(int value) {}", methods["b"].signature)

    def test_local_classes_and_members_are_not_separate_symbols(self):
        from codewiki.index.symbols import extract

        source = "class A { void m() { class Local { void x(){} } } }\n"
        symbols = extract("A.java", "java", source)
        fqns = {symbol.fqn for symbol in symbols}
        self.assertIn("A", fqns)
        self.assertIn("A.m", fqns)
        self.assertNotIn("A.Local", fqns)
        self.assertNotIn("A.Local.x", fqns)

    def test_initializer_local_classes_and_members_are_not_separate_symbols(self):
        from codewiki.index.symbols import extract

        source = "class A { static { class Local { void x(){} } } }\n"
        fqns = {symbol.fqn for symbol in extract("A.java", "java", source)}
        self.assertEqual({"A"}, fqns)

    def test_unresolved_large_type_still_contains_all_members(self):
        import codewiki.index.symbols as symbol_module

        source = (
            "class Large {\n"
            "  void before() {}\n"
            + "\n".join(
                "  // padding line %d" % index for index in range(3005)
            )
            + "\n"
            + "  void after(String value) {}\n"
            + "  class Nested {\n"
            + "    void nested(String value) {}\n"
            + "  }\n"
            + "}\n"
        )
        original_bound = symbol_module.MAX_BODY_SCAN_LINES
        try:
            self.assertEqual(10000, original_bound)
            symbol_module.MAX_BODY_SCAN_LINES = 3
            symbols = symbol_module.extract("Large.java", "java", source)
        finally:
            symbol_module.MAX_BODY_SCAN_LINES = original_bound

        by_fqn = {symbol.fqn: symbol for symbol in symbols}
        large = by_fqn["Large"]
        self.assertIsNone(large.end_line)
        self.assertEqual("UNRESOLVED", large.confidence)
        self.assertEqual(
            {"Large", "Large.before", "Large.after", "Large.Nested", "Large.Nested.nested"},
            set(by_fqn),
        )
        self.assertGreater(by_fqn["Large.after"].line, 3000)
        self.assertEqual(["String"], by_fqn["Large.after"].params)
        self.assertEqual("Large", by_fqn["Large.after"].owner_fqn)
        self.assertEqual("Large", by_fqn["Large.Nested"].owner_fqn)
        self.assertGreater(by_fqn["Large.Nested.nested"].line, 3000)
        self.assertEqual("Large.Nested", by_fqn["Large.Nested.nested"].owner_fqn)
        self.assertEqual(["String"], by_fqn["Large.Nested.nested"].params)

    def test_compact_commented_braces_keep_nested_type_and_member_owner(self):
        from codewiki.index.symbols import extract

        source = "class Outer { /* } { */ class Inner { void x(String value) {} } }\n"
        symbols = extract("Outer.java", "java", source)
        inner = next(symbol for symbol in symbols if symbol.fqn == "Outer.Inner")
        member = next(symbol for symbol in symbols if symbol.name == "x")
        self.assertEqual("Outer", inner.owner_fqn)
        self.assertEqual("Outer.Inner.x", member.fqn)
        self.assertEqual(["String"], member.params)
        self.assertEqual("CONFIRMED", member.confidence)

    def test_comments_do_not_shift_same_line_signature_parameters(self):
        from codewiki.index.symbols import extract

        source = (
            "class Comments { /* before */ @pkg.sub.Ann(value = 1) "
            "void run(/* inside */ final String value /* after */, int[] values) {} "
            "}\n"
        )
        run = next(symbol for symbol in extract("Comments.java", "java", source)
                   if symbol.name == "run")
        self.assertEqual("Comments.run", run.fqn)
        self.assertEqual(["String", "int[]"], run.params)
        self.assertEqual(2, run.param_count)
        self.assertEqual("CONFIRMED", run.confidence)

    def test_generic_constructors_methods_and_dotted_annotations_are_indexed(self):
        from codewiki.index.symbols import extract

        source = (
            "class Generic {\n"
            "  @pkg.sub.Before(value = 1)\n"
            "  <T> Generic(T value) {}\n"
            "  @pkg.sub.Same(value = factory(1, 2)) public <T> T convert(T value) {}\n"
            "}\n"
        )
        symbols = extract("Generic.java", "java", source)
        constructor = next(symbol for symbol in symbols if symbol.kind == "constructor")
        method = next(symbol for symbol in symbols if symbol.name == "convert")
        self.assertEqual("Generic.Generic", constructor.fqn)
        self.assertEqual(["T"], constructor.params)
        self.assertEqual("CONFIRMED", constructor.confidence)
        self.assertEqual("Generic.convert", method.fqn)
        self.assertEqual(["T"], method.params)
        self.assertEqual("CONFIRMED", method.confidence)


if __name__ == "__main__":
    unittest.main()
