from __future__ import annotations

import json
import os
import tempfile
import unittest


def write_file(root, relative_path, contents):
    path = os.path.join(root, relative_path)
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write(contents)


class JavaImportResolutionTests(unittest.TestCase):
    def test_index_persists_import_forms_and_database_resolution_rows(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-imports-") as root:
            write_file(root, "src/p/Type.java", "package p;\npublic class Type {}\n")
            write_file(root, "src/p/Codes.java", "package p;\npublic class Codes {}\n")
            write_file(
                root,
                "src/app/Use.java",
                "package app;\n"
                "import p.Type;\n"
                "import p.*;\n"
                "import static p.Codes.PAID;\n"
                "import static p.Codes.*;\n"
                "public class Use {}\n",
            )
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)
            connection = open_index(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT line, raw, form, name, target_fqn, internal_target, outcome FROM imports "
                    "JOIN files USING(file_id) WHERE path = ? ORDER BY line",
                    ("src/app/Use.java",),
                ).fetchall()
                self.assertEqual(
                    [
                        (2, "import p.Type;", "single", "p.Type", "p.Type", "p.Type", "resolved"),
                        (3, "import p.*;", "wildcard", "p", "p", "p", "resolved"),
                        (4, "import static p.Codes.PAID;", "static_single", "p.Codes.PAID", "p.Codes.PAID", "p.Codes", "resolved"),
                        (5, "import static p.Codes.*;", "static_wildcard", "p.Codes", "p.Codes", "p.Codes", "resolved"),
                    ],
                    rows,
                )
                self.assertGreater(
                    connection.execute("SELECT count(*) FROM type_resolutions").fetchone()[0],
                    0,
                )
            finally:
                connection.close()

    def test_resolution_precedence_and_database_only_query(self):
        from codewiki.index import pipeline
        from codewiki.query.types import resolve_type_path

        with tempfile.TemporaryDirectory(prefix="codewiki-resolution-") as root:
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import p.explicit.Thing;\n"
                "import p.wild.*;\n"
                "public class Use { class Thing {} }\n"
            ))
            write_file(root, "src/app/ExplicitUse.java", (
                "package app;\n"
                "import p.explicit.Thing;\n"
                "public class ExplicitUse {}\n"
            ))
            write_file(root, "src/app/SamePackageUse.java", (
                "package app;\npublic class SamePackageUse {}\n"
            ))
            write_file(root, "src/q/WildcardUse.java", (
                "package q;\n"
                "import p.wild.*;\n"
                "public class WildcardUse {}\n"
            ))
            write_file(root, "src/p/explicit/Thing.java", (
                "package p.explicit;\npublic class Thing {}\n"
            ))
            write_file(root, "src/p/wild/Thing.java", (
                "package p.wild;\npublic class Thing {}\n"
            ))
            write_file(root, "src/app/Thing.java", "package app;\npublic class Thing {}\n")
            pipeline.run(root, os.path.join(root, "out"), jobs=1)
            db_path = os.path.join(root, "out", "index.sqlite3")

            nested = resolve_type_path(db_path, "Thing", "src/app/Use.java")
            self.assertEqual("app.Use.Thing", nested.resolved_fqn)
            self.assertEqual(1, nested.rule)
            self.assertEqual("resolved", nested.outcome)

            explicit = resolve_type_path(db_path, "Thing", "src/app/ExplicitUse.java")
            self.assertEqual("p.explicit.Thing", explicit.resolved_fqn)
            self.assertEqual(2, explicit.rule)

            same_package = resolve_type_path(db_path, "Thing", "src/app/SamePackageUse.java")
            self.assertEqual("app.Thing", same_package.resolved_fqn)
            self.assertEqual(3, same_package.rule)

            wildcard = resolve_type_path(db_path, "Thing", "src/q/WildcardUse.java")
            self.assertEqual("p.wild.Thing", wildcard.resolved_fqn)
            self.assertEqual(4, wildcard.rule)

            os.remove(os.path.join(root, "src/q/WildcardUse.java"))
            after_delete = resolve_type_path(db_path, "Thing", "src/q/WildcardUse.java")
            self.assertEqual(wildcard.as_dict(), after_delete.as_dict())

    def test_ambiguity_and_external_internal_looking_failures_are_conservative(self):
        from codewiki.index import pipeline
        from codewiki.query.types import resolve_type_path

        with tempfile.TemporaryDirectory(prefix="codewiki-ambiguity-") as root:
            write_file(root, "src/app/External.java", (
                "package app;\n"
                "import java.util.List;\n"
                "import p.internal.Missing;\n"
                "public class External {}\n"
            ))
            write_file(root, "src/q/Wild.java", (
                "package q;\n"
                "import p.one.*;\n"
                "import p.two.*;\n"
                "public class Wild {}\n"
            ))
            write_file(root, "src/app/Same.java", (
                "package app;\npublic class Same {}\n"
            ))
            write_file(root, "src/p/internal/Present.java", (
                "package p.internal;\npublic class Present {}\n"
            ))
            write_file(root, "src/p/one/Duplicate.java", (
                "package p.one;\npublic class Duplicate {}\n"
            ))
            write_file(root, "src/p/two/Duplicate.java", (
                "package p.two;\npublic class Duplicate {}\n"
            ))
            write_file(root, "src/app/Duplicate.java", "package app;\npublic class Duplicate {}\n")
            write_file(root, "src/app/OtherDuplicate.java", "package app;\npublic class Duplicate {}\n")
            pipeline.run(root, os.path.join(root, "out"), jobs=1)
            db_path = os.path.join(root, "out", "index.sqlite3")

            wildcard = resolve_type_path(db_path, "Duplicate", "src/q/Wild.java")
            self.assertEqual("unresolved", wildcard.outcome)
            self.assertIsNone(wildcard.resolved_fqn)
            self.assertEqual(4, wildcard.rule)
            self.assertEqual(["p.one.Duplicate", "p.two.Duplicate"], wildcard.candidates)

            same_package = resolve_type_path(db_path, "Duplicate", "src/app/Same.java")
            self.assertEqual("unresolved", same_package.outcome)
            self.assertEqual(3, same_package.rule)
            self.assertEqual(["app.Duplicate", "app.Duplicate"], same_package.candidates)

            external = resolve_type_path(db_path, "List", "src/app/External.java")
            self.assertEqual("external", external.outcome)
            self.assertIsNone(external.resolved_fqn)
            self.assertIsNone(external.rule)
            self.assertEqual(["java.util.List"], external.candidates)

            internal_missing = resolve_type_path(db_path, "Missing", "src/app/External.java")
            self.assertEqual("unresolved", internal_missing.outcome)
            self.assertEqual(2, internal_missing.rule)
            self.assertEqual(["p.internal.Missing"], internal_missing.candidates)

    def test_external_wildcard_can_be_reported_without_source_access(self):
        from codewiki.index import pipeline
        from codewiki.query.types import resolve_type_path

        with tempfile.TemporaryDirectory(prefix="codewiki-external-wildcard-") as root:
            write_file(root, "Use.java", (
                "package app;\nimport java.util.*;\npublic class Use {}\n"
            ))
            pipeline.run(root, os.path.join(root, "out"), jobs=1)
            result = resolve_type_path(
                os.path.join(root, "out", "index.sqlite3"), "List", "Use.java"
            )
            self.assertEqual("external", result.outcome)
            self.assertIsNone(result.rule)
            self.assertEqual(["java.util.List"], result.candidates)

    def test_query_result_has_stable_json_shape(self):
        from codewiki.index import pipeline
        from codewiki.query.types import resolve_type_path

        with tempfile.TemporaryDirectory(prefix="codewiki-shape-") as root:
            write_file(root, "Use.java", "package p;\npublic class Use {}\n")
            pipeline.run(root, os.path.join(root, "out"), jobs=1)
            result = resolve_type_path(
                os.path.join(root, "out", "index.sqlite3"), "NoSuchType", "Use.java"
            )
            self.assertEqual(
                {"file", "name", "resolved_fqn", "rule", "outcome", "candidates"},
                set(result.as_dict()),
            )
            self.assertEqual("Use.java", result.file)
            self.assertEqual("NoSuchType", result.name)
            self.assertIsNone(result.resolved_fqn)
            self.assertIsNone(result.rule)
            self.assertEqual("unresolved", result.outcome)
            self.assertIsInstance(json.loads(json.dumps(result.as_dict()))["candidates"], list)

    def test_meta_persists_form_outcome_counts_and_internal_rate(self):
        from codewiki.index import pipeline
        from codewiki.query.types import resolve_type_path
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-rate-") as root:
            imports = [
                "import p.Type;",
                "import p.Missing;",
                "import java.util.List;",
                "import java.util.Map;",
                "import java.time.Instant;",
                "import org.slf4j.Logger;",
                "import org.slf4j.MDC;",
                "import javax.annotation.Nullable;",
                "import static java.lang.Math.PI;",
                "import static java.lang.Math.*;",
            ]
            write_file(root, "src/p/Type.java", "package p;\npublic class Type {}\n")
            write_file(root, "src/app/Use.java", "package app;\n" + "\n".join(imports) +
                        "\npublic class Use {}\n")
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)
            connection = open_index(result.db_path)
            try:
                meta = dict(connection.execute("SELECT key, value FROM meta"))
            finally:
                connection.close()
            self.assertEqual("10", meta["import_count"])
            self.assertEqual("0.500000", meta["internal_resolution_rate"])
            self.assertEqual("8", meta["import_form_single"])
            self.assertEqual("1", meta["import_form_static_single"])
            self.assertEqual("1", meta["import_form_static_wildcard"])
            self.assertEqual("1", meta["import_outcome_resolved"])
            self.assertEqual("1", meta["import_outcome_unresolved"])
            self.assertEqual("8", meta["import_outcome_external"])
            self.assertEqual("0", meta["import_outcome_excluded"])
            self.assertEqual({
                "resolved": 3,
                "unresolved": 1,
                "external": 6,
                "excluded": 0,
            }, json.loads(meta["type_resolution_outcomes"]))
            for outcome, count in {
                "resolved": 3,
                "unresolved": 1,
                "external": 6,
                "excluded": 0,
            }.items():
                self.assertEqual(
                    str(count), meta["type_resolution_outcome_" + outcome]
                )

            external_type = resolve_type_path(
                os.path.join(root, "out", "index.sqlite3"),
                "List", "src/app/Use.java",
            )
            self.assertEqual("external", external_type.outcome)

    def test_import_classification_uses_existing_longest_package_prefix(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-import-prefix-") as root:
            write_file(root, "src/org/hl7/fhir/r4/model/Patient.java", (
                "package org.hl7.fhir.r4.model;\npublic class Patient {}\n"
            ))
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import org.junit.jupiter.api.Test;\n"
                "import org.hl7.fhir.r4.model.Patient;\n"
                "public class Use {}\n"
            ))
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)
            connection = open_index(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT name, outcome FROM imports ORDER BY line"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual([
                ("org.junit.jupiter.api.Test", "external"),
                ("org.hl7.fhir.r4.model.Patient", "resolved"),
            ], rows)

    def test_import_with_unrelated_com_package_is_external(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-import-com-") as root:
            write_file(root, "src/com/acme/Existing.java", (
                "package com.acme;\npublic class Existing {}\n"
            ))
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import com.google.common.collect.Lists;\n"
                "public class Use {}\n"
            ))
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)
            connection = open_index(result.db_path)
            try:
                outcome = connection.execute(
                    "SELECT outcome FROM imports WHERE name = ?",
                    ("com.google.common.collect.Lists",),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual("external", outcome)

    def test_import_from_generated_only_package_is_excluded(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-import-excluded-") as root:
            write_file(root, "generated/Thing.java", (
                "// Code generated by fixture\n"
                "package com.acme.gen;\npublic class Thing {}\n"
            ))
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import com.acme.gen.Thing;\n"
                "public class Use {}\n"
            ))
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)
            connection = open_index(result.db_path)
            try:
                outcome = connection.execute(
                    "SELECT outcome FROM imports WHERE name = ?",
                    ("com.acme.gen.Thing",),
                ).fetchone()[0]
                type_outcome = connection.execute(
                    "SELECT outcome FROM type_resolutions WHERE name = ?",
                    ("Thing",),
                ).fetchone()[0]
                symbol_count = connection.execute(
                    "SELECT count(*) FROM symbols WHERE fqn = ?",
                    ("com.acme.gen.Thing",),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual("excluded", outcome)
            self.assertEqual("excluded", type_outcome)
            self.assertEqual(0, symbol_count)

            from codewiki.query.types import resolve_type_path

            queried = resolve_type_path(
                result.db_path, "Thing", "src/app/Use.java"
            )
            self.assertEqual("excluded", queried.outcome)
            self.assertEqual(2, queried.rule)
            self.assertEqual(["com.acme.gen.Thing"], queried.candidates)

    def test_missing_type_classification_uses_exact_packages_and_wildcard_precedence(self):
        from codewiki.index import pipeline
        from codewiki.query.types import resolve_type_path

        with tempfile.TemporaryDirectory(prefix="codewiki-type-prefix-") as root:
            write_file(root, "src/org/hl7/fhir/Present.java", (
                "package org.hl7.fhir;\npublic class Present {}\n"
            ))
            write_file(root, "src/internal/package-info.java", (
                "package internal;\n"
            ))
            write_file(root, "generated/Only.java", (
                "// Code generated by fixture\n"
                "package com.acme.generated;\npublic class Only {}\n"
            ))
            write_file(root, "src/app/Explicit.java", (
                "package app;\n"
                "import org.junit.jupiter.api.Test;\n"
                "public class Explicit {}\n"
            ))
            write_file(root, "src/app/ExternalWild.java", (
                "package app;\n"
                "import org.junit.jupiter.*;\n"
                "public class ExternalWild {}\n"
            ))
            write_file(root, "src/app/ExcludedWild.java", (
                "package app;\n"
                "import com.acme.generated.*;\n"
                "import java.util.*;\n"
                "public class ExcludedWild {}\n"
            ))
            write_file(root, "src/app/MixedWild.java", (
                "package app;\n"
                "import internal.*;\n"
                "import com.acme.generated.*;\n"
                "import java.util.*;\n"
                "public class MixedWild {}\n"
            ))
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)

            explicit = resolve_type_path(
                result.db_path, "Test", "src/app/Explicit.java"
            )
            self.assertEqual("external", explicit.outcome)
            self.assertIsNone(explicit.rule)
            self.assertEqual(["org.junit.jupiter.api.Test"], explicit.candidates)

            external_wild = resolve_type_path(
                result.db_path, "Missing", "src/app/ExternalWild.java"
            )
            self.assertEqual("external", external_wild.outcome)
            self.assertIsNone(external_wild.rule)
            self.assertEqual(["org.junit.jupiter.Missing"], external_wild.candidates)

            excluded_wild = resolve_type_path(
                result.db_path, "Missing", "src/app/ExcludedWild.java"
            )
            self.assertEqual("excluded", excluded_wild.outcome)
            self.assertEqual(4, excluded_wild.rule)
            self.assertEqual([
                "com.acme.generated.Missing", "java.util.Missing"
            ], excluded_wild.candidates)

            mixed_wild = resolve_type_path(
                result.db_path, "Missing", "src/app/MixedWild.java"
            )
            self.assertEqual("unresolved", mixed_wild.outcome)
            self.assertEqual(4, mixed_wild.rule)
            self.assertEqual([
                "com.acme.generated.Missing", "internal.Missing",
                "java.util.Missing",
            ], mixed_wild.candidates)

    def test_analyzable_existing_and_missing_types_keep_resolved_and_unresolved(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-import-package-") as root:
            write_file(root, "src/com/acme/real/Present.java", (
                "package com.acme.real;\npublic class Present {}\n"
            ))
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import com.acme.real.Present;\n"
                "import com.acme.real.Missing;\n"
                "public class Use {}\n"
            ))
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)
            connection = open_index(result.db_path)
            try:
                rows = connection.execute(
                    "SELECT name, outcome FROM imports ORDER BY line"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual([
                ("com.acme.real.Present", "resolved"),
                ("com.acme.real.Missing", "unresolved"),
            ], rows)

    def test_meta_reports_two_resolved_two_unresolved_five_external_three_excluded(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-import-counts-") as root:
            write_file(root, "src/internal/one/One.java", (
                "package internal.one;\npublic class One {}\n"
            ))
            write_file(root, "src/internal/two/Two.java", (
                "package internal.two;\npublic class Two {}\n"
            ))
            write_file(root, "src/missing/Types.java", (
                "package missing;\npublic class Types {}\n"
            ))
            for index in range(1, 4):
                write_file(root, "generated/Excluded%d.java" % index, (
                    "// Code generated by fixture\n"
                    "package generated.pkg%d;\npublic class Excluded%d {}\n"
                    % (index, index)
                ))
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import internal.one.One;\n"
                "import internal.two.Two;\n"
                "import missing.MissingOne;\n"
                "import missing.MissingTwo;\n"
                "import java.util.List;\n"
                "import java.util.Map;\n"
                "import org.junit.jupiter.api.Test;\n"
                "import com.google.common.collect.Lists;\n"
                "import net.example.Missing;\n"
                "import generated.pkg1.Excluded1;\n"
                "import generated.pkg2.Excluded2;\n"
                "import generated.pkg3.Excluded3;\n"
                "public class Use {}\n"
            ))
            result = pipeline.run(root, os.path.join(root, "out"), jobs=1)
            self.assertEqual({
                "resolved": 2,
                "unresolved": 2,
                "external": 5,
                "excluded": 3,
            }, result.import_outcomes)
            self.assertEqual(0.5, result.internal_resolution_rate)
            connection = open_index(result.db_path)
            try:
                meta = dict(connection.execute("SELECT key, value FROM meta"))
            finally:
                connection.close()
            self.assertEqual("0.500000", meta["internal_resolution_rate"])
            self.assertEqual({
                "resolved": 2,
                "unresolved": 2,
                "external": 5,
                "excluded": 3,
            }, json.loads(meta["import_outcomes"]))
            for outcome, count in {
                "resolved": 2,
                "unresolved": 2,
                "external": 5,
                "excluded": 3,
            }.items():
                self.assertEqual(str(count), meta["import_outcome_" + outcome])

    def test_indexing_builds_repository_resolution_lookup_once(self):
        from unittest.mock import patch

        from codewiki.index import pipeline, resolution

        with tempfile.TemporaryDirectory(prefix="codewiki-lookup-cache-") as root:
            write_file(root, "src/p/Type.java", "package p;\npublic class Type {}\n")
            write_file(root, "src/q/Other.java", "package q;\npublic class Other {}\n")
            write_file(root, "src/app/Use.java", (
                "package app;\n"
                "import p.Type;\n"
                "import p.*;\n"
                "import java.util.List;\n"
                "public class Use {}\n"
            ))

            with patch.object(
                    resolution, "build_lookup", wraps=resolution.build_lookup) as build_lookup:
                pipeline.run(root, os.path.join(root, "out"), jobs=1)

            self.assertEqual(1, build_lookup.call_count)

    def test_reindexing_keeps_import_and_resolution_rows_identical(self):
        from codewiki.index import pipeline
        from codewiki.store.db import open_index

        with tempfile.TemporaryDirectory(prefix="codewiki-determinism-") as root:
            write_file(root, "src/p/Type.java", "package p;\npublic class Type {}\n")
            write_file(root, "src/app/Use.java", (
                "package app;\nimport p.*;\nimport java.util.List;\npublic class Use {}\n"
            ))
            first = pipeline.run(root, os.path.join(root, "first"), jobs=1)
            second = pipeline.run(root, os.path.join(root, "second"), jobs=1)

            def rows(path):
                connection = open_index(path)
                try:
                    return (
                        connection.execute(
                            "SELECT path, line, raw, form, name, target_fqn, internal_target, "
                            "outcome, candidates FROM imports JOIN files USING(file_id) "
                            "ORDER BY path, line, raw"
                        ).fetchall(),
                        connection.execute(
                            "SELECT path, name, resolved_fqn, rule, outcome, candidates "
                            "FROM type_resolutions JOIN files USING(file_id) "
                            "ORDER BY path, name"
                        ).fetchall(),
                    )
                finally:
                    connection.close()

            self.assertEqual(rows(first.db_path), rows(second.db_path))


if __name__ == "__main__":
    unittest.main()
