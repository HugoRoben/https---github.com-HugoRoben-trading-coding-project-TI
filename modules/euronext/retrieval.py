"""Read Amsterdam trade files and resolve the traded options through ESMA FIRDS."""

import csv
from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta
from io import BytesIO, TextIOWrapper
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

from options_lab.config import AmsterdamMarket
from options_lab.domain import iso, parse_time

AMSTERDAM = ZoneInfo("Europe/Amsterdam")
FORMAT = "euronext-amsterdam-trades-v1"
TRADE_FILES = "https://marketdata.euronext.com/data-reporting-service/trades-file/download"
FIRDS = "https://registers.esma.europa.eu/solr/esma_registers_firds/select"
REF_FIELDS = (
    "isin,mic,gnr_short_name,gnr_notional_curr_code,drv_underlng_isin,drv_expiry_date,"
    "mrkt_trdng_trmination_date,drv_option_type,drv_option_exercise_style,drv_price_multiplier,"
    "drv_sp_prc_value_amount,drv_sp_prc_value_curr_code"
)
TRADE_FIELDS = {
    "TradingDateTime",
    "PublicationDateTime",
    "MifidInstrumentID",
    "MifidPrice",
    "MifidQuantity",
    "MifidPriceNotation",
    "MifidCurrency",
    "MmtModificationIndicator",
    "Venue",
    "TradeUniqueIdentifier",
}


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "options-lab/0.1 (local market research)"})
    try:
        with urlopen(request, timeout=30) as response:
            if response.status == 204:
                return b""
            payload = response.read(32_000_001)
    except HTTPError as error:
        raise ValueError(f"{request.host} returned HTTP {error.code}") from error
    except OSError as error:
        raise ValueError(
            f"Could not reach {request.host}: {error.reason if hasattr(error, 'reason') else error}"
        ) from error
    if not payload or len(payload) > 32_000_000:
        raise ValueError(f"Unexpected download size from {request.host}")
    return payload


def matches_class(record: dict, market: AmsterdamMarket) -> bool:
    # The exchange short name contains the class as a separate field, e.g. ASL.
    name = record["gnr_short_name"].split()
    return (
        len(name) == 7
        and name[:2] == ["ENXT", "NL/O"]
        and name[5] == market.option_class
        and record["mic"] == "XEUE"
        and record.get("drv_underlng_isin") == market.share_isin
        and record.get("drv_option_type") in {"CALL", "PUTO"}
        and record.get("gnr_notional_curr_code")
        == record.get("drv_sp_prc_value_curr_code")
        == "EUR"
    )


def listed_options(market: AmsterdamMarket, start: date, end: date, get) -> dict:
    # Each ESMA short name includes the expiry as YYYYMMDD. Narrow the search by
    # month and enforce the exact date, product class, venue and currency on each result.
    months = sorted(
        {(start + timedelta(days=i)).strftime("%Y%m") for i in range((end - start).days + 1)}
    )
    month_terms = " OR ".join(month + "*" for month in months)
    query = (
        f"drv_underlng_isin:{market.share_isin} AND mic:XEUE AND latest_received_flag:1 "
        f"AND gnr_short_name:{market.option_class} AND gnr_short_name:({month_terms})"
    )
    result = {}
    offset = 0
    while True:
        params = dict(
            q=query, rows=1000, start=offset, sort="isin asc,id asc", fl=REF_FIELDS, wt="json"
        )
        page = json.loads(get(FIRDS + "?" + urlencode(params)))["response"]
        if int(page["start"]) != offset:
            raise ValueError("ESMA returned an unexpected reference-data page")
        for record in page["docs"]:
            if not matches_class(record, market):
                continue
            expiry = date.fromisoformat(record["drv_expiry_date"][:10])
            if start <= expiry <= end:
                isin = record["isin"]
                if isin in result and result[isin] != record:
                    raise ValueError(f"Conflicting ESMA contract references for {isin}")
                result[isin] = record
        offset += len(page["docs"])
        if offset >= int(page["numFound"]):
            return result
        if not page["docs"]:
            raise ValueError("Incomplete ESMA reference-data response")


def publications(
    content: bytes, filename: str, venue: str, isins: Collection[str], trading_day: date
) -> list:
    if not content:  # The exchange returns HTTP 204 for an empty selection.
        return []
    try:
        with ZipFile(BytesIO(content)) as archive:
            info = archive.getinfo(filename)
            if info.file_size > 128_000_000:
                raise ValueError("Unexpected size for the Amsterdam trade file")
            with archive.open(info) as stream, TextIOWrapper(stream, encoding="utf-8-sig") as text:
                first = text.readline()
                if not first.startswith("TradingDateTime,"):
                    if "Euronext" not in first:
                        raise ValueError("Unrecognized Euronext CSV header")
                    first = text.readline()
                header = next(csv.reader([first]))
                if not TRADE_FIELDS.issubset(header):
                    raise ValueError("Euronext trade file is missing required columns")
                return [
                    row
                    for row in csv.DictReader(text, fieldnames=header)
                    if row["Venue"] == venue
                    and row["MifidInstrumentID"] in isins
                    and parse_time(row["TradingDateTime"]).astimezone(AMSTERDAM).date()
                    == trading_day
                ]
    except (BadZipFile, KeyError) as error:
        raise ValueError(f"Expected {filename} in the Euronext ZIP download") from error


def fetch_trades(
    market: AmsterdamMarket, expiry: date | None = None, *, get=download, now=None
) -> dict:
    """Capture the published executions for this Amsterdam trading date and option class."""
    now = now or (lambda: datetime.now(UTC))
    today = now().astimezone(AMSTERDAM).date()
    start = expiry or (today + timedelta(days=market.min_days_to_expiry))
    end = expiry or (today + timedelta(days=market.max_days_to_expiry))
    if start < today:
        raise ValueError("choose an Amsterdam expiry on or after the local trading date")
    terms = listed_options(market, start, end, get)
    if expiry and not terms:
        raise ValueError(f"ESMA lists no {market.option_class} options for {expiry}")
    option_url = f"{TRADE_FILES}/EQUITY_INDEX_DERIVATIVES/{market.window}/AMS"
    stock_url = f"{TRADE_FILES}/EQUITIES/{market.window}/AMS"
    options = publications(
        get(option_url), "Trades_EquityIndexDerivatives.csv", "XEUE", terms.keys(), today
    )
    stocks = publications(get(stock_url), "Trades_Equities.csv", "XAMS", {market.share_isin}, today)
    selected = sorted({r["MifidInstrumentID"] for r in options})
    return {
        "format": FORMAT,
        "retrieved_at": iso(now()),
        "trading_day": today.isoformat(),
        "underlying": market.underlying,
        "share_isin": market.share_isin,
        "option_class": market.option_class,
        "window": market.window,
        "expiry_from": start.isoformat(),
        "expiry_to": end.isoformat(),
        "listed_contracts": len(terms),
        "sources": {"options": option_url, "stock": stock_url, "reference": FIRDS},
        "contracts": {k: terms[k] for k in selected},
        "options": options,
        "stock": stocks,
    }
