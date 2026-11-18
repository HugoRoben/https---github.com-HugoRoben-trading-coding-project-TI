from decimal import Decimal, ROUND_HALF_UP

from .config import Settings
from .domain import Quote, Snapshot
from .pricing import model_value
from .validation import quality_flags


def money(value: float) -> Decimal:
    return Decimal(str(value))


def fill_amount(quote: Quote, side: str, settings: Settings) -> tuple[Decimal, Decimal]:
    """Slipped price per share and signed cash change for one contract, including the fee."""
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
