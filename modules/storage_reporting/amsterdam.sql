-- SQLite layout for delayed Amsterdam executions of the configured option class.
-- A capture records one rolling publication window and the archived source payload.
-- Its digest is stable on reimport. A valid window can contain zero eligible trades.
CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY NOT NULL,
    retrieved_utc TEXT NOT NULL, trading_day TEXT NOT NULL, underlying TEXT NOT NULL,
    share_isin TEXT NOT NULL, option_class TEXT NOT NULL, window TEXT NOT NULL,
    expiry_from TEXT NOT NULL, expiry_to TEXT NOT NULL, listed_contracts INTEGER NOT NULL,
    raw_ref TEXT NOT NULL
);
-- Trade identifiers are unique within a capture. The same trade can appear again in an
-- overlapping window. Per-window reports use both capture_id and trade_id for that reason.
-- Option premiums and share prices are EUR per share. Quantity counts option contracts.
-- The nullable stock fields identify the as-of match. The valuator computes age and model
-- price from stored observations and settings when it reads a report.
CREATE TABLE IF NOT EXISTS option_trades (
    capture_id TEXT NOT NULL REFERENCES captures(capture_id), trade_id TEXT NOT NULL,
    option_isin TEXT NOT NULL, traded_utc TEXT NOT NULL, published_utc TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('call','put')), strike_eur REAL NOT NULL,
    expiry_utc TEXT NOT NULL, assumed_cutoff INTEGER NOT NULL, exercise_style TEXT NOT NULL,
    multiplier REAL, quantity REAL NOT NULL, trade_eur REAL NOT NULL,
    stock_trade_id TEXT, stock_utc TEXT, stock_eur REAL,
    PRIMARY KEY (capture_id, trade_id)
);
CREATE INDEX IF NOT EXISTS trades_by_capture_time ON option_trades(capture_id, traded_utc);
