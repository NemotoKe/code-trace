from __future__ import annotations

import os
import tempfile
import unittest


class MultiprocessProbeTests(unittest.TestCase):
    def test_401_one_line_java_files_have_identical_symbols_and_imports_with_jobs_one_and_two(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-many-") as root:
            source_dir = os.path.join(root, "src")
            os.mkdir(source_dir)
            for index in range(401):
                name = "C%03d" % index
                with open(os.path.join(source_dir, name + ".java"), "w", encoding="utf-8") as stream:
                    stream.write(
                        "package p;\nimport p.Dependency;\npublic class %s { void m() {} }\n"
                        % name
                    )
            first_out = os.path.join(root, "first")
            second_out = os.path.join(root, "second")
            first = pipeline.run(root, first_out, jobs=1)
            second = pipeline.run(root, second_out, jobs=2)
            self.assertEqual(802, first.symbols_found)
            self.assertEqual(802, second.symbols_found)
            first_connection = open_index(first.db_path)
            second_connection = open_index(second.db_path)
            try:
                first_rows = first_connection.execute(
                    "SELECT symbol_id, name, kind, fqn, line, end_line "
                    "FROM symbols ORDER BY symbol_id"
                ).fetchall()
                second_rows = second_connection.execute(
                    "SELECT symbol_id, name, kind, fqn, line, end_line "
                    "FROM symbols ORDER BY symbol_id"
                ).fetchall()
                first_imports = first_connection.execute(
                    "SELECT path, line, column, raw, form, name, target_fqn, "
                    "internal_target, outcome, candidates "
                    "FROM imports JOIN files USING(file_id) "
                    "ORDER BY path, line, column"
                ).fetchall()
                second_imports = second_connection.execute(
                    "SELECT path, line, column, raw, form, name, target_fqn, "
                    "internal_target, outcome, candidates "
                    "FROM imports JOIN files USING(file_id) "
                    "ORDER BY path, line, column"
                ).fetchall()
            finally:
                first_connection.close()
                second_connection.close()
            self.assertEqual(first_rows, second_rows)
            self.assertEqual(first_imports, second_imports)
            self.assertEqual(401, len(first_imports))
