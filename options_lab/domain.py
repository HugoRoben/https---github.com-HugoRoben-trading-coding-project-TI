"""Define the shared records and serialization conventions for option quote captures.

Contract, Quote and Snapshot are immutable records used by the Alpaca and synthetic paths.
They keep feed identity, contract terms and the separate availability and observation
clocks together. The time and digest helpers also provide the canonical representation used
in archives, SQLite references and report identifiers.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json


def parse_time(value: str) -> datetime:
    """Parse an offset-aware ISO timestamp and return the same instant in UTC.

    value may end in Z or carry an explicit offset such as +01:00. Converting to UTC keeps
    retrieval, quote and expiry times comparable across venues and daylight-saving
    transitions. Invalid text or a timestamp with no timezone offset raises ValueError.
    """
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"missing UTC offset: {value}")
    return dt.astimezone(UTC)


def iso(dt: datetime) -> str:
    """Serialize an aware datetime as a fixed-width UTC timestamp.

    Convert dt to UTC and emit ISO text ending in Z with six fractional-second digits. This
    common format is used for persisted observation times, sortable database timestamps and
    report provenance. A timezone-naive datetime raises ValueError because the intended
    instant cannot be inferred.
    """
    if dt.tzinfo is None:
        raise ValueError("timestamp requires a UTC offset")
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def digest(data: object) -> str:
    """Return the hexadecimal SHA-256 of a canonical JSON representation.

    Encode data as UTF-8 JSON with sorted mapping keys and compact separators. Mapping
    insertion order and pretty-printing therefore have no effect on a content identifier,
    while sequence order is preserved. Values must be JSON-serializable. NaN and infinities
    raise ValueError, and unsupported objects raise TypeError.
    """
    return sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Contract:
    """Describe the option terms observed when a quote was captured.

    symbol and underlying identify the instruments. kind is call or put. strike is in the
    stated currency per underlying share, and multiplier gives the number of share units
    used to convert a per-share premium to a contract amount. A missing multiplier remains
    None. exercise_style records the source classification or "unknown".

    expiry_at is the timezone-aware cutoff used for valuation. expiry_time_assumed marks a
    cutoff inferred from a date-only source. Storage versions these terms independently of
    the symbol so a later correction can coexist with the original capture.
    """

    symbol: str
    underlying: str
    expiry_at: datetime
    kind: str
    strike: float
    currency: str
    multiplier: float | None
    exercise_style: str
    expiry_time_assumed: bool = False


@dataclass(frozen=True)
class Quote:
    """Associate both observed sides of an option market with a contract version.

    bid and ask are premiums per underlying share in the contract currency. quote_at is the
    option feed's own timestamp. Missing sides or an unavailable timestamp stay None so
    validation and reports can explain which observations were usable. Retrieval time and
    the corresponding stock price belong to the enclosing Snapshot.
    """

    contract: Contract
    quote_at: datetime | None
    bid: float | None
    ask: float | None


@dataclass(frozen=True)
class Snapshot:
    """Group one retrieval of an underlying and its selected option quotes.

    capture_id identifies the batch. source distinguishes synthetic from market
    observations, and provider and feed labels identify the input streams. retrieved_at is
    when the batch was available to the collector. underlying_at timestamps the observation
    behind spot, which may be missing.

    quotes holds the observed contracts and their individual quote timestamps. Retaining
    all three clocks lets replay order decisions by availability and lets validation detect
    stale or unsynchronized market inputs.
    """

    capture_id: str
    source: str
    provider: str
    option_feed: str
    underlying_feed: str
    retrieved_at: datetime
    underlying: str
    spot: float | None
    underlying_at: datetime | None
    quotes: tuple[Quote, ...]
