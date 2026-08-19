# codewiki

`codewiki` is a deterministic, standard-library-only Python 3.9 command-line
tool for indexing Java symbols into SQLite and looking them up without opening
source files during queries.

## Usage

Build an index:

```text
python3 -m codewiki index /path/to/repository --out .codewiki
```

The default output is `.codewiki` relative to the current working directory.
The indexer never writes to the scanned repository unless `--out` explicitly
names a directory inside it. `--jobs N` selects multiprocessing for large
inputs; `--quiet` suppresses progress while retaining the final summary.

Look up symbols:

```text
python3 -m codewiki symbol OrderService.cancel --out .codewiki
python3 -m codewiki symbol Order --out .codewiki --json --limit 10 --kind class
```

Queries support simple names, `Type.member`, exact fully qualified names, and
nested type/member forms. Simple-name ambiguity is preserved. A missing or
stale database exits with status 2 and says to rerun `index`; no-match exits 0.

Resolve a Java type name from an indexed repository-relative file:

```text
python3 -m codewiki resolve-type Order --from src/com/acme/Use.java --out .codewiki
python3 -m codewiki resolve-type Order --from src/com/acme/Use.java --out .codewiki --json
```

Resolution follows conservative precedence: same-file types (including nested
types), explicit single-type imports, one same-package type, and one matching
non-static wildcard package. Static imports are recorded but never provide
types. Ambiguous or missing internal candidates are `unresolved`; clearly
external imports such as `java.util.List` are `external`. Imports whose
repository package is present only in excluded files are `excluded`; import
classification uses the longest exact package prefix, so a shared root alone
does not make an import internal. JSON always has `file`, `name`,
`resolved_fqn`, `rule`, `outcome`, and `candidates` keys; absent FQNs and rules
are `null`, and no-match exits 0.

Show the indexed subtype closure of a fully qualified type:

```text
python3 -m codewiki impls com.acme.Base --out .codewiki
python3 -m codewiki impls com.acme.Base --out .codewiki --direct --limit 10
python3 -m codewiki impls com.acme.Base --out .codewiki --json --profile normal
```

Results are ordered by distance and FQN. `--direct` keeps only types that name
the queried type directly, and `--limit` keeps the nearest results.
`--implementation-limit` bounds the candidate search. JSON always has `fqn`,
`direct`, `count`, `truncated`, `results`, `status`, `truncation_reason`,
`boundaries`, and `profile` keys; `truncation_reason` is `candidates`,
`limit`, or `null`. No-match exits 0.

Read callers and callees of a fully qualified method:

```text
python3 -m codewiki callers com.acme.OrderService.cancel --out .codewiki
python3 -m codewiki callers com.acme.OrderService.cancel --out .codewiki --confirmed --direct
python3 -m codewiki callees com.acme.OrderService.cancel --out .codewiki --json --limit 10
```

`callers` includes direct calls and calls that name a same-method ancestor;
`--direct` keeps only the former and `--confirmed` removes possible and
unresolved edges. `callees --confirmed` keeps only confirmed calls. Both
commands apply `--limit` after filtering, report their direct/expanded or
resolved/unresolved split, and return an empty result with status 0 when the
method is not indexed. JSON for `callers` always has `fqn`, `direct_only`,
`confirmed_only`, `count`, `truncated`, `direct`, `expanded`, `results`,
`status`, `truncation_reason`, `boundaries`, and `profile` keys;
`truncation_reason` is `dispatch_hops`, `limit`, or `null`. JSON for `callees`
always has `fqn`, `confirmed_only`, `count`, `truncated`, `resolved`,
`unresolved`, `results`, `status`, `truncation_reason`, and `boundaries` keys;
`truncation_reason` is `limit` or `null`.

The status values are `COMPLETE`, `TRUNCATED`, `STOPPED_AT_BOUNDARY`, and
`NOT_INDEXED`. `COMPLETE` means the search finished, including when it found
nothing. `TRUNCATED` means a display limit or search budget cut the result.
`STOPPED_AT_BOUNDARY` means the search found an indexed boundary. `NOT_INDEXED`
means the queried symbol is not in the index at all. The precedence is
`NOT_INDEXED`, then `TRUNCATED`, then `STOPPED_AT_BOUNDARY`, then `COMPLETE`.

`boundaries` is non-empty only for `callees`. A reflective call such as
`Class.forName(name).newInstance()` is recorded at the call site, but the index
holds no edge into whatever it reaches, so the boundary is visible looking down
and invisible looking up. The other three commands emit an empty `boundaries`
list.

Walk the call graph upward from a method, optionally keeping only the entry
points it reaches:

```text
python3 -m codewiki trace-up com.acme.OrderRepository.updateStatus --out .codewiki
python3 -m codewiki trace-up com.acme.OrderRepository.updateStatus --out .codewiki --entrypoints
python3 -m codewiki trace-up com.acme.OrderRepository.updateStatus --out .codewiki --depth 16 --json
```

One shortest path is kept per reachable method, so a heavily re-convergent call
graph stays finite. `--entrypoints` reports each reaching entry point with its
kind and the chain down to the queried method. `--depth` bounds the walk and
defaults to 8. JSON always has `fqn`, `depth`, `entrypoints_only`, `count`,
`truncated`, `status`, `truncation_reason`, `boundaries`, `max_depth_reached`,
`results`, and `profile` keys; `truncation_reason` is `depth`, `nodes`,
`limit`, or `null`.

