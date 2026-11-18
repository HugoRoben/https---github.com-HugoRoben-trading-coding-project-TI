"""Settings for U.S. quote collection and Amsterdam trade collection."""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Collection:
    underlying: str
    min_days_to_expiry: int
    max_days_to_expiry: int
    strike_band_fraction: float
    nearest_strikes: int
    interval_seconds: int


@dataclass(frozen=True)
class Model:
    rate: float
    dividend_yield: float
    volatility: float


@dataclass(frozen=True)
class Quality:
    max_age_seconds: int
    max_skew_seconds: int


@dataclass(frozen=True)
class Simulation:
    initial_cash_usd: float
    entry_buffer_per_share: float
    fee_per_contract_usd: float
    slippage_per_share: float
    hold_minutes: int


@dataclass(frozen=True)
class Settings:
    collection: Collection
    model: Model
    quality: Quality
    simulation: Simulation


@dataclass(frozen=True)
class AmsterdamMarket:
    underlying: str
    share_isin: str
    option_class: str
    window: str
    min_days_to_expiry: int
    max_days_to_expiry: int
    interval_seconds: int
    max_spot_age_seconds: int


@dataclass(frozen=True)
class AmsterdamSettings:
    euronext: AmsterdamMarket
    model: Model


def load_settings(path: Path = ROOT / "config/default.toml") -> Settings | AmsterdamSettings:
    with path.open("rb") as file:
        data = tomllib.load(file)
    m = Model(**data["model"])
    if "euronext" in data:
        e = AmsterdamMarket(**data["euronext"])
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", e.share_isin) or not re.fullmatch(
            r"[A-Z0-9]+", e.option_class
        ):
            raise ValueError("expected a share ISIN and an Amsterdam option class")
        if e.window not in {"LAST_15_MINUTES", "LAST_HOUR"}:
            raise ValueError("choose LAST_15_MINUTES or LAST_HOUR for the Amsterdam tape")
        if not all(
            type(n) is int
            for n in (
                e.min_days_to_expiry,
                e.max_days_to_expiry,
                e.interval_seconds,
                e.max_spot_age_seconds,
            )
        ):
            raise ValueError("Amsterdam day and second settings must be whole numbers")
        if not (0 <= e.min_days_to_expiry <= e.max_days_to_expiry <= 366):
            raise ValueError("choose an Amsterdam expiry window between 0 and 366 days")
        if min(e.interval_seconds, e.max_spot_age_seconds) <= 0:
            raise ValueError("collection interval and stock age limit must be positive")
        if (
            not all(isfinite(v) for v in (m.rate, m.dividend_yield, m.volatility))
            or m.volatility < 0
        ):
            raise ValueError("expected finite model inputs and nonnegative volatility")
        return AmsterdamSettings(e, m)
    c = Collection(**data["collection"])
    q = Quality(**data["quality"])
    s = Simulation(**data["simulation"])
    if not c.underlying.isalpha() or not c.underlying.isupper():
        raise ValueError("collection.underlying must be an uppercase US stock ticker")
    if not (1 <= c.min_days_to_expiry <= c.max_days_to_expiry and 0 < c.strike_band_fraction < 1):
        raise ValueError("invalid collection expiry window or strike band")
    if not (isinstance(c.nearest_strikes, int) and 1 <= c.nearest_strikes <= 50):
        raise ValueError("choose 1–50 strikes per expiry")
    if min(c.interval_seconds, s.hold_minutes) <= 0:
        raise ValueError("collection interval and holding time must be positive")
    nonnegative = (
        m.volatility,
        q.max_age_seconds,
        q.max_skew_seconds,
        s.initial_cash_usd,
        s.entry_buffer_per_share,
        s.fee_per_contract_usd,
        s.slippage_per_share,
    )
    if not all(isfinite(x) and x >= 0 for x in nonnegative):
        raise ValueError(
            "volatility, quality thresholds, capital and costs must be finite and nonnegative"
        )
    if not all(isfinite(x) for x in (m.rate, m.dividend_yield, c.interval_seconds, s.hold_minutes)):
        raise ValueError("rates, interval and holding time must be finite")
    return Settings(c, m, q, s)
