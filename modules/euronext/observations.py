"""Pair each ordinary option execution with an earlier Amsterdam share execution."""

from bisect import bisect_right
from datetime import date, datetime, time
from math import isfinite
from typing import NamedTuple

from options_lab.config import AmsterdamMarket
from options_lab.domain import iso, parse_time

from .retrieval import AMSTERDAM, FORMAT, matches_class


class Execution(NamedTuple):
    traded: datetime
    published: datetime
    trade_id: str
    isin: str
    price: float
    quantity: float


def positive(value) -> float | None:
    if value in ("", None):
        return None
    number = float(value)
    return number if isfinite(number) and number > 0 else None


def ordinary_trades(rows, venue, isins, day, retrieved) -> list[Execution]:
    # A later cancellation or amendment disqualifies the original print in this window.
    latest = {}
    for row in rows:
        traded = parse_time(row["TradingDateTime"])
        published = parse_time(row["PublicationDateTime"])
        if (
            row["Venue"] != venue
            or row["MifidInstrumentID"] not in isins
            or traded.astimezone(AMSTERDAM).date() != day
            or traded > published
            or published > retrieved
        ):
            raise ValueError("Inconsistent trade venue, instrument, or timestamps in capture")
        key = row["TradeUniqueIdentifier"]
        if not key:
            raise ValueError("Missing Euronext trade identifier")
        if key in latest and published == latest[key][0] and row != latest[key][1]:
            raise ValueError(f"Conflicting Euronext publications for {key}")
        if key not in latest or published > latest[key][0]:
            latest[key] = (published, row)
    result = []
    for published, row in latest.values():
        if (
            row["MmtModificationIndicator"] != "-"
            or row["MifidCurrency"] != "EUR"
            or row["MifidPriceNotation"] != "MONE"
        ):
            continue
        price, quantity = positive(row["MifidPrice"]), positive(row["MifidQuantity"])
        if price is not None and quantity is not None:
            result.append(
                Execution(
                    parse_time(row["TradingDateTime"]),
                    published,
                    row["TradeUniqueIdentifier"],
                    row["MifidInstrumentID"],
                    price,
                    quantity,
                )
            )
    return sorted(result)


def trade_rows(raw: dict, market: AmsterdamMarket) -> list[dict]:
    if raw["format"] != FORMAT or (raw["underlying"], raw["share_isin"], raw["option_class"]) != (
        market.underlying,
        market.share_isin,
        market.option_class,
    ):
        raise ValueError("Capture does not match the selected Amsterdam profile")
    day = date.fromisoformat(raw["trading_day"])
    retrieved = parse_time(raw["retrieved_at"])
    stocks = ordinary_trades(raw["stock"], "XAMS", {market.share_isin}, day, retrieved)
    options = ordinary_trades(raw["options"], "XEUE", raw["contracts"], day, retrieved)
    stock_times = [trade.traded for trade in stocks]
    first_expiry = date.fromisoformat(raw["expiry_from"])
    last_expiry = date.fromisoformat(raw["expiry_to"])
    rows = []
    for traded, published, trade_id, isin, price, quantity in options:
        record = raw["contracts"][isin]
        if record["isin"] != isin or not matches_class(record, market):
            raise ValueError(f"Unexpected Amsterdam contract reference for {isin}")
        expiry_date = date.fromisoformat(record["drv_expiry_date"][:10])
        if not first_expiry <= expiry_date <= last_expiry:
            raise ValueError(f"Unexpected expiry for {isin}")
        cutoff = record.get("mrkt_trdng_trmination_date")
        expiry = parse_time(cutoff) if cutoff else None
        assumed = expiry is None or expiry.astimezone(AMSTERDAM).date() != expiry_date
        if assumed:
            expiry = datetime.combine(expiry_date, time(17, 30), AMSTERDAM)
        strike = positive(record["drv_sp_prc_value_amount"])
        if strike is None:
            raise ValueError(f"Invalid strike for {isin}")
        # Exclude any stock print that was only published after the option traded.
        idx = bisect_right(stock_times, traded) - 1
        while idx >= 0 and stocks[idx].published > traded:
            idx -= 1
        stock = stocks[idx] if idx >= 0 else None
        rows.append(
            dict(
                trade_id=trade_id,
                option_isin=isin,
                traded_utc=iso(traded),
                published_utc=iso(published),
                kind={"CALL": "call", "PUTO": "put"}[record["drv_option_type"]],
                strike_eur=strike,
                expiry_utc=iso(expiry),
                assumed_cutoff=int(assumed),
                exercise_style={"AMER": "american", "EURO": "european"}.get(
                    record.get("drv_option_exercise_style"), "unknown"
                ),
                multiplier=positive(record.get("drv_price_multiplier")),
                quantity=quantity,
                trade_eur=price,
                stock_trade_id=stock.trade_id if stock else None,
                stock_utc=iso(stock.traded) if stock else None,
                stock_eur=stock.price if stock else None,
            )
        )
    return rows
