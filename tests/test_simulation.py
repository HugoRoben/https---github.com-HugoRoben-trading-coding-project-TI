"""Verify synthetic replay chronology, eligibility, cash accounting and trade reporting.

The tests modify individual features of the bundled synthetic session, including available
capital, quote timestamps, multiplier and exit timing. Expected fills and cash changes are
checked in decimal USD so signals, entries, realized results and open positions can be
distinguished.
"""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest

from modules.models.simulation import replay
from modules.storage_reporting.reporting import closed_trade_rows
from options_lab.config import load_settings
from options_lab.fixtures import fixture_inputs


class ReplayTests(unittest.TestCase):
    """Exercise one-contract trading behavior with controlled changes to the demo session.

    Each case starts with the same fixture and default settings. Selected changes force
    entry cancellation, early exit, missing closing marks or different contract economics.
    Assertions address both the chronological event history and the resulting portfolio
    summary.
    """

    def setUp(self):
        """Load fresh synthetic observations and default settings for one replay case.

        Keep the planned session close and the list of Snapshot objects from
        fixture_inputs. Discard the input hashes because these tests call replay directly
        in memory. Each case can reorder or replace its frames without changing the bundled
        fixture.
        """
        self.close, inputs = fixture_inputs()
        self.frames = [frame for frame, _ in inputs]
        self.settings = load_settings()

    def run_replay(self, **changes):
        """Run the fixture replay with optional overrides to the simulation settings.

        changes names fields of the Simulation dataclass such as initial_cash_usd or
        hold_minutes. Make a replaced copy of the rule set and enclosing settings, run
        against the test's current frames and close, and return the complete replay result
        for assertions.
        """
        rules = replace(self.settings.simulation, **changes)
        return replay(self.frames, self.close, replace(self.settings, simulation=rules))

    def test_roundtrip_matches_hand_calculation_and_chronology(self):
        """Check a complete trade against hand-calculated cash movements and P&L.

        Reverse the input frames to exercise chronological sorting. Require distinct
        signal, buy and sell captures, then compare both signed cash changes with slipped
        per-share prices times the multiplier and the fees. Check realized P&L, final
        equity and a flat closing position.
        """
        self.frames.reverse()
        result = self.run_replay()
        signal, buy, sell = result["events"]
        self.assertEqual(
            [e["capture_id"] for e in (signal, buy, sell)], ["demo-01", "demo-02", "demo-04"]
        )
        self.assertEqual(
            Decimal(buy["cash_change_usd"]), -(Decimal("1.61") * 100 + Decimal("0.65"))
        )
        self.assertEqual(Decimal(sell["cash_change_usd"]), Decimal("2.09") * 100 - Decimal("0.65"))
        self.assertEqual(Decimal(result["realized_pnl_usd"]), Decimal("46.70"))
        self.assertEqual(Decimal(result["equity_usd"]), Decimal("1046.70"))
        self.assertEqual(result["position_status"], "flat")

    def test_capital_rechecked_at_fill(self):
        """Exercise affordability both at signal selection and again on the later fill.

        A starting balance of USD 155 admits the initial signal but cannot cover the next
        eligible ask and fee, so the ledger must show a cancellation. A USD 50 starting
        balance must produce no signal at all.
        """
        events = self.run_replay(initial_cash_usd=155)["events"]
        self.assertEqual([e["action"] for e in events], ["signal", "cancel"])
        self.assertEqual(events[-1]["reason"], "insufficient_cash_at_fill")
        self.assertEqual(self.run_replay(initial_cash_usd=50)["events"], [])

    def test_trade_report_pairs_fills_and_omits_unclosed_positions(self):
        """Check completed round trips in a ledger containing non-fill events and an open buy.

        Combine a real fixture round trip with an invented losing trade and a final
        unmatched buy. Verify summed fees, net P&L and the second trade's entry metadata. A
        signal and a single buy on their own must produce no completed-trade row.
        """
        signal, buy, sell = self.run_replay()["events"]
        later_buy = {**buy, "at": "2025-02-04T15:15:00Z", "price_per_share": "2.30"}
        later_sell = {**sell, "at": "2025-02-04T15:45:00Z", "trade_pnl_usd": "-22.30"}
        events = [signal, {"action": "cancel"}, buy, sell, later_buy, later_sell, later_buy]
        first, second = closed_trade_rows(events)
        self.assertEqual(first["fees_usd"], Decimal("1.30"))
        self.assertEqual(first["net_pnl_usd"], Decimal("46.70"))
        self.assertEqual(second["entry_utc"], later_buy["at"])
        self.assertEqual(second["buy_per_share"], Decimal("2.30"))
        self.assertEqual(second["net_pnl_usd"], Decimal("-22.30"))
        self.assertEqual(list(closed_trade_rows([signal, buy])), [])

    def test_actual_multiplier(self):
        """Check that changing the observed contract multiplier changes realized P&L.

        Replace every fixture contract's multiplier with 10 while keeping the same quotes
        and fees. The resulting net realized USD 3.50 exercises the conversion from
        per-share price to contract cash and catches an implicit assumption of 100 shares
        per contract.
        """
        self.frames = [
            replace(
                s,
                quotes=tuple(
                    replace(q, contract=replace(q.contract, multiplier=10)) for q in s.quotes
                ),
            )
            for s in self.frames
        ]
        self.assertEqual(Decimal(self.run_replay()["realized_pnl_usd"]), Decimal("3.50"))

    def test_no_fill_on_recaptured_pre_signal_quote_even_if_fresh(self):
        """Reject a new capture whose option quote predates the pending signal.

        Insert a later retrieval of the original quote between the signal and the next
        genuine update. Its quote age still passes the usual freshness checks. Require the
        buy to use the subsequent frame with an actually newer option timestamp.
        """
        first, second = self.frames[:2]
        same = replace(
            first, capture_id="recapture", retrieved_at=first.retrieved_at + timedelta(seconds=2)
        )
        self.frames.insert(1, same)
        buy = next(e for e in self.run_replay()["events"] if e["action"] == "buy")
        self.assertEqual(buy["capture_id"], second.capture_id)

    def test_scheduled_close_and_missing_exit(self):
        """Exercise an early scheduled exit and unavailable closing valuations.

        Extend the holding period beyond the planned close and check that a usable closing
        bid yields a scheduled-close sale. Remove that bid and then the closing frame
        itself. The remaining open position must be unpriced, with unavailable equity and
        unrealized P&L in the missing-bid case.
        """
        result = self.run_replay(hold_minutes=90)
        self.assertEqual(result["events"][-1]["reason"], "scheduled_close")
        last = self.frames[-1]
        self.frames[-1] = replace(last, quotes=(replace(last.quotes[0], bid=None), last.quotes[1]))
        open_result = self.run_replay(hold_minutes=90)
        self.assertEqual(open_result["position_status"], "open_unpriced")
        self.assertIsNone(open_result["equity_usd"])
        self.assertIsNone(open_result["unrealized_pnl_usd"])
        self.assertEqual(open_result["closed_trades"], 0)
        self.frames.pop()
        self.assertEqual(self.run_replay(hold_minutes=90)["position_status"], "open_unpriced")

    def test_no_entry_with_planned_exit_at_or_after_expiry(self):
        """Reject a pending entry whose earliest planned exit reaches contract expiry.

        Move expiry close to the signal and raise spot so that the call still satisfies the
        entry-price rule. Require an expiry-related cancellation and verify the ledger
        contains no buy. This isolates the exit timing constraint from affordability or
        model thresholds.
        """
        expiry = self.frames[2].retrieved_at
        self.frames = [
            replace(
                s,
                quotes=tuple(
                    replace(q, contract=replace(q.contract, expiry_at=expiry)) for q in s.quotes
                ),
            )
            for s in self.frames
        ]
        # Near-expiry value still exceeds the cheap ask, so the rejection tests exit timing.
        self.frames = [replace(s, spot=110) for s in self.frames]
        result = self.run_replay()
        self.assertIn("planned_exit_reaches_expiry", [e["reason"] for e in result["events"]])
        self.assertFalse(any(e["action"] == "buy" for e in result["events"]))
