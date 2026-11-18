CREATE TABLE IF NOT EXISTS captures (
    capture_id TEXT PRIMARY KEY NOT NULL,
    retrieved_utc TEXT NOT NULL, trading_day TEXT NOT NULL, underlying TEXT NOT NULL,
    share_isin TEXT NOT NULL, option_class TEXT NOT NULL, window TEXT NOT NULL,
    expiry_from TEXT NOT NULL, expiry_to TEXT NOT NULL, listed_contracts INTEGER NOT NULL,
    raw_ref TEXT NOT NULL
);
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
