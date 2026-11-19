"""Translate an archived Alpaca capture into the records used by pricing and storage.

The underlying observation is the midpoint of the IEX bid and ask. Each selected option
carries its own indicative quote time and the contract terms returned by the catalog.
Exchange observation times and the collector's retrieval time remain available
independently for age and synchronization checks.
"""

from datetime import UTC, date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

from options_lab.domain import Contract, Quote, Snapshot, parse_time

NEW_YORK = ZoneInfo("America/New_York")
FORMAT = "alpaca-options-v1"


def number(value) -> float | None:
    """Convert an optional provider field to a finite float.

    Return None for a missing value, an empty string, NaN or either infinity. Numeric
    strings and numbers are converted through float. A malformed nonempty value raises a
    conversion error. Zero and negative values pass through so the caller can apply the
    appropriate rule for a price, bid or multiplier.
    """
    if value in (None, ""):
        return None
    result = float(value)
    return result if isfinite(result) else None


def stock_midpoint(response: dict) -> float | None:
    """Compute the underlying price proxy from a latest-stock-quote response.

    Read bp and ap from the nested quote mapping and take their arithmetic mean in USD per
    share. Return None if either side is absent or nonfinite, the bid is nonpositive, or
    the bid exceeds the ask. A locked positive quote is usable. The collector requires a
    usable midpoint for its initial strike selection.
    """
    quote = response.get("quote") or {}
    bid, ask = number(quote.get("bp")), number(quote.get("ap"))
    if bid is None or ask is None or not 0 < bid <= ask:
        return None
    return (bid + ask) / 2


def normalize(raw: dict) -> Snapshot:
    """Build a Snapshot from one raw IEX-stock and indicative-options capture.

    Check the archived format, feed names and underlying symbol. Join every selected option
    symbol to its archived contract terms. A missing option observation still produces a
    Quote with empty fields. A provider expiry date becomes an assumed 16:00 New York
    cutoff converted to UTC. An absent multiplier stays unknown.

    Return a market Snapshot with the original capture ID, retrieval time, stock midpoint
    and timestamp, and a tuple of option quotes. Invalid feed or symbol combinations raise
    ValueError. Required structural fields must be present in the archive. No network or
    database access is needed.
    """
    if raw["format"] != FORMAT or (raw["option_feed"], raw["underlying_feed"]) != (
        "indicative",
        "iex",
    ):
        raise ValueError("unsupported capture format or feeds")
    symbol = raw["underlying"]
    stock = raw["stock_response"]
    if stock.get("symbol", symbol) != symbol:
        raise ValueError("stock response does not match the requested underlying")
    universe = raw["universe"]
    metadata = {
        c["symbol"]: c for page in universe["pages"] for c in (page["option_contracts"] or [])
    }
    book = raw["options_response"]["quotes"] or {}
    quotes = []
    for name in universe["symbols"]:
        c = metadata[name]
        # The provider supplies an expiry date. The local cutoff is a model convention.
        expiry_at = datetime.combine(date.fromisoformat(c["expiration_date"]), time(16), NEW_YORK)
        contract = Contract(
            name,
            c["underlying_symbol"],
            expiry_at.astimezone(UTC),
            c["type"],
            float(c["strike_price"]),
            "USD",
            number(c.get("multiplier")),
            c.get("style") or "unknown",
            expiry_time_assumed=True,
        )
        q = book.get(name) or {}
        quotes.append(
            Quote(
                contract,
                parse_time(q["t"]) if q.get("t") else None,
                number(q.get("bp")),
                number(q.get("ap")),
            )
        )
    timestamp = (stock.get("quote") or {}).get("t")
    return Snapshot(
        raw["capture_id"],
        "market",
        "alpaca",
        raw["option_feed"],
        raw["underlying_feed"],
        parse_time(raw["retrieved_at"]),
        symbol,
        stock_midpoint(stock),
        parse_time(timestamp) if timestamp else None,
        tuple(quotes),
    )
