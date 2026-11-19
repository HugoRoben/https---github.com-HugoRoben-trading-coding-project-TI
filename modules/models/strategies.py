"""Define the entry signal and one-contract cash flows for the USD synthetic replay.

A call becomes a candidate when the per-share model value exceeds its ask by the configured
buffer. Bid/ask, per-share slippage, the observed contract multiplier and fees then
determine affordability and cash movements. Simulation decides when a signal may be filled
and when a position can exit.
"""

from decimal import Decimal, ROUND_HALF_UP

from options_lab.config import Settings
from options_lab.domain import Quote, Snapshot
from options_lab.validation import quality_flags

from .black_scholes import model_value


def money(value: float) -> Decimal:
    """Convert a numeric scenario or quote value to Decimal through its text form.

    This keeps the decimal digits shown by the input when mixing quoted prices, fees and
    balances in cash calculations. It performs no cent rounding. The fill calculation
    rounds the final contract-level cash movement after applying slippage and the fee.
    """
    return Decimal(str(value))


def fill_amount(quote: Quote, side: str, settings: Settings) -> tuple[Decimal, Decimal]:
    """Calculate a slipped per-share fill and signed USD cash change for one contract.

    For a buy, add configured slippage to the ask, multiply by the observed contract
    multiplier and debit the fee. For a sell, subtract slippage from the bid with a floor
    at zero, multiply and deduct the fee from proceeds. quote must contain the required
    quote side and a usable multiplier.

    Return two Decimals, the fill price per share and the cash change rounded half-up to
    cents. The fee is charged once per side. An unrecognized side raises ValueError. The
    calculation does not mutate a portfolio.
    """
    rules = settings.simulation
    slip = money(rules.slippage_per_share)
    fee = money(rules.fee_per_contract_usd)
    multiplier = money(quote.contract.multiplier)
    if side == "buy":
        price = money(quote.ask) + slip
        change = -price * multiplier - fee
    elif side == "sell":
        price = max(Decimal(0), money(quote.bid) - slip)
        change = price * multiplier - fee
    else:
        raise ValueError("unknown fill side")
    return price, change.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def entry_candidate(snapshot: Snapshot, cash: Decimal, settings: Settings) -> Quote | None:
    """Choose an affordable eligible call for a signal at this snapshot.

    Discard calls with quality flags and require model value minus ask to exceed the
    configured per-share buffer strictly. Check cash against a one-contract buy including
    the observed multiplier, slippage and fee. Among qualifying calls choose the greatest
    model-minus-ask difference, breaking ties by symbol.

    Return the selected Quote or None if there is no candidate. The replay records the
    signal at retrieval time and checks affordability again when a later quote can fill it.
    """
    candidates = []
    for quote in snapshot.quotes:
        if quote.contract.kind != "call" or quality_flags(snapshot, quote, settings.quality):
            continue
        edge = model_value(snapshot, quote, settings.model) - quote.ask
        if edge <= settings.simulation.entry_buffer_per_share:
            continue
        if cash + fill_amount(quote, "buy", settings)[1] >= 0:
            candidates.append((-edge, quote.contract.symbol, quote))
    return min(candidates, key=lambda item: item[:2])[2] if candidates else None
