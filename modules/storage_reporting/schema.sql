-- SQLite layout for the U.S. quote pipeline and its synthetic replay fixture.
-- A snapshot is one retrieval, even when the provider repeats previously seen quotes.
-- The writer commits its header, observed contract versions and quote rows together.
-- UTC times are stored as sortable ISO strings. raw_ref and input_sha256 identify the input.
CREATE TABLE IF NOT EXISTS snapshots (
    capture_id TEXT PRIMARY KEY NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('synthetic', 'market')),
    provider TEXT NOT NULL,
    option_feed TEXT NOT NULL,
    underlying_feed TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    underlying TEXT NOT NULL,
    spot REAL,
    underlying_at TEXT,
    raw_ref TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    quality_policy TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'complete')
);
CREATE INDEX IF NOT EXISTS snapshots_by_time ON snapshots (source, retrieved_at);

-- A symbol can acquire corrected metadata. Earlier snapshots retain their observed terms.
CREATE TABLE IF NOT EXISTS contracts (
    terms_id TEXT PRIMARY KEY NOT NULL,
    provider TEXT NOT NULL,
    symbol TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiry_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('call', 'put')),
    strike REAL NOT NULL CHECK (strike > 0),
    currency TEXT NOT NULL,
    multiplier REAL,
    exercise_style TEXT NOT NULL,
    expiry_time_assumed INTEGER NOT NULL CHECK (expiry_time_assumed IN (0, 1))
);
-- One observation per contract version in a capture. Bid and ask are USD per share.
-- Missing source fields stay NULL. ingest_flags records the policy findings at ingestion,
-- so a newer model or quality policy can revisit the original observation.
CREATE TABLE IF NOT EXISTS quotes (
    capture_id TEXT NOT NULL REFERENCES snapshots(capture_id),
    terms_id TEXT NOT NULL REFERENCES contracts(terms_id),
    quote_at TEXT,
    bid REAL,
    ask REAL,
    ingest_flags TEXT NOT NULL,
    PRIMARY KEY (capture_id, terms_id)
);
