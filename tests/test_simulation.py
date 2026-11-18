from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import unittest

from options_lab.config import load_settings
from options_lab.fixtures import fixture_inputs
from options_lab.reporting import closed_trade_rows
from options_lab.simulation import replay


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.close, inputs = fixture_inputs()
        self.frames = [frame for frame, _ in inputs]
        self.settings = load_settings()

    def run_replay(self, **changes):
        rules = replace(self.settings.simulation, **changes)
        return replay(self.frames, self.close, replace(self.settings, simulation=rules))

    def test_roundtrip_matches_hand_calculation_and_chronology(self):
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
        events = self.run_replay(initial_cash_usd=155)["events"]
        self.assertEqual([e["action"] for e in events], ["signal", "cancel"])
        self.assertEqual(events[-1]["reason"], "insufficient_cash_at_fill")
        self.assertEqual(self.run_replay(initial_cash_usd=50)["events"], [])

    def test_trade_report_pairs_fills_and_omits_unclosed_positions(self):
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
        first, second = self.frames[:2]
        same = replace(
            first, capture_id="recapture", retrieved_at=first.retrieved_at + timedelta(seconds=2)
        )
        self.frames.insert(1, same)
        buy = next(e for e in self.run_replay()["events"] if e["action"] == "buy")
        self.assertEqual(buy["capture_id"], second.capture_id)

    def test_scheduled_close_and_missing_exit(self):
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
