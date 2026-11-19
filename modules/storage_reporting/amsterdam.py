"""Store Amsterdam execution windows and value the option prints in EUR per share.

Each capture keeps its raw archive, registered terms and the share trade matched to each
option execution. Two rolling windows may contain the same print. Read and value one named
window or the latest matching capture to keep counts interpretable. Prices and quality
statuses in the report use the model settings supplied at read time.
"""

from dataclasses import asdict
from pathlib import Path

from modules.euronext.observations import trade_rows
from modules.models.black_scholes import YEAR_SECONDS, black_scholes
from options_lab.config import AmsterdamSettings
from options_lab.domain import digest, parse_time

from .database import database
from .raw_captures import archive
from .reporting import write_report_files

TRADE_COLUMNS = (
    "trade_id",
    "option_isin",
    "traded_utc",
    "published_utc",
    "kind",
    "strike_eur",
    "expiry_utc",
    "assumed_cutoff",
    "exercise_style",
    "multiplier",
    "quantity",
    "trade_eur",
    "stock_trade_id",
    "stock_utc",
    "stock_eur",
)
REPORT_COLUMNS = ("capture_id", *TRADE_COLUMNS, "stock_age_s", "model_eur", "valuation_status")


def amsterdam_database(directory: Path):
    """Return a context manager for the Amsterdam SQLite store under directory.

    The database filename is amsterdam.sqlite3. Entering the context creates the directory
    and tables if needed, enables foreign keys and yields a connection with named columns.
    The Amsterdam schema stores execution windows and matched trade rows independently of
    the USD quote database.
    """
    return database(directory / "amsterdam.sqlite3", schema="amsterdam.sql")


