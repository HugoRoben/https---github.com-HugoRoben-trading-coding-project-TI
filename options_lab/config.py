"""Load immutable settings for the U.S. quote and Amsterdam execution workflows.

The TOML section names identify the profile. The U.S. profile combines collection,
quote-quality checks, pricing and a synthetic USD replay. The Amsterdam profile combines a
share and option class, publication window and EUR pricing scenario. The shared Model type
holds annual inputs, while the other settings express each workflow's units and selection
rules.
"""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Collection:
    """Configure contract discovery and capture timing for an Alpaca session.

    underlying is the U.S. ticker. The minimum and maximum days to expiry define an
    inclusive calendar-day search relative to the New York date. strike_band_fraction is
    the fraction on either side of the first stock midpoint. nearest_strikes caps distinct
    strikes at the earliest returned expiry, keeping available calls and puts.
    interval_seconds sets the default pause between completed captures.
    """

    underlying: str
    min_days_to_expiry: int
    max_days_to_expiry: int
    strike_band_fraction: float
    nearest_strikes: int
    interval_seconds: int


@dataclass(frozen=True)
class Model:
    """Hold the annual inputs for a constant-parameter European pricing scenario.

    rate is the continuously compounded risk-free rate, dividend_yield is the continuous
    dividend yield, and volatility is annualized standard deviation. All three are
    decimals, so 0.02 means 2%. The profile determines the pricing currency. Reports
    preserve these supplied assumptions so a saved valuation can be reproduced.
    """

    rate: float
    dividend_yield: float
    volatility: float


@dataclass(frozen=True)
class Quality:
    """Set the maximum ages and clock disagreement allowed on a USD quote row.

    max_age_seconds compares both the stock and option observation times with the
    snapshot's retrieval time. max_skew_seconds bounds the absolute gap between the two
    observations. A difference equal to its configured limit is allowed. Validation records
    separate flags for stale, future and missing timestamps.
    """

    max_age_seconds: int
    max_skew_seconds: int


@dataclass(frozen=True)
class Simulation:
    """Specify available capital, entry threshold, execution costs and holding time.

    initial_cash_usd is the starting cash balance. To signal an entry, the model price
    minus the ask must exceed entry_buffer_per_share. Each fill incurs adverse slippage
    of slippage_per_share and a fee of fee_per_contract_usd for the one contract.
    hold_minutes sets the planned holding period from the entry capture.
    """

    initial_cash_usd: float
    entry_buffer_per_share: float
    fee_per_contract_usd: float
    slippage_per_share: float
    hold_minutes: int


@dataclass(frozen=True)
class Settings:
    """Bundle the configuration shared by the USD market and synthetic workflows.

    collection selects the Alpaca quote universe. model supplies per-share scenario inputs,
    quality controls the admissibility of observations, and simulation sets capital and
    fill rules for the fixture replay. The report writer serializes the bundle with its
    input provenance.
    """

    collection: Collection
    model: Model
    quality: Quality
    simulation: Simulation


@dataclass(frozen=True)
class AmsterdamMarket:
    """Select the Dutch cash share, derivative class and publication window to collect.

    underlying labels the share, share_isin identifies it in the trade files and FIRDS, and
    option_class selects the exchange product. window selects the exchange's rolling trade
    file. The expiry bounds count calendar days from the Amsterdam trading date and may
    include same-day expiries.

    interval_seconds controls polling. max_spot_age_seconds is a separate pricing limit on
    the age of the matched share execution at the time the option traded.
    """

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
    """Bundle the Amsterdam market selection with its EUR pricing scenario.

    euronext determines which share, product class, trading window and spot-age threshold
    the collector and report reader use. model supplies the rate, yield and volatility for
    per-share valuations. Changing model assumptions allows a stored window to be repriced
    from the same archived executions.
    """

    euronext: AmsterdamMarket
    model: Model


def load_settings(path: Path = ROOT / "config/default.toml") -> Settings | AmsterdamSettings:
    """Read a TOML profile and validate the settings used by its workflow.

    path defaults to the bundled U.S. configuration. A file containing an euronext section
    produces AmsterdamSettings. Its identifiers, rolling window, calendar-day bounds and
    timing limits are validated. A U.S. profile produces Settings after checking its
    ticker, strike and expiry selection, quality thresholds, capital and trading costs.

    Model inputs are annual decimals. Validation accepts finite rates and yields and
    requires nonnegative volatility. File access, TOML syntax, missing fields and invalid
    values surface to the caller. Loading the profile does not open a database or contact a
    provider.
    """
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
