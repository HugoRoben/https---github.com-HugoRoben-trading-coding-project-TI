"""Decode the stock quote, contract metadata, and option quotes in a raw capture."""

from datetime import UTC, date, datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

from options_lab.domain import Contract, Quote, Snapshot, parse_time

NEW_YORK = ZoneInfo("America/New_York")
FORMAT = "alpaca-options-v1"


def number(value) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if isfinite(result) else None


def stock_midpoint(response: dict) -> float | None:
    quote = response.get("quote") or {}
    bid, ask = number(quote.get("bp")), number(quote.get("ap"))
    if bid is None or ask is None or not 0 < bid <= ask:
        return None
    return (bid + ask) / 2


def normalize(raw: dict) -> Snapshot:
    """Convert one raw Alpaca capture into a snapshot of the underlying and its options."""
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
