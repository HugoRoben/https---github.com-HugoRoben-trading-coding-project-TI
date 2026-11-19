"""Replay an explicitly timed, single-position strategy on synthetic USD quote captures.

The replay distinguishes when a complete capture becomes available from the option quote's
exchange timestamp. A signal, entry and exit are separate events, with costs and cash
checked at the relevant fill. The returned ledger drives the notebook's completed-trades
table and the saved replay report.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from options_lab.config import Settings
from options_lab.domain import Contract, Snapshot, iso
from options_lab.validation import quality_flags

from .strategies import entry_candidate, fill_amount, money


@dataclass(frozen=True)
class Order:
    """Hold the contract and decision time of an unfilled synthetic entry signal.

    signalled_at is the retrieval time of the snapshot that generated the signal. A later
    eligible quote must have a strictly newer option timestamp to fill the order. Storing
    the full contract also binds the order to the observed terms, including its expiry and
    multiplier.
    """

    contract: Contract
    signalled_at: datetime


@dataclass(frozen=True)
class Position:
    """Carry the entry terms of the single long option contract held in the replay.

    entered_at is the retrieval time of the filled entry and starts the holding-period
    clock. entry_cost is the positive USD cash outlay for one contract, including entry
    slippage and fee. The exit calculation subtracts this amount from net sale proceeds to
    obtain realized P&L.
    """

    contract: Contract
    entered_at: datetime
    entry_cost: Decimal


def replay(snapshots: list[Snapshot], close_at: datetime, settings: Settings) -> dict:
    """Apply the long-call strategy to synthetic snapshots available by a planned close.

    Sort snapshots by retrieved_at and keep frames at or before close_at. The retained set
    must be nonempty, synthetic and have distinct decision times. settings supplies the
    pricing assumptions, quote-quality limits, capital, costs and holding period. At most
    one entry or position can be outstanding.

    A signal may fill on a subsequent eligible option quote with a timestamp after the
    decision. A buy must still be affordable and its planned exit must precede expiry. A
    filled position exits on a qualifying bid after the holding period or at the scheduled
    closing capture.

    Return a dictionary of chronological events, cash, realized P&L, open-position status
    and any unfilled signal. An open position needs an eligible closing mark to report
    equity and unrealized P&L. Without one those amounts are None. Monetary balances are
    decimal strings for serialization.
    """
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
        """Append one event with the decision time and the option quote's own timestamp.

        action identifies a signal, buy, sell or cancellation. frame ties the event to its
        capture and quote supplies the contract symbol and quote time. Copy the current
        cash balance when recording, so fill events show cash after the transaction.
        Additional fields carry event-specific prices, fees, reasons or P&L.
        """
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
