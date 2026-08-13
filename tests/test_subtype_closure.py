from __future__ import annotations

import os
import sqlite3
import unittest

from tests.fixture import fixture_directory, write_fixture


class SubtypeClosureTests(unittest.TestCase):
    def setUp(self):
        from codewiki.index import pipeline

        self.directory = fixture_directory()
        self.root = self.directory.name
        write_fixture(self.root)
        result = pipeline.run(self.root, os.path.join(self.root, "index-out"), jobs=1)
        self.db_path = result.db_path

    def tearDown(self):
        self.directory.cleanup()

    def _add_java(self, relative_path, source):
        path = os.path.join(self.root, relative_path)
        parent = os.path.dirname(path)
        if not os.path.isdir(parent):
            os.makedirs(parent)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(source)

    def _reindex(self):
        from codewiki.index import pipeline

        result = pipeline.run(self.root, os.path.join(self.root, "extra-index-out"), jobs=1)
        self.db_path = result.db_path

    def _insert_cycle_rows(self):
        connection = sqlite3.connect(self.db_path)
        try:
            file_ids = {}
            for name in ("A", "B", "C"):
                cursor = connection.execute(
                    "INSERT INTO files(path, language, package, lines, sha256, "
                    "is_test, is_generated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "src/cycle/%s.java" % name,
                        "java",
                        "cycle",
                        1,
                        "cycle-%s" % name,
                        0,
                        0,
                    ),
                )
                file_ids[name] = cursor.lastrowid
                connection.execute(
                    "INSERT INTO symbols(file_id, name, kind, fqn, owner_fqn, "
                    "params, param_count, signature, line, end_line, confidence) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        file_ids[name], name, "class", "cycle." + name, None,
                        None, None, "class " + name, 1, 1, "CERTAIN",
                    ),
                )

            edges = (
                ("B", "A", 2),
                ("C", "B", 3),
                ("B", "C", 4),
            )
            for owner, target, line in edges:
                connection.execute(
                    "INSERT INTO supertypes(file_id, owner_fqn, line, relation, "
                    "raw, name, target_fqn, rule, outcome, candidates) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        file_ids[owner], "cycle." + owner, line, "extends",
                        target, target, "cycle." + target, 1, "resolved", "[]",
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def test_direct_subtype_has_metadata_and_distance(self):
        from codewiki.query.types import SubtypeResult, subtypes

        result = subtypes(self.db_path, "com.acme.OrderDao")

        self.assertEqual(
            [SubtypeResult(
                "com.acme.OrderRepository",
                "class",
                "src/com/acme/OrderRepository.java",
                2,
                1,
                "implements",
            )],
            result,
        )
        self.assertEqual(
            {
                "fqn": "com.acme.OrderRepository",
                "kind": "class",
                "path": "src/com/acme/OrderRepository.java",
                "line": 2,
                "distance": 1,
                "relation": "implements",
            },
            result[0].as_dict(),
        )

    def test_unknown_type_and_leaf_have_empty_closures(self):
        from codewiki.query.types import subtypes

        self.assertEqual([], subtypes(self.db_path, "com.example.NoSuchType"))
        self.assertEqual([], subtypes(self.db_path, "com.acme.OrderRepository"))

    def test_transitive_subtypes_have_distance_and_stable_order(self):
        self._add_java(
            "src/graph/Base.java",
            "package graph;\npublic interface Base {}\n",
        )
        self._add_java(
            "src/graph/Mid.java",
            "package graph;\npublic interface Mid extends Base {}\n",
        )
        self._add_java(
            "src/graph/Leaf.java",
            "package graph;\npublic class Leaf extends Mid {}\n",
        )
        self._reindex()

        from codewiki.query.types import subtypes

        result = subtypes(self.db_path, "graph.Base")

        self.assertEqual(
            ["graph.Mid", "graph.Leaf"],
            [item.fqn for item in result],
        )
        self.assertEqual(
            [(1, "extends"), (2, "extends")],
            [(item.distance, item.relation) for item in result],
        )

    def test_two_paths_emit_subtype_once_at_shortest_distance(self):
        self._add_java(
            "src/paths/Base.java",
            "package paths;\npublic interface Base {}\n",
        )
        self._add_java(
            "src/paths/Mid.java",
            "package paths;\npublic interface Mid extends Base {}\n",
        )
        self._add_java(
            "src/paths/Leaf.java",
            "package paths;\npublic class Leaf extends Mid implements Base {}\n",
        )
        self._reindex()

        from codewiki.query.types import subtypes

        result = subtypes(self.db_path, "paths.Base")

        self.assertEqual(
            ["paths.Leaf", "paths.Mid"],
            [item.fqn for item in result],
        )
        leaf = next(item for item in result if item.fqn == "paths.Leaf")
        self.assertEqual(1, leaf.distance)
        self.assertEqual("implements", leaf.relation)

    def test_cycle_terminates_and_excludes_queried_type(self):
        self._insert_cycle_rows()

        from codewiki.query.types import subtypes

        result = subtypes(self.db_path, "cycle.A")

        self.assertEqual(["cycle.B", "cycle.C"], [item.fqn for item in result])
        self.assertEqual([1, 2], [item.distance for item in result])


if __name__ == "__main__":
    unittest.main()
