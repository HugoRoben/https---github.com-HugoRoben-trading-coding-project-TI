"""Persist and reconstruct option quote snapshots with the terms observed at capture time.

A capture groups a stock observation and its option quotes. Contract terms are versioned by
a digest so later metadata corrections cannot change the meaning of an earlier quote. Each
save runs in one SQLite transaction and records source provenance, the active quality
policy and the flags found on ingestion.
"""

from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from options_lab.config import Quality
from options_lab.domain import Contract, Quote, Snapshot, digest, iso, parse_time
from options_lab.validation import quality_flags


@contextmanager
def database(path: Path, *, schema: str = "schema.sql"):
    """Open a local SQLite database and initialize it with the selected schema.

    path is the database filename. Create its parent directories, enable foreign keys and
    apply the SQL script named by schema from this module's directory. The default schema
    stores USD snapshots. The Amsterdam trade store supplies its own script.

    Yield a connection whose rows support access by column name, with a ten-second lock
    timeout. Individual writers own their transactions. The context manager always closes
    the connection, including when the caller raises.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(Path(__file__).with_name(schema).read_text())
        yield db
    finally:
        db.close()


def save_snapshot(
    db: sqlite3.Connection, snapshot: Snapshot, raw_ref: str, input_hash: str, quality: Quality
) -> bool:
    """Commit a complete capture and its observed contract terms and quotes as a unit.

    db is an open quote database. snapshot must contain at least one quote and unique
    option symbols, each with the expected underlying. raw_ref identifies the source
    archive or fixture, input_hash identifies its contents, and quality sets the thresholds
    recorded alongside the per-quote flags.

    Return True for a newly committed capture. Reusing the same capture ID and hash returns
    False, while reusing the ID with different content raises ValueError. A failure in any
    contract or quote insertion rolls back the whole database transaction. Corrected terms
    under the same symbol receive a distinct terms ID.
    """
    s = snapshot
    if not s.quotes or len({q.contract.symbol for q in s.quotes}) != len(s.quotes):
        raise ValueError("a capture must contain unique contract symbols and at least one row")
    with db:
        inserted = db.execute(
            """INSERT INTO snapshots (capture_id, source, provider, option_feed, underlying_feed,
               retrieved_at, underlying, spot, underlying_at, raw_ref, input_sha256, quality_policy, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'complete')
               ON CONFLICT(capture_id) DO NOTHING""",
            (
                s.capture_id,
                s.source,
                s.provider,
                s.option_feed,
                s.underlying_feed,
                iso(s.retrieved_at),
                s.underlying,
                s.spot,
                iso(s.underlying_at) if s.underlying_at else None,
                raw_ref,
                input_hash,
                json.dumps(asdict(quality), sort_keys=True),
            ),
        )
        if inserted.rowcount == 0:
            if (
                input_hash
                != db.execute(
                    "SELECT input_sha256 FROM snapshots WHERE capture_id=?", (s.capture_id,)
                ).fetchone()[0]
            ):
                raise ValueError(
                    f"capture ID already exists with different content: {s.capture_id}"
                )
            return False
        for quote in s.quotes:
            c = quote.contract
            if c.underlying != s.underlying:
                raise ValueError(f"unexpected underlying for {c.symbol}")
            terms = (
                s.provider,
                c.symbol,
                c.underlying,
                iso(c.expiry_at),
                c.kind,
                float(c.strike),
                c.currency,
                c.multiplier,
                c.exercise_style,
                int(c.expiry_time_assumed),
            )
            terms_id = digest(terms)
            db.execute(
                """INSERT INTO contracts (terms_id, provider, symbol, underlying, expiry_at,
                       kind, strike, currency, multiplier, exercise_style, expiry_time_assumed)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(terms_id) DO NOTHING""",
                (terms_id, *terms),
            )
            db.execute(
                """INSERT INTO quotes (capture_id, terms_id, quote_at, bid, ask, ingest_flags)
                       VALUES (?,?,?,?,?,?)""",
                (
                    s.capture_id,
                    terms_id,
                    iso(quote.quote_at) if quote.quote_at else None,
                    quote.bid,
                    quote.ask,
                    json.dumps(quality_flags(s, quote, quality)),
                ),
            )
    return True


def read_snapshot(db: sqlite3.Connection, capture_id: str) -> Snapshot:
    """Reconstruct a saved Snapshot using the contract version attached to each quote.

    Look up capture_id on db, join the quote rows to their term records, and return options
    ordered by symbol. Convert persisted timestamps back to UTC datetimes and preserve
    missing sides, multipliers and observation times. Reading from SQLite makes a
    historical capture usable even when the provider is unavailable. A missing capture
    raises ValueError.
    """
    s = db.execute("SELECT * FROM snapshots WHERE capture_id=?", (capture_id,)).fetchone()
    if s is None:
        raise ValueError(f"capture {capture_id} is missing from this database")
    quotes = []
    for row in db.execute(
        """SELECT c.*, q.quote_at, q.bid, q.ask FROM quotes q
                            JOIN contracts c USING (terms_id) WHERE capture_id=? ORDER BY c.symbol""",
        (capture_id,),
    ):
        c = Contract(
            row["symbol"],
            row["underlying"],
            parse_time(row["expiry_at"]),
            row["kind"],
            row["strike"],
            row["currency"],
            row["multiplier"],
            row["exercise_style"],
            bool(row["expiry_time_assumed"]),
        )
        quotes.append(
            Quote(
                c, parse_time(row["quote_at"]) if row["quote_at"] else None, row["bid"], row["ask"]
            )
        )
    return Snapshot(
        capture_id,
        s["source"],
        s["provider"],
        s["option_feed"],
        s["underlying_feed"],
        parse_time(s["retrieved_at"]),
        s["underlying"],
        s["spot"],
        parse_time(s["underlying_at"]) if s["underlying_at"] else None,
        tuple(quotes),
    )


def provenance(db: sqlite3.Connection, capture_id: str) -> dict:
    """Return the input identity and feed information recorded for a capture.

    Look up capture_id on db and produce a dictionary with source, provider, option and
    underlying feeds, retrieval timestamp, raw reference and input SHA-256. Reports use
    these fields to identify an exact source observation and the demo checks its stored
    hash against the fixture. An absent capture raises ValueError.
    """
    row = db.execute(
        """SELECT capture_id, source, provider, option_feed, underlying_feed,
                     retrieved_at, raw_ref, input_sha256 FROM snapshots WHERE capture_id=?""",
        (capture_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"capture {capture_id} is missing; run demo to load the synthetic dataset")
    return dict(row)


def latest_market_id(db: sqlite3.Connection) -> str:
    """Choose the most recently retrieved market capture from the quote database.

    Read the snapshots table on db and restrict the search to source "market". Resolve
    equal retrieval timestamps by descending capture ID for a repeatable choice. Return the
    ID so the caller can pin a valuation to that observation. Raise ValueError if no market
    capture is stored.
    """
    row = db.execute("""SELECT capture_id FROM snapshots WHERE source='market'
                     ORDER BY retrieved_at DESC, capture_id DESC LIMIT 1""").fetchone()
    if row is None:
        raise ValueError("no market captures yet; run collect first")
    return row[0]
