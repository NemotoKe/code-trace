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

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_fqn ON symbols(fqn);
CREATE INDEX IF NOT EXISTS idx_symbols_owner_fqn ON symbols(owner_fqn);
