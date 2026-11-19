"""Verify SQLite capture identity, versioned contract terms and quote-quality flags.

Work with a temporary database and the bundled synthetic frame to check atomic saves and
exact reconstruction. Cases distinguish a repeated import from a genuinely later retrieval
of the same quote. Other checks exercise metadata corrections and the separate option,
stock and availability clocks.
"""

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
    """Check persistence and validation against an isolated quote snapshot database.

    The cases drive the same database functions used by collection. A fixture frame
    supplies known contract terms and quote timestamps, so assertions can locate a change
    in capture identity, terms history, transaction behavior or quality policy.
    """

    def setUp(self):
        """Initialize a temporary SQLite store and select a known fixture snapshot.

        Enter both the temporary directory and the database connection through the test
        cleanup stack. Keep the first synthetic snapshot and its input digest, together
        with the default quality thresholds, so every test uses comparable source data.
        """
        root = self.enterContext(TemporaryDirectory())
        self.path = Path(root) / "options.sqlite3"
        self.db = self.enterContext(database(self.path))
        self.frame, self.sha = fixture_inputs()[1][0]
        self.quality = load_settings().quality

    def save(self, frame, sha):
        """Write a frame with the given input hash into this test's open database.

        Use a fixed fixture reference and the default quality thresholds. Return
        save_snapshot's insertion flag so callers can distinguish a new capture from an
        identical reimport. Integrity and capture-identity errors are allowed to reach the
        invoking test.
        """
        return save_snapshot(self.db, frame, "fixture.json", sha, self.quality)

    def test_roundtrip_reimport_and_new_retrieval_of_same_quote(self):
        """Check reconstruction and distinguish raw reimport from a new capture.

        Save a fixture, reopen the database and require equality with the in-memory record.
        Reimporting the same ID and hash is idempotent even with a different raw path. A
        conflicting hash is rejected. Saving a later retrieval with a new ID then adds
        quote rows while sharing the original contract terms.
        """
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
        """Force a late insertion failure to verify that a capture is atomic.

        Keep the first quote valid and give the second contract an invalid strike,
        triggering the SQLite constraint. After the error, inspect snapshots, contracts and
        quotes. All three tables must be empty, including the terms and quote inserted
        before the failure.
        """
        good, bad = self.frame.quotes
        bad = replace(bad, contract=replace(bad.contract, strike=-1))
        with self.assertRaises(sqlite3.IntegrityError):
            self.save(replace(self.frame, quotes=(good, bad)), "invalid")
        for name in ("snapshots", "contracts", "quotes"):
            self.assertEqual(self.db.execute(f"SELECT count(*) FROM {name}").fetchone()[0], 0)

    def test_new_terms_preserve_original_snapshot(self):
        """Store revised contract metadata while retaining the original observation.

        After saving the fixture, insert a new capture whose same-symbol option has an
        unknown multiplier and exercise style. Reading both capture IDs must reproduce
        their respective original terms. This guards the versioned relationship between a
        quote and its contract definition.
        """
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
        """Check independent diagnostics for quote prices, clocks and contract metadata.

        Build a crossed, stale option quote and require the exact flags including clock
        skew. Then combine a missing option timestamp and sides with a future stock
        observation and unknown terms, and check the full resulting flag set. Also require
        the timestamp parser to reject a timezone-naive input.
        """
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