For these commands, `--limit` is a display limit applied after the answer is
computed. The search budgets are `--implementation-limit` for `impls`,
`--dispatch-hops` for `callers`, and `--depth` for `trace-up`; they stop the
search while it runs. If both kinds of limit apply, the search-budget reason is
reported in `truncation_reason` rather than `limit`.
`--profile normal|detailed` is available on `impls`, `callers`, and
`trace-up`. `normal` sets `impls` to 10 candidates, `callers` to 2 dispatch
hops, and `trace-up` to depth 4.
`detailed` is the default behaviour, with no implementation or dispatch budget
and the ordinary trace depth of 8. Omitting `--profile` behaves like `detailed`
but reports `"profile": null`. An explicitly supplied budget flag overrides
the corresponding profile value.

Find the methods that read or write a table or a column:

```text
python3 -m codewiki table ORDERS --out .codewiki
python3 -m codewiki table ORDERS --out .codewiki --write --json
python3 -m codewiki column ORDERS.STATUS --out .codewiki --write
```

Table and column names are matched case-insensitively. `--read` and `--write`
filter by access; without either, both are returned. Reserved words are legal
table names and are treated as such.

Read aggregate statistics from an existing index, or measure how many
SQL-touching methods reach an entry point:

```text
python3 -m codewiki stats --out .codewiki --json
python3 -m codewiki reach --out .codewiki --depth 16 --json
```

Both emit counts and rates only, never identifiers: grouping is applied only to
columns whose value set is fixed in code, identifiers appear only inside
`COUNT(DISTINCT ...)`, and `meta` is read through an allowlist so `repo_root`
cannot leak. A value outside a known vocabulary — an entry-point kind added to
`ENTRYPOINT_RULES` — is counted under `other` rather than dropped or named.
This is what makes the output safe to carry off a machine that holds source you
cannot copy; `docs/field-loop.md` is the procedure that relies on it.

## Determinism and schema

Files and symbols are sorted before insertion, so logical rows and
`file_id`/`symbol_id` values are repeatable for the same source bytes. SQLite
foreign keys are enabled. `generated_at` is stored as the current UTC timestamp
for operational visibility and is intentionally excluded from logical-content
comparisons. The schema version is checked before every query; incompatible
databases fail clearly instead of appearing empty.

The DDL is in `codewiki/store/schema.sql` and contains `files`, `symbols`,
`imports`, `type_resolutions`, `supertypes`, `calls`, `sql_accesses`,
`sql_column_accesses`, `annotations`, `entrypoints`, and `meta`, with indexes on
symbol name, FQN, owner FQN, import form/outcome, file/type resolution lookup,
call caller/target/name, table and column keys, annotation simple name, and
entry-point method and kind. Import forms
are the stable values `single`, `wildcard`, `static_single`, and
`static_wildcard`. Import rows retain the raw statement, normalized name,
target classification, and candidate JSON. `meta` stores form/outcome counts
for imports and all four type-resolution outcome counts. The
`internal_resolution_rate` is calculated as resolved divided by resolved plus
unresolved (external and excluded imports excluded). The four import outcomes
are persisted and reported even when a count is zero. The schema is additive:
future versions may add columns or tables but must not rename or remove the
required fields.

## Java extraction limits

The extractor uses conservative regular expressions, comment/string stripping,
and brace matching adapted from the original `llm-wiki` implementation. It
captures packages, classes, interfaces, enums, records, annotations,
constructors, methods, nested parent chains, signatures, and parsed parameter
types. Multi-line parameter lists that cannot be safely parsed remain in the
index with `POSSIBLE` confidence and null parameter fields. A type whose body
range cannot be resolved within the bounded scan is retained with a null
`end_line` and `UNRESOLVED` confidence; its members are still indexed.
The body scan bound is 10,000 lines, which is finite for corrupt input and above
the largest supported HAPI source file observed by the project.

Anonymous and local classes are not separate symbols; methods encountered in
their bodies may be attributed to the nearest named enclosing type.

## What is and is not resolved

Call resolution is partial, and the boundary decides how far a trace reaches.

| Call form | Example | Resolved |
|---|---|---|
| receiver | `svc.cancel()` | yes — through the declared variable, a type name, or an inherited field |
| bare | `helper()` | yes — against the enclosing type and its supertypes |
| chained | `a.b().c()` | no — the receiver expression is recorded, the return type is not yet followed |
| constructor | `new Foo()` | no |
| method reference | `Foo::bar` | no |

Overloads resolve to `POSSIBLE` with every candidate listed rather than to a
guess; argument counts and types are not used to narrow them. Nothing here
follows interface dispatch to an implementation, reflection, or dependency
injection: an edge exists only where the source names the receiver.

SQL is read from string literals in Java source. Statements assembled by
concatenation at runtime, or held in external mapper XML, are not seen. Table
and column extraction is textual and does not resolve aliases across
subqueries.

Entry points are Servlet, JAX-RS, and `main`, defined in `ENTRYPOINT_RULES` in
`codewiki/index/entrypoints.py`. That constant is the extension point: add the
annotation name, base class, or method shape your own framework uses and the
rest of the pipeline follows. Spring MVC is deliberately not included.

XML, SQL, and properties files are recorded as files but their contents are not
analyzed. The project does no caching, no LLM calls, and no network access.
