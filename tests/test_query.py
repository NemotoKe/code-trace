from __future__ import annotations

import os
import unittest

from tests.fixture import fixture_directory, write_fixture


class QueryTests(unittest.TestCase):
    def setUp(self):
        from codewiki.index import pipeline

        self.directory = fixture_directory()
        self.root = self.directory.name
        write_fixture(self.root)
        self.result = pipeline.run(self.root, os.path.join(self.root, "index-out"), jobs=1)

    def tearDown(self):
        self.directory.cleanup()

    def test_exact_and_shorthand_forms_preserve_overload_ambiguity(self):
        from codewiki.query.symbols import search_path

        exact = search_path(self.result.db_path, "com.acme.OrderService.cancel")
        shorthand = search_path(self.result.db_path, "OrderService.cancel")
        self.assertEqual(2, exact.count)
        self.assertFalse(exact.truncated)
        self.assertEqual(
            ["String", "String",],
            sorted(result["params"][0] for result in exact.results),
        )
        self.assertEqual(2, shorthand.count)
        self.assertEqual(
            {1, 2}, {result["param_count"] for result in shorthand.results}
        )
        self.assertTrue(all(
            result["fqn"] == "com.acme.OrderService.cancel"
            for result in shorthand.results
        ))

    def test_nested_and_duplicate_simple_queries(self):
        from codewiki.query.symbols import search_path

        nested = search_path(self.result.db_path, "OrderService.Audit.Entry.record")
        self.assertEqual(1, nested.count)
        self.assertEqual("com.acme.OrderService.Audit.Entry.record", nested.results[0]["fqn"])
        duplicate = search_path(self.result.db_path, "Order")
        self.assertEqual(2, duplicate.count)
        self.assertEqual({"com.acme.Order", "com.other.Order"}, {
            result["fqn"] for result in duplicate.results
        })

    def test_kind_limit_and_result_shape(self):
        from codewiki.query.symbols import RESULT_KEYS, search_path

        limited = search_path(
            self.result.db_path, "OrderService.cancel", kind="method", limit=1
        )
        self.assertEqual(1, limited.count)
        self.assertTrue(limited.truncated)
        self.assertEqual(RESULT_KEYS, tuple(limited.results[0].keys()))
        self.assertEqual("method", limited.results[0]["kind"])
        self.assertEqual("src/com/acme/OrderService.java", limited.results[0]["path"])
        self.assertEqual(6, limited.results[0]["line"])
        self.assertIsInstance(limited.results[0]["params"], list)

    def test_no_match_is_zero_without_error(self):
        from codewiki.query.symbols import search_path

        result = search_path(self.result.db_path, "does.not.exist")
        self.assertEqual({"query": "does.not.exist", "count": 0,
                          "truncated": False, "results": []}, result.as_dict())

    def test_dotted_queries_are_case_sensitive(self):
        from codewiki.query.symbols import search_path

        correct = search_path(self.result.db_path, "OrderService.cancel")
        wrong_case = search_path(self.result.db_path, "orderservice.cancel")
        self.assertEqual(2, correct.count)
        self.assertEqual(0, wrong_case.count)
        self.assertEqual([], wrong_case.results)
        self.assertEqual(2, search_path(self.result.db_path, "Order").count)
        self.assertEqual(0, search_path(self.result.db_path, "order").count)

    def test_query_does_not_open_source_files(self):
        from codewiki.query.symbols import search_path

        os.remove(os.path.join(self.root, "src/com/acme/OrderService.java"))
        result = search_path(self.result.db_path, "OrderService")
        self.assertGreater(result.count, 0)


if __name__ == "__main__":
    unittest.main()
