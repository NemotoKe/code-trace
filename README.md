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
python3 -m codewiki impls com.acme.Base --out .codewiki --json
```

Results are ordered by distance and FQN. `--direct` keeps only types that name
the queried type directly, and `--limit` keeps the nearest results. JSON always
has `fqn`, `direct`, `count`, `truncated`, and `results` keys; no-match exits 0.

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
method is not indexed.

## Determinism and schema

Files and symbols are sorted before insertion, so logical rows and
`file_id`/`symbol_id` values are repeatable for the same source bytes. SQLite
foreign keys are enabled. `generated_at` is stored as the current UTC timestamp
for operational visibility and is intentionally excluded from logical-content
comparisons. The schema version is checked before every query; incompatible
databases fail clearly instead of appearing empty.

The DDL is in `codewiki/store/schema.sql` and contains `files`, `symbols`,
`imports`, `type_resolutions`, and `meta`, with indexes on symbol name, FQN,
owner FQN, import form/outcome, and file/type resolution lookup. Import forms
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
their bodies may be attributed to the nearest named enclosing type. This is a
deliberate unit-1 limitation. The project does not analyze hierarchy, calls,
fields, SQL, XML, properties, entry points, traces, caching, LLMs,
network access, or non-Java source semantics. XML, SQL, and properties files
are recorded as files but are not analyzed.
