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

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_fqn ON symbols(fqn);
CREATE INDEX IF NOT EXISTS idx_symbols_owner_fqn ON symbols(owner_fqn);
CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_id);
CREATE INDEX IF NOT EXISTS idx_imports_form ON imports(form);
CREATE INDEX IF NOT EXISTS idx_imports_outcome ON imports(outcome);
CREATE INDEX IF NOT EXISTS idx_type_resolutions_file_name ON type_resolutions(file_id, name);
