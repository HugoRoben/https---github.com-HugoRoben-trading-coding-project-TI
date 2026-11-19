"""Read consistent SQLite previews for the market and synthetic status tables.

The query set covers capture counts, contract versions, individual quotes and flagged
observations. Quote ages are measured at retrieval in seconds. Each result carries a
dataset label so the notebook can display real and synthetic records together while
preserving their origin. pandas is required for these notebook views.
"""

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
    """Read counts and bounded table previews from both local USD databases.

    data_dir must contain initialized options.sqlite3 and demo.sqlite3 files. Open each in
    read-only mode and run its queries in a single read transaction. rows must be positive
    and limits each preview per database. The status counts cover each whole database.

    Return DataFrames under status, snapshots, contracts, quotes and flagged, each with a
    dataset column. Empty previews retain their column names. A missing database or schema
    raises a SQLite error. Each database has its own consistent read point.
    """
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
