from .config import Quality
from .domain import Quote, Snapshot


def quality_flags(snapshot: Snapshot, quote: Quote, quality: Quality) -> list[str]:
    flags = []
    if quote.bid is None or quote.ask is None:
        flags.append("missing_bid_ask")
    elif min(quote.bid, quote.ask) <= 0:
        flags.append("nonpositive_bid_ask")
    elif quote.bid > quote.ask:
        flags.append("crossed_quote")
    if snapshot.spot is None or snapshot.spot <= 0:
        flags.append("missing_or_invalid_spot")
    for label, timestamp in (("option", quote.quote_at), ("underlying", snapshot.underlying_at)):
        if timestamp is None:
            flags.append(f"missing_{label}_time")
            continue
        age = (snapshot.retrieved_at - timestamp).total_seconds()
        if age < 0:
            flags.append(f"future_{label}")
        elif age > quality.max_age_seconds:
            flags.append(f"stale_{label}")
    if quote.quote_at and snapshot.underlying_at:
        skew = abs((quote.quote_at - snapshot.underlying_at).total_seconds())
        if skew > quality.max_skew_seconds:
            flags.append("unsynchronized")
    c = quote.contract
    if c.expiry_at <= snapshot.retrieved_at:
        flags.append("expired")
    if c.multiplier is None or c.multiplier <= 0:
        flags.append("unknown_or_invalid_multiplier")
    if c.exercise_style not in ("american", "european"):
        flags.append("unknown_exercise_style")
    if c.currency != "USD":
        flags.append("unsupported_currency")
    return flags
