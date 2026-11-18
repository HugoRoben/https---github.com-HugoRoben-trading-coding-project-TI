"""Each transaction publishes one completed capture and its observed contract terms."""

from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3

from .config import Quality
from .domain import Contract, Quote, Snapshot, digest, iso, parse_time
from .validation import quality_flags


@contextmanager
def database(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(Path(__file__).with_name("schema.sql").read_text())
        yield db
    finally:
        db.close()


def save_snapshot(
    db: sqlite3.Connection, snapshot: Snapshot, raw_ref: str, input_hash: str, quality: Quality
) -> bool:
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
    row = db.execute(
        """SELECT capture_id, source, provider, option_feed, underlying_feed,
                     retrieved_at, raw_ref, input_sha256 FROM snapshots WHERE capture_id=?""",
        (capture_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"capture {capture_id} is missing; run demo to load the synthetic dataset")
    return dict(row)


def latest_market_id(db: sqlite3.Connection) -> str:
    row = db.execute("""SELECT capture_id FROM snapshots WHERE source='market'
                     ORDER BY retrieved_at DESC, capture_id DESC LIMIT 1""").fetchone()
    if row is None:
        raise ValueError("no market captures yet; run collect first")
    return row[0]
