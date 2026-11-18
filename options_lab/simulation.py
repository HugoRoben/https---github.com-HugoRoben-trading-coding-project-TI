"""One synthetic long contract at a time. Decisions use capture availability in UTC."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from .config import Settings
from .domain import Contract, Snapshot, iso
from .strategies import entry_candidate, fill_amount, money
from .validation import quality_flags


@dataclass(frozen=True)
class Order:
    contract: Contract
    signalled_at: datetime


@dataclass(frozen=True)
class Position:
    contract: Contract
    entered_at: datetime
    entry_cost: Decimal


def replay(snapshots: list[Snapshot], close_at: datetime, settings: Settings) -> dict:
    frames = sorted(
        (s for s in snapshots if s.retrieved_at <= close_at), key=lambda s: s.retrieved_at
    )
    if not frames or any(s.source != "synthetic" for s in frames):
        raise ValueError("replay requires synthetic captures within the planned session")
    if len({s.retrieved_at for s in frames}) != len(frames):
        raise ValueError("replay requires distinct decision times")
    rules = settings.simulation
    hold = timedelta(minutes=rules.hold_minutes)
    start = cash = money(rules.initial_cash_usd)
    realized = Decimal(0)
    closed = 0
    position = pending = None
    events = []

    def record(action, frame, quote, **details):
        events.append(
            dict(
                action=action,
                capture_id=frame.capture_id,
                at=iso(frame.retrieved_at),
                symbol=quote.contract.symbol,
                quote_at=iso(quote.quote_at),
                cash_usd=str(cash),
                **details,
            )
        )

    for frame in frames:
        now = frame.retrieved_at
        at_close = now == close_at
        if position or pending:
            contract = position.contract if position else pending.contract
            quote = next((q for q in frame.quotes if q.contract == contract), None)
            if quote is None or quality_flags(frame, quote, settings.quality):
                continue
            if position:
                due = position.entered_at + hold
                if quote.quote_at <= position.entered_at or (not at_close and quote.quote_at < due):
                    continue
                price, proceeds = fill_amount(quote, "sell", settings)
                pnl = proceeds - position.entry_cost
                cash += proceeds
                realized += pnl
                closed += 1
                record(
                    "sell",
                    frame,
                    quote,
                    price_per_share=str(price),
                    cash_change_usd=str(proceeds),
                    fee_usd=str(money(rules.fee_per_contract_usd)),
                    quantity=1,
                    multiplier=contract.multiplier,
                    trade_pnl_usd=str(pnl),
                    reason="hold_elapsed" if quote.quote_at >= due else "scheduled_close",
                )
                position = None
            elif not at_close and quote.quote_at > pending.signalled_at:
                price, change = fill_amount(quote, "buy", settings)
                if min(now + hold, close_at) >= contract.expiry_at:
                    record("cancel", frame, quote, reason="planned_exit_reaches_expiry")
                elif cash + change < 0:
                    record("cancel", frame, quote, reason="insufficient_cash_at_fill")
                else:
                    cash += change
                    position = Position(contract, now, -change)
                    record(
                        "buy",
                        frame,
                        quote,
                        price_per_share=str(price),
                        cash_change_usd=str(change),
                        fee_usd=str(money(rules.fee_per_contract_usd)),
                        quantity=1,
                        multiplier=contract.multiplier,
                        signal_at=iso(pending.signalled_at),
                    )
                pending = None
            continue
        if not at_close:
            candidate = entry_candidate(frame, cash, settings)
            if candidate:
                pending = Order(candidate.contract, now)
                record("signal", frame, candidate, reason="model_above_ask_plus_buffer")

    unrealized = Decimal(0)
    status = "flat"
    if position:
        last = frames[-1]
        mark = next((q for q in last.quotes if q.contract == position.contract), None)
        if (
            last.retrieved_at == close_at
            and mark
            and not quality_flags(last, mark, settings.quality)
        ):
            unrealized = fill_amount(mark, "sell", settings)[1] - position.entry_cost
            status = "open_marked_at_last_capture"
        else:
            unrealized = None
            status = "open_unpriced"
    total = None if unrealized is None else realized + unrealized
    return dict(
        source="synthetic",
        session_close_utc=iso(close_at),
        last_capture_utc=iso(frames[-1].retrieved_at),
        position_status=status,
        open_symbol=position.contract.symbol if position else None,
        unfilled_signal=pending.contract.symbol if pending else None,
        closed_trades=closed,
        initial_cash_usd=str(start),
        cash_usd=str(cash),
        realized_pnl_usd=str(realized),
        unrealized_pnl_usd=None if unrealized is None else str(unrealized),
        equity_usd=None if total is None else str(start + total),
        events=events,
    )
