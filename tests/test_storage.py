from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from modules.storage_reporting.database import database, read_snapshot, save_snapshot
from options_lab.config import load_settings
from options_lab.domain import parse_time
from options_lab.fixtures import fixture_inputs
from options_lab.validation import quality_flags


class StorageTests(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(TemporaryDirectory())
        self.path = Path(root) / "options.sqlite3"
        self.db = self.enterContext(database(self.path))
        self.frame, self.sha = fixture_inputs()[1][0]
        self.quality = load_settings().quality

    def save(self, frame, sha):
        return save_snapshot(self.db, frame, "fixture.json", sha, self.quality)

    def test_roundtrip_reimport_and_new_retrieval_of_same_quote(self):
        self.assertTrue(self.save(self.frame, self.sha))
        with database(self.path) as reopened:
            self.assertEqual(read_snapshot(reopened, self.frame.capture_id), self.frame)
            self.assertFalse(
                save_snapshot(reopened, self.frame, "copy.json", self.sha, self.quality)
            )
        with self.assertRaisesRegex(ValueError, "different content"):
            self.save(self.frame, "changed")
        again = replace(
            self.frame,
            capture_id="new",
            retrieved_at=self.frame.retrieved_at + timedelta(seconds=2),
        )
        self.assertTrue(self.save(again, "new hash"))
        self.assertEqual(self.db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM contracts").fetchone()[0], 2)
        self.assertEqual(self.db.execute("SELECT count(*) FROM quotes").fetchone()[0], 4)

    def test_partial_failure_rolls_back_snapshot_and_terms(self):
        good, bad = self.frame.quotes
        bad = replace(bad, contract=replace(bad.contract, strike=-1))
        with self.assertRaises(sqlite3.IntegrityError):
            self.save(replace(self.frame, quotes=(good, bad)), "invalid")
        for name in ("snapshots", "contracts", "quotes"):
            self.assertEqual(self.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0], 0)

    def test_new_terms_preserve_original_snapshot(self):
        self.save(self.frame, self.sha)
        q = self.frame.quotes[0]
        changed = replace(
            q, contract=replace(q.contract, multiplier=None, exercise_style="unknown")
        )
        later = replace(self.frame, capture_id="later", quotes=(changed,))
        self.save(later, "other")
        self.assertEqual(read_snapshot(self.db, self.frame.capture_id), self.frame)
        self.assertEqual(read_snapshot(self.db, "later").quotes, (changed,))

    def test_quality_flags_preserve_separate_clocks_and_metadata(self):
        frame = self.frame
        q = frame.quotes[0]
        stale = replace(q, quote_at=frame.retrieved_at - timedelta(seconds=350), bid=2, ask=1)
        self.assertEqual(
            set(quality_flags(frame, stale, self.quality)),
            {"crossed_quote", "stale_option", "unsynchronized"},
        )
        future = replace(frame, underlying_at=frame.retrieved_at + timedelta(seconds=1), spot=None)
        missing = replace(
            q,
            quote_at=None,
            bid=None,
            contract=replace(q.contract, multiplier=None, exercise_style="unknown"),
        )
        self.assertEqual(
            set(quality_flags(future, missing, self.quality)),
            {
                "missing_bid_ask",
                "missing_or_invalid_spot",
                "missing_option_time",
                "future_underlying",
                "unknown_or_invalid_multiplier",
                "unknown_exercise_style",
            },
        )
        with self.assertRaises(ValueError):
            parse_time("2025-01-01T12:00:00")
