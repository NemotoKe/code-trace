from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest


def _write_file(root, relative_path, source):
    path = os.path.join(root, relative_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(source)


class EntrypointIntegrationTests(unittest.TestCase):
    def test_pipeline_classifies_main_servlet_transitive_servlet_and_jaxrs(self):
        sources = {
            "src/entry/MainApp.java": (
                "package entry;\n"
                "\n"
                "public class MainApp {\n"
                "    public static void main(String[] args) {}\n"
                "}\n"
            ),
            "src/entry/DirectServlet.java": (
                "package entry;\n"
                "\n"
                "import javax.servlet.http.HttpServlet;\n"
                "\n"
                "public class DirectServlet extends HttpServlet {\n"
                "    public void doGet() {}\n"
                "    void helper() {}\n"
                "}\n"
            ),
            "src/entry/BaseServlet.java": (
                "package entry;\n"
                "\n"
                "import javax.servlet.http.HttpServlet;\n"
                "\n"
                "public class BaseServlet extends HttpServlet {}\n"
            ),
            "src/entry/TransitiveServlet.java": (
                "package entry;\n"
                "\n"
                "public class TransitiveServlet extends BaseServlet {\n"
                "    public void doPost() {}\n"
                "}\n"
            ),
            "src/entry/Resource.java": (
                "package entry;\n"
                "\n"
                "@Path(\"/resource\")\n"
                "public class Resource {\n"
                "    @GET\n"
                "    public void get() {}\n"
                "    public void unannotated() {}\n"
                "}\n"
            ),
            "src/entry/SpringController.java": (
                "package entry;\n"
                "\n"
                "@RestController\n"
                "public class SpringController {\n"
                "    @GetMapping(\"/items\")\n"
                "    public void mapped() {}\n"
                "}\n"
            ),
            "src/javax/servlet/http/HttpServlet.java": (
                "package javax.servlet.http;\n"
                "\n"
                "public class HttpServlet {}\n"
            ),
        }
        with tempfile.TemporaryDirectory(prefix="codewiki-entrypoint-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-entrypoint-out-") as out:
            for relative_path, source in sources.items():
                _write_file(root, relative_path, source)

            from codewiki.index import pipeline

            result = pipeline.run(root, out, jobs=1)
            connection = sqlite3.connect(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT f.path, e.method_fqn, e.owner_fqn, e.kind, "
                    "e.reason, e.line "
                    "FROM entrypoints AS e JOIN files AS f USING(file_id) "
                    "ORDER BY e.entrypoint_id"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                (
                    "src/entry/DirectServlet.java",
                    "entry.DirectServlet.doGet", "entry.DirectServlet",
                    "servlet", "servlet:doGet", 6,
                ),
                (
                    "src/entry/MainApp.java", "entry.MainApp.main",
                    "entry.MainApp", "main", "main_signature", 4,
                ),
                (
                    "src/entry/Resource.java", "entry.Resource.get",
                    "entry.Resource", "jaxrs", "jaxrs:GET", 6,
                ),
                (
                    "src/entry/TransitiveServlet.java",
                    "entry.TransitiveServlet.doPost", "entry.TransitiveServlet",
                    "servlet", "servlet:doPost", 4,
                ),
            ],
            rows,
        )
        self.assertEqual(4, result.entrypoints_found)
        self.assertNotIn(
            "entry.DirectServlet.helper",
            [row[1] for row in rows],
        )
        self.assertNotIn(
            "entry.Resource.unannotated",
            [row[1] for row in rows],
        )
        self.assertNotIn(
            "entry.SpringController.mapped",
            [row[1] for row in rows],
        )

    def test_main_signature_rejects_int_no_args_and_accepts_varargs(self):
        sources = {
            "src/entry/IntMain.java": (
                "package entry;\n"
                "\n"
                "public class IntMain {\n"
                "    public static void main(int count) {}\n"
                "}\n"
            ),
            "src/entry/NoArgMain.java": (
                "package entry;\n"
                "\n"
                "public class NoArgMain {\n"
                "    public void main() {}\n"
                "}\n"
            ),
            "src/entry/VarargsMain.java": (
                "package entry;\n"
                "\n"
                "public class VarargsMain {\n"
                "    public static void main(String... args) {}\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory(prefix="codewiki-main-signature-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-main-signature-out-") as out:
            for relative_path, source in sources.items():
                _write_file(root, relative_path, source)

            from codewiki.index import pipeline

            result = pipeline.run(root, out, jobs=1)
            connection = sqlite3.connect(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT f.path, e.method_fqn, e.kind, e.reason, e.line "
                    "FROM entrypoints AS e JOIN files AS f USING(file_id) "
                    "ORDER BY e.entrypoint_id"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                (
                    "src/entry/VarargsMain.java", "entry.VarargsMain.main",
                    "main", "main_signature", 4,
                ),
            ],
            rows,
        )
        self.assertEqual(1, result.entrypoints_found)

    def test_external_httpservlet_marker_and_transitive_servlet_chain(self):
        sources = {
            "src/p/DirectServlet.java": (
                "package p;\n"
                "\n"
                "class DirectServlet extends HttpServlet {\n"
                "    void doGet() {}\n"
                "}\n"
            ),
            "src/p/BaseServlet.java": (
                "package p;\n"
                "\n"
                "class BaseServlet extends HttpServlet {\n"
                "    void doPost() {}\n"
                "}\n"
            ),
            "src/p/ChildServlet.java": (
                "package p;\n"
                "\n"
                "class ChildServlet extends BaseServlet {\n"
                "    void doDelete() {}\n"
                "}\n"
            ),
            "src/p/OtherExternal.java": (
                "package p;\n"
                "\n"
                "class OtherExternalUser extends OtherExternal {\n"
                "    void doGet() {}\n"
                "}\n"
            ),
        }
        with tempfile.TemporaryDirectory(prefix="codewiki-external-servlet-repo-") as root, \
                tempfile.TemporaryDirectory(prefix="codewiki-external-servlet-out-") as out:
            for relative_path, source in sources.items():
                _write_file(root, relative_path, source)

            from codewiki.index import pipeline

            result = pipeline.run(root, out, jobs=1)
            connection = sqlite3.connect(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT f.path, e.method_fqn, e.kind, e.reason, e.line "
                    "FROM entrypoints AS e JOIN files AS f USING(file_id) "
                    "ORDER BY e.entrypoint_id"
                ).fetchall()
                servlet_supertype_rows = connection.execute(
                    "SELECT s.name, s.outcome, s.target_fqn "
                    "FROM supertypes AS s WHERE s.name = 'HttpServlet' "
                    "ORDER BY s.owner_fqn"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(
            [
                ("src/p/BaseServlet.java", "p.BaseServlet.doPost",
                 "servlet", "servlet:doPost", 4),
                ("src/p/ChildServlet.java", "p.ChildServlet.doDelete",
                 "servlet", "servlet:doDelete", 4),
                ("src/p/DirectServlet.java", "p.DirectServlet.doGet",
                 "servlet", "servlet:doGet", 4),
            ],
            rows,
        )
        self.assertEqual(3, result.entrypoints_found)
        self.assertEqual(2, len(servlet_supertype_rows))
        self.assertTrue(all(
            outcome in ("external", "unresolved") and target_fqn is None
            for _name, outcome, target_fqn in servlet_supertype_rows
        ))
        self.assertNotIn(
            "p.OtherExternalUser.doGet",
            [row[1] for row in rows],
        )

    def test_schema_contains_entrypoints_columns_indexes_and_new_version(self):
        from codewiki.store.db import connect, initialize

        connection = connect(":memory:")
        try:
            initialize(connection, repo_root="/repo")
            self.assertEqual(
                [
                    "entrypoint_id", "file_id", "method_fqn", "owner_fqn",
                    "kind", "reason", "line",
                ],
                [row[1] for row in connection.execute(
                    "PRAGMA table_info(entrypoints)"
                )],
            )
            self.assertEqual(
                {
                    "idx_entrypoints_method",
                    "idx_entrypoints_kind",
                    "idx_entrypoints_file",
                },
                {
                    row[1] for row in connection.execute(
                        "PRAGMA index_list(entrypoints)"
                    )
                },
            )
            self.assertEqual(
                "5",
                connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()[0],
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
