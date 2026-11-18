"""European Black–Scholes–Merton values per share; ACT/365F for timestamp inputs."""

from math import erfc, exp, isfinite, log, sqrt

from .config import Model
from .domain import Quote, Snapshot

YEAR_SECONDS = 365 * 24 * 60 * 60


def black_scholes(
    kind: str,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    dividend_yield: float,
    volatility: float,
) -> float:
    if kind not in ("call", "put"):
        raise ValueError("kind must be call or put")
    if not all(isfinite(x) for x in (spot, strike, years, rate, dividend_yield, volatility)):
        raise ValueError("pricing inputs must be finite")
    if min(spot, strike) <= 0 or min(years, volatility) < 0:
        raise ValueError("positive spot and strike, nonnegative time and volatility required")
    sign = 1 if kind == "call" else -1
    discounted_spot = spot * exp(-dividend_yield * years)
    discounted_strike = strike * exp(-rate * years)
    scale = volatility * sqrt(years)
    if scale == 0:
        return max(sign * (discounted_spot - discounted_strike), 0.0)
    d1 = (log(spot / strike) + (rate - dividend_yield + volatility**2 / 2) * years) / scale
    d2 = d1 - scale

    def cdf(x: float) -> float:
        return erfc(-x / sqrt(2)) / 2

    return max(0.0, sign * (discounted_spot * cdf(sign * d1) - discounted_strike * cdf(sign * d2)))


def model_value(snapshot: Snapshot, quote: Quote, model: Model) -> float | None:
    c = quote.contract
    years = (c.expiry_at - snapshot.retrieved_at).total_seconds() / YEAR_SECONDS
    if snapshot.spot is None or snapshot.spot <= 0 or years < 0:
        return None
    return black_scholes(
        c.kind, snapshot.spot, c.strike, years, model.rate, model.dividend_yield, model.volatility
    )
