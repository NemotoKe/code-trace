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

## Determinism and schema

Files and symbols are sorted before insertion, so logical rows and
`file_id`/`symbol_id` values are repeatable for the same source bytes. SQLite
foreign keys are enabled. `generated_at` is stored as the current UTC timestamp
for operational visibility and is intentionally excluded from logical-content
comparisons. The schema version is checked before every query; incompatible
databases fail clearly instead of appearing empty.

The DDL is in `codewiki/store/schema.sql` and contains `files`, `symbols`, and
`meta`, with indexes on symbol name, FQN, and owner FQN. The schema is additive:
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
fields, SQL, XML, properties, imports, entry points, traces, caching, LLMs,
network access, or non-Java source semantics. XML, SQL, and properties files
are recorded as files but are not analyzed.
