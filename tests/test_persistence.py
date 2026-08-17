from __future__ import annotations

import hashlib
import os
import unittest

from tests.fixture import fixture_directory, write_fixture


def snapshot(root):
    result = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in (".codewiki", "index-out"))
        for filename in sorted(filenames):
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with open(path, "rb") as stream:
                result[rel] = hashlib.sha256(stream.read()).hexdigest()
    return result


class PersistenceTests(unittest.TestCase):
    def test_pipeline_persists_records_and_keeps_source_bytes_unchanged(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with fixture_directory() as root:
            write_fixture(root)
            before = snapshot(root)
            timings = {}
            result = pipeline.run(root, os.path.join(root, "index-out"), jobs=1, timings=timings)
            self.assertEqual(10, result.files_scanned)
            self.assertEqual(7, result.files_analyzed)
            self.assertGreater(result.symbols_found, 0)
            self.assertTrue(timings["scan"] >= 0)
            self.assertTrue(timings["symbols"] >= 0)
            self.assertTrue(timings["persist"] >= 0)
            self.assertTrue(timings["total"] >= 0)
            self.assertEqual(before, snapshot(root))

            connection = open_index(result.db_path)
            self.assertEqual(10, connection.execute("SELECT count(*) FROM files").fetchone()[0])
            generated = connection.execute(
                "SELECT package, is_generated FROM files "
                "WHERE path = 'generated/Generated.java'"
            ).fetchone()
            is_test = connection.execute(
                "SELECT is_test FROM files WHERE path = 'tests/java/TestOrder.java'"
            ).fetchone()[0]
            self.assertEqual("generated", generated[0])
            self.assertEqual(1, generated[1])
            self.assertEqual(1, is_test)
            self.assertEqual(1, connection.execute(
                "SELECT count(*) FROM symbols WHERE name = 'Generated'"
            ).fetchone()[0])

    def test_repeated_indexing_has_same_logical_rows_and_symbol_ids(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with fixture_directory() as root:
            write_fixture(root)
            out = os.path.join(root, "index-out")
            first = pipeline.run(root, out, jobs=1)
            connection = open_index(first.db_path)
            first_files = connection.execute(
                "SELECT file_id, path, language, package, lines, sha256, is_test, is_generated "
                "FROM files ORDER BY file_id"
            ).fetchall()
            first_symbols = connection.execute(
                "SELECT symbol_id, file_id, name, kind, fqn, owner_fqn, params, param_count, "
                "signature, line, end_line, confidence FROM symbols ORDER BY symbol_id"
            ).fetchall()
            first_meta = dict(connection.execute("SELECT key, value FROM meta"))
            connection.close()
            second = pipeline.run(root, out, jobs=1)
            connection = open_index(second.db_path)
            self.assertEqual(first_files, connection.execute(
                "SELECT file_id, path, language, package, lines, sha256, is_test, is_generated "
                "FROM files ORDER BY file_id"
            ).fetchall())
            self.assertEqual(first_symbols, connection.execute(
                "SELECT symbol_id, file_id, name, kind, fqn, owner_fqn, params, param_count, "
                "signature, line, end_line, confidence FROM symbols ORDER BY symbol_id"
            ).fetchall())
            second_meta = dict(connection.execute("SELECT key, value FROM meta"))
            self.assertEqual(first_meta["schema_version"], second_meta["schema_version"])
            self.assertEqual(first_meta["repo_root"], second_meta["repo_root"])
            self.assertNotEqual("", second_meta["generated_at"])


if __name__ == "__main__":
    unittest.main()
