"""Read-only SQLite views for the status notebook, returned as pandas DataFrames."""

from contextlib import closing
from pathlib import Path
import sqlite3

import pandas as pd

_QUOTE_SELECT = """
    SELECT q.capture_id, c.symbol, q.bid, q.ask, q.quote_at AS quote_utc,
           ROUND((julianday(s.retrieved_at) - julianday(q.quote_at)) * 86400, 1) AS age_at_capture_s,
           q.ingest_flags
    FROM quotes q JOIN snapshots s USING (capture_id) JOIN contracts c USING (terms_id)"""
_QUOTE_ORDER = " ORDER BY s.retrieved_at DESC, s.capture_id DESC, c.symbol LIMIT ?"
_QUERIES = {
    "status": """
        SELECT COUNT(*) AS captures, (SELECT COUNT(*) FROM contracts) AS contract_versions,
               (SELECT COUNT(*) FROM quotes) AS quote_rows,
               (SELECT COUNT(*) FROM quotes WHERE ingest_flags <> '[]') AS flagged_rows,
               MAX(retrieved_at) AS last_capture_utc,
               (SELECT MAX(quote_at) FROM quotes) AS newest_option_quote_utc
        FROM snapshots""",
    "snapshots": """
        SELECT capture_id, retrieved_at AS retrieved_utc, underlying, spot,
               underlying_at AS underlying_utc, provider, option_feed, underlying_feed, status
        FROM snapshots ORDER BY retrieved_at DESC, capture_id DESC LIMIT ?""",
    "contracts": """
        SELECT symbol, underlying, kind, strike, expiry_at AS expiry_utc,
               exercise_style, multiplier, currency
        FROM contracts ORDER BY expiry_at, strike, symbol, terms_id LIMIT ?""",
    "quotes": _QUOTE_SELECT + _QUOTE_ORDER,
    "flagged": _QUOTE_SELECT + " WHERE q.ingest_flags <> '[]'" + _QUOTE_ORDER,
}


def read_status_tables(data_dir: Path, rows: int) -> dict[str, pd.DataFrame]:
    """Read a consistent set of counts and previews per database, labelled by dataset."""
    if rows < 1:
        raise ValueError("rows must be positive")
    records = {name: [] for name in _QUERIES}
    columns = {}
    for dataset, filename in [
        ("Alpaca market", "options.sqlite3"),
        ("Synthetic demo", "demo.sqlite3"),
    ]:
        uri = (data_dir / filename).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.execute("BEGIN")  # All five queries see the same capture history.
            for name, sql in _QUERIES.items():
                cursor = db.execute(sql, () if name == "status" else (rows,))
                columns[name] = ["dataset", *(column[0] for column in cursor.description)]
                records[name].extend((dataset, *row) for row in cursor)

    return {
        name: pd.DataFrame.from_records(table_rows, columns=columns[name])
        for name, table_rows in records.items()
    }