def recent_windows(db, settings: AmsterdamSettings, limit: int) -> list[dict]:
    """Summarize the latest saved windows for the share and option class in settings.

    On the open Amsterdam connection db, group option rows by capture and return at most
    limit dictionaries in descending retrieval order. Each contains the trading day, window
    label, execution count, distinct traded series and latest execution time. Empty
    captures appear with zero counts and a null latest trade time.

    limit must be positive. Counts describe individual windows and can overlap when the
    collector polls more often than the length of a window.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    return [
        dict(row)
        for row in db.execute(
            """SELECT c.retrieved_utc, c.trading_day, c.window, COUNT(t.trade_id) AS executions,
                  COUNT(DISTINCT t.option_isin) AS traded_series, MAX(t.traded_utc) AS newest_trade_utc
           FROM captures AS c LEFT JOIN option_trades AS t USING(capture_id)
           WHERE c.share_isin=? AND c.option_class=? GROUP BY c.capture_id
           ORDER BY c.retrieved_utc DESC, c.capture_id DESC LIMIT ?""",
            (settings.euronext.share_isin, settings.euronext.option_class, limit),
        )
    ]


def save_window(db, raw: dict, directory: Path, settings: AmsterdamSettings) -> tuple[str, int]:
    """Archive one Amsterdam window and persist its eligible option executions.

    Validate raw against settings.euronext and derive its normalized trade rows, then write
    the native payload under directory/raw/euronext. The archive digest becomes the capture
    ID. On db, insert the capture and all its rows in one transaction. An empty window
    still records the retrieval.

    Return the capture ID and the count of eligible executions in the input, including on
    reimport. A matching digest reuses the existing database rows. A database failure rolls
    back that transaction, and the already saved raw file remains available for a retry.
    """
    observations = trade_rows(raw, settings.euronext)
    path = archive(raw, directory / "raw" / "euronext")
    capture_id = path.stem
    with db:
        inserted = db.execute(
            """INSERT INTO captures
               (capture_id,retrieved_utc,trading_day,underlying,share_isin,option_class,window,
                expiry_from,expiry_to,listed_contracts,raw_ref)
               VALUES (:capture_id,:retrieved_at,:trading_day,:underlying,:share_isin,:option_class,:window,
                       :expiry_from,:expiry_to,:listed_contracts,:raw_ref)
               ON CONFLICT(capture_id) DO NOTHING""",
            {**raw, "capture_id": capture_id, "raw_ref": str(path.relative_to(directory))},
        )
        if inserted.rowcount:
            fields = ("capture_id", *TRADE_COLUMNS)
            db.executemany(
                f"INSERT INTO option_trades ({','.join(fields)}) VALUES ({','.join(':' + f for f in fields)})",
                ({"capture_id": capture_id, **row} for row in observations),
            )
    return capture_id, len(observations)


def read_report(db, settings: AmsterdamSettings, capture_id: str | None = None):
    """Read one Amsterdam window and value each option at its execution time.

    Filter db by the share ISIN and option class in settings. An explicit capture_id pins
    the result. Otherwise select the latest matching capture. For each trade, measure share
    age and use the matched share price, observed strike and remaining ACT/365F term in the
    configured European pricing scenario.

    Return a pair of capture metadata and trade dictionaries, newest execution first. A
    missing or stale share trade or a trade past expiry yields a status and an empty model
    value. Valid model prices are rounded to six decimals in EUR per share. A missing
    capture returns (None, []), while a saved empty window returns its metadata and an
    empty list.
    """
    market = settings.euronext
    filters = "share_isin=? AND option_class=?"
    args = [market.share_isin, market.option_class]
    if capture_id is not None:
        filters += " AND capture_id=?"
        args.append(capture_id)
    row = db.execute(
        f"SELECT * FROM captures WHERE {filters} ORDER BY retrieved_utc DESC, capture_id DESC LIMIT 1",
        args,
    ).fetchone()
    if row is None:
        return None, []
    info = dict(row)
    rows = []
    model = settings.model
    for item in db.execute(
        "SELECT * FROM option_trades WHERE capture_id=? ORDER BY traded_utc DESC, trade_id",
        (info["capture_id"],),
    ):
        trade = dict(item)
        at = parse_time(trade["traded_utc"])
        years = (parse_time(trade["expiry_utc"]) - at).total_seconds() / YEAR_SECONDS
        age = (at - parse_time(trade["stock_utc"])).total_seconds() if trade["stock_utc"] else None
        value = None
        if age is None:
            status = "missing earlier share trade"
        elif age > market.max_spot_age_seconds:
            status = "stale share trade"
        elif years < 0:
            status = "past expiry cutoff"
        else:
            value = round(
                black_scholes(
                    trade["kind"],
                    trade["stock_eur"],
                    trade["strike_eur"],
                    years,
                    model.rate,
                    model.dividend_yield,
                    model.volatility,
                ),
                6,
            )
            status = "ok"
        rows.append({**trade, "stock_age_s": age, "model_eur": value, "valuation_status": status})
    return info, rows


def write_trade_report(directory: Path, info, rows, settings: AmsterdamSettings) -> Path:
    """Export one valued Amsterdam window and its provenance under directory.

    Pass the info and rows returned by read_report together with the settings used for
    valuation. The CSV includes execution prices, share matches, model values and statuses.
    The manifest records the capture identity, data sources, reporting delay, currency,
    scenario assumptions and execution count.

    Return the report directory named from a digest of the manifest and rows. A window with
    zero trades still produces a manifest and a CSV header. Repeating the same export
    resolves to the same path.
    """
    manifest = {
        "capture": info,
        "settings": asdict(settings),
        "currency": "EUR",
        "options": "Euronext Amsterdam (XEUE) delayed executions",
        "stock": "Euronext Amsterdam (XAMS) share executions",
        "reference": "ESMA FIRDS",
        "publication_delay_minutes": 15,
        "pricing": "European Black–Scholes–Merton scenario per share at option execution time. "
        "The stock proxy is the last share trade already published by that execution time.",
        "trade_count": len(rows),
    }
    target = directory / ("amsterdam-" + digest([manifest, rows])[:16])
    return write_report_files(
        target, "trades.csv", REPORT_COLUMNS, rows, {"manifest.json": manifest}
    )
