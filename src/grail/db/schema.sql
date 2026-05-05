CREATE TABLE IF NOT EXISTS metadata(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL DEFAULT 'unknown',
    file_path TEXT NOT NULL,
    line_start INTEGER,
    line_end INTEGER,
    symbol_status TEXT NOT NULL DEFAULT 'indexed',
    human_verified INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS code_refs (
    id INTEGER PRIMARY KEY,
    from_symbol_id INTEGER NOT NULL,
    to_symbol_id INTEGER,
    target_text TEXT,
    ref_type TEXT NOT NULL,
    instruction TEXT,
    file_path TEXT,
    line_number INTEGER,

    FOREIGN KEY (from_symbol_id) REFERENCES symbols(id) ON DELETE CASCADE,
    FOREIGN KEY (to_symbol_id) REFERENCES symbols(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY,
    symbol_id INTEGER NOT NULL,
    claim TEXT NOT NULL,
    evidence TEXT,
    confidence TEXT NOT NULL DEFAULT 'unknown',
    claim_status TEXT NOT NULL DEFAULT 'proposed',

    FOREIGN KEY (symbol_id) REFERENCES symbols(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(type);
CREATE INDEX IF NOT EXISTS idx_symbols_status ON symbols(symbol_status);

CREATE INDEX IF NOT EXISTS idx_code_refs_from ON code_refs(from_symbol_id);
CREATE INDEX IF NOT EXISTS idx_code_refs_to ON code_refs(to_symbol_id);
CREATE INDEX IF NOT EXISTS idx_code_refs_target ON code_refs(target_text);

CREATE INDEX IF NOT EXISTS idx_claims_symbol ON claims(symbol_id);
CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(claim_status);