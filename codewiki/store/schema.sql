PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS files (
    file_id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL,
    package TEXT,
    lines INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    is_test INTEGER NOT NULL,
    is_generated INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    symbol_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    fqn TEXT NOT NULL,
    owner_fqn TEXT,
    params TEXT,
    param_count INTEGER,
    signature TEXT NOT NULL,
    line INTEGER NOT NULL,
    end_line INTEGER,
    confidence TEXT NOT NULL,
    UNIQUE(file_id, line, name, kind)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    import_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    line INTEGER NOT NULL,
    column INTEGER NOT NULL,
    raw TEXT NOT NULL,
    form TEXT NOT NULL,
    name TEXT NOT NULL,
    target_fqn TEXT,
    internal_target TEXT,
    outcome TEXT NOT NULL CHECK(outcome IN ('resolved', 'external', 'unresolved', 'excluded')),
    candidates TEXT NOT NULL,
    CHECK(form IN ('single', 'wildcard', 'static_single', 'static_wildcard'))
);

CREATE TABLE IF NOT EXISTS type_resolutions (
    resolution_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    resolved_fqn TEXT,
    rule INTEGER,
    outcome TEXT NOT NULL CHECK(outcome IN ('resolved', 'external', 'unresolved', 'excluded')),
    candidates TEXT NOT NULL,
    UNIQUE(file_id, name)
);

CREATE TABLE IF NOT EXISTS supertypes (
    supertype_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    owner_fqn TEXT NOT NULL,
    line INTEGER NOT NULL,
    relation TEXT NOT NULL CHECK(relation IN ('extends', 'implements')),
    raw TEXT NOT NULL,
    name TEXT NOT NULL,
    target_fqn TEXT,
    rule INTEGER,
    outcome TEXT NOT NULL CHECK(outcome IN ('resolved', 'external', 'unresolved', 'excluded')),
    candidates TEXT NOT NULL,
    UNIQUE(file_id, line, owner_fqn, relation, raw)
);

CREATE TABLE IF NOT EXISTS calls (
    call_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    caller_fqn TEXT NOT NULL,
    caller_kind TEXT NOT NULL,
    line INTEGER NOT NULL,
    form TEXT NOT NULL CHECK(form IN ('receiver', 'bare', 'chained', 'method_ref', 'constructor')),
    receiver TEXT,
    name TEXT NOT NULL,
    owner_fqn TEXT,
    target_fqn TEXT,
    confidence TEXT NOT NULL CHECK(confidence IN ('CONFIRMED', 'POSSIBLE', 'UNRESOLVED')),
    reason TEXT NOT NULL,
    candidates TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sql_accesses (
    access_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    method_fqn TEXT NOT NULL,
    method_kind TEXT NOT NULL,
    line INTEGER NOT NULL,
    verb TEXT NOT NULL CHECK(verb IN ('select', 'insert', 'update', 'delete', 'merge')),
    table_name TEXT NOT NULL,
    table_key TEXT NOT NULL,
    access TEXT NOT NULL CHECK(access IN ('READ', 'WRITE')),
    statement TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sql_column_accesses (
    column_access_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    method_fqn TEXT NOT NULL,
    method_kind TEXT NOT NULL,
    line INTEGER NOT NULL,
    verb TEXT NOT NULL CHECK(verb IN ('select', 'insert', 'update', 'delete', 'merge')),
    table_name TEXT NOT NULL,
    table_key TEXT NOT NULL,
    column_name TEXT NOT NULL,
    column_key TEXT NOT NULL,
    access TEXT NOT NULL CHECK(access IN ('READ', 'WRITE')),
    statement TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    owner_fqn TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    name TEXT NOT NULL,
    simple_name TEXT NOT NULL,
    line INTEGER NOT NULL,
    raw TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(caller_fqn);
CREATE INDEX IF NOT EXISTS idx_calls_target ON calls(target_fqn);
CREATE INDEX IF NOT EXISTS idx_calls_name ON calls(name);
CREATE INDEX IF NOT EXISTS idx_calls_file ON calls(file_id);
CREATE INDEX IF NOT EXISTS idx_sql_accesses_table ON sql_accesses(table_key);
CREATE INDEX IF NOT EXISTS idx_sql_accesses_method ON sql_accesses(method_fqn);
CREATE INDEX IF NOT EXISTS idx_sql_accesses_file ON sql_accesses(file_id);
CREATE INDEX IF NOT EXISTS idx_sql_column_accesses_column
    ON sql_column_accesses(table_key, column_key);
CREATE INDEX IF NOT EXISTS idx_sql_column_accesses_method
    ON sql_column_accesses(method_fqn);
CREATE INDEX IF NOT EXISTS idx_sql_column_accesses_file
    ON sql_column_accesses(file_id);
CREATE INDEX IF NOT EXISTS idx_annotations_simple_name
    ON annotations(simple_name);
CREATE INDEX IF NOT EXISTS idx_annotations_owner
    ON annotations(owner_fqn);
CREATE INDEX IF NOT EXISTS idx_annotations_file
    ON annotations(file_id);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_fqn ON symbols(fqn);
CREATE INDEX IF NOT EXISTS idx_symbols_owner_fqn ON symbols(owner_fqn);
CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_id);
CREATE INDEX IF NOT EXISTS idx_imports_form ON imports(form);
CREATE INDEX IF NOT EXISTS idx_imports_outcome ON imports(outcome);
CREATE INDEX IF NOT EXISTS idx_type_resolutions_file_name ON type_resolutions(file_id, name);
CREATE INDEX IF NOT EXISTS idx_supertypes_owner ON supertypes(owner_fqn);
CREATE INDEX IF NOT EXISTS idx_supertypes_target ON supertypes(target_fqn);
