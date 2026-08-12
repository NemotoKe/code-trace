from __future__ import annotations

import os
import unittest

from tests.fixture import fixture_directory, write_fixture


class ScanTests(unittest.TestCase):
    def test_records_java_and_non_java_metadata_and_detects_generated_and_test(self):
        from codewiki.config import Config
        from codewiki.index.scan import analyzable, scan

        with fixture_directory() as root:
            write_fixture(root)
            records, skipped = scan(root, Config())
            by_path = {record.path: record for record in records}
            self.assertEqual({
                "java", "xml", "sql", "properties",
            }, {record.language for record in records})
            self.assertTrue(by_path["generated/Generated.java"].is_generated)
            self.assertTrue(by_path["tests/java/TestOrder.java"].is_test)
            self.assertEqual([], [
                record.path for record in analyzable(records)
                if record.path == "generated/Generated.java"
            ])
            self.assertIn("generated", skipped)
            self.assertEqual(sorted(record.path for record in records), [
                record.path for record in records
            ])

    def test_read_text_uses_repository_relative_path(self):
        from codewiki.config import Config
        from codewiki.index.scan import read_text, scan

        with fixture_directory() as root:
            write_fixture(root)
            records, _ = scan(root, Config())
            java = next(record for record in records if record.path.endswith("Order.java"))
            self.assertIn("class Order", read_text(root, java.path))
            self.assertFalse(os.path.isabs(java.path))


if __name__ == "__main__":
    unittest.main()
