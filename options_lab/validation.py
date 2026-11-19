"""Assess USD quote quality at the time a snapshot became available.

These checks compare the option clock and underlying clock separately with retrieval time
and with each other. They also check price sides and the contract metadata used in pricing
and fill accounting. Storage saves the resulting flags and downstream consumers decide
whether a row can support a model comparison or a simulated fill.
"""

from .config import Quality
from .domain import Quote, Snapshot


def quality_flags(snapshot: Snapshot, quote: Quote, quality: Quality) -> list[str]:
    """List the price, timestamp and contract-quality issues on one USD quote row.

    Compare the bid and ask for presence, positivity and a crossed market. Check the stock
    price and measure the ages of the option and stock observations against
    snapshot.retrieved_at. Flag missing, future or stale timestamps and excessive
    cross-feed skew using quality's second-based limits.

    Also check expiry at retrieval, a positive multiplier, a recognized exercise style and
    USD currency. Return the applicable flag strings in check order, or an empty list for a
    passing row. This function leaves the original observation intact so ingest and
    analysis can apply different thresholds.
    """
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
