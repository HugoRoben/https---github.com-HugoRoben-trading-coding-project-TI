from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"missing UTC offset: {value}")
    return dt.astimezone(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("timestamp requires a UTC offset")
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def digest(data: object) -> str:
    return sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Contract:
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
    contract: Contract
    quote_at: datetime | None
    bid: float | None
    ask: float | None


@dataclass(frozen=True)
class Snapshot:
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
