"""Persist Amsterdam trade windows and value each print in EUR at its execution time."""

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
    return database(directory / "amsterdam.sqlite3", schema="amsterdam.sql")


def recent_windows(db, settings: AmsterdamSettings, limit: int) -> list[dict]:
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
