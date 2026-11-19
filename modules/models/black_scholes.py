"""Calculate European Black–Scholes–Merton scenario values per underlying share.

The scalar function accepts time in years, a constant volatility and continuously
compounded risk-free and dividend rates. The snapshot adapter measures actual elapsed
seconds over a fixed 365-day year. The same formula can serve as a baseline for
American-style contracts, with early exercise and discrete dividends outside its
assumptions.
"""

from math import erfc, exp, isfinite, log, sqrt

from options_lab.config import Model
from options_lab.domain import Quote, Snapshot

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
    """Price one European call or put on an underlying with a continuous dividend yield.

    kind is either "call" or "put". spot and strike are positive amounts in the same
    currency per underlying share. years is the nonnegative time to expiry. rate and
    dividend_yield are continuously compounded annual decimals. volatility is annualized
    standard deviation in decimal units, so 0.25 represents 25%.

    Return the premium per share before any contract multiplier or fees. At expiry the
    result is intrinsic value. With zero volatility and positive time it is the positive
    part of the signed difference between discounted spot and strike. A negative interest
    rate is supported. Nonfinite inputs, unknown option kinds or invalid domains raise
    ValueError.
    """
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
        """Evaluate the standard normal cumulative probability at x.

        Use the complementary error function to compute the lower-tail probability,
        including for negative arguments. Applying the same function to signed d1 and d2
        lets the call and put formulas share the discounting and arithmetic.
        """
        return erfc(-x / sqrt(2)) / 2

    return max(0.0, sign * (discounted_spot * cdf(sign * d1) - discounted_strike * cdf(sign * d2)))


def model_value(snapshot: Snapshot, quote: Quote, model: Model) -> float | None:
    """Value a snapshot's contract at the time the complete quote capture was retrieved.

    Use quote.contract for the option kind, strike and expiry. The underlying price comes
    from snapshot.spot and the three annual scenario parameters come from model. Convert
    the UTC interval from retrieval to expiry to years on an ACT/365F basis.

    Return the per-share price, or None for a missing or nonpositive spot or a retrieval
    past expiry. Exactly at expiry the scalar model gives intrinsic value. The caller
    decides whether quote age, currency or other quality flags make the value usable.
    """
    c = quote.contract
    years = (c.expiry_at - snapshot.retrieved_at).total_seconds() / YEAR_SECONDS
    if snapshot.spot is None or snapshot.spot <= 0 or years < 0:
        return None
    return black_scholes(
        c.kind, snapshot.spot, c.strike, years, model.rate, model.dividend_yield, model.volatility
    )
