"""Exercise the U.S. collector, archive, SQLite store and reports through the CLI.

Provider replies and account settings are manufactured. Temporary paths isolate output and
allow the tests to inspect raw JSON, persisted observations and report contents after
successful collection, interrupts and failed pagination. Other cases verify deterministic
fixture replay without any provider access.
"""

from contextlib import redirect_stderr, redirect_stdout
import csv
from datetime import UTC, date, datetime
import io
import json
import os
from pathlib import Path
from socket import gaierror
from ssl import SSLCertVerificationError
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit

from modules.alpaca.client import CONTRACTS_URL, AlpacaError, contract_catalog_url
from modules.alpaca.normalization import normalize
from modules.alpaca.retrieval import fetch_capture, select_universe
from modules.storage_reporting.database import database
from options_lab.cli import main
from options_lab.config import load_settings
from options_lab.domain import iso
from options_lab.validation import quality_flags


class PipelineTests(unittest.TestCase):
    """Cover the external boundaries of the local Alpaca and synthetic workflows.

    Tests drive normal CLI parsing, capture its diagnostics and examine the files a user
    would receive. Controlled responses make account routing, fixed-universe selection,
    reimport and failure behavior reproducible without an Alpaca account.
    """

    def setUp(self):
        """Isolate the filesystem, credentials and console for each pipeline test.

        Create temporary data and report paths, capture both output streams and install
        test-only environment variables under a restoring patch. Set a UTC quote time and
        start a request log so the test can inspect exactly which hosts, feeds and pages
        the collector used.
        """
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.data = self.root / "data"
        self.reports = self.root / "reports"
        self.output = io.StringIO()
        self.enterContext(redirect_stdout(self.output))
        self.enterContext(redirect_stderr(self.output))
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "APCA_API_KEY_ID": "PK-test-only",
                    "APCA_API_SECRET_KEY": "test-only-secret",
                    "APCA_API_BASE_URL": "",
                },
            )
        )
        self.stamp = iso(datetime.now(UTC))
        self.queries = []

    def cli(self, *command):
        """Call the application's main function with the test's data and report roots.

        command contains the subcommand and any subcommand arguments as individual tokens.
        Return the integer command status. Printed output is available through the streams
        installed in setUp, allowing the caller to assert on both the status and the
        user-facing diagnostic.
        """
        return main(["--data-dir", str(self.data), "--report-dir", str(self.reports), *command])

    def mock_get(self, url, params):
        """Respond to the U.S. adapter's endpoint and parameter pair with fixture JSON.

        Record each request, return an AAPL stock quote, and split the contract catalog
        over two pages with a call and a put. The option feed returns only the call so
        tests can follow a missing put observation into storage and valuation. Reject
        unexpected endpoints and check the requested feed and symbols.
        """
        self.queries.append((url, params.copy()))
        if url.endswith("/stocks/AAPL/quotes/latest"):
            return {"symbol": "AAPL", "quote": {"bp": 99.9, "ap": 100.1, "t": self.stamp}}
        if url in (CONTRACTS_URL, "https://api.alpaca.markets/v2/options/contracts"):
            page_two = "page_token" in params
            fields = dict(
                underlying_symbol="AAPL",
                root_symbol="AAPL",
                expiration_date="2099-02-20",
                strike_price="100",
                multiplier="100",
                size="100",
                style="american",
            )
            contract = dict(
                fields,
                symbol="TEST-P" if page_two else "TEST-C",
                type="put" if page_two else "call",
            )
            return {"option_contracts": [contract], "next_page_token": None if page_two else "two"}
        if url.endswith("/options/quotes/latest"):
            self.assertEqual(params, {"feed": "indicative", "symbols": "TEST-C,TEST-P"})
            return {"quotes": {"TEST-C": {"bp": 1.50, "ap": 1.65, "t": self.stamp}}}
        self.fail(f"unexpected API endpoint: {url}")

    def test_market_quotes_and_catalog_routing_through_the_collector(self):
        """Verify quote and metadata routing across key prefixes and account overrides.

        Drive a collection through the real HTTP request builder, replacing only urlopen.
        Assert that stock and option quotes use the data host and both catalog pages use
        the expected account host. Cover explicit paper and live overrides and reject an
        unsupported base URL.
        """

        def respond(request, *, timeout):
            """Adapt the test's JSON responder to the urlopen request interface.

            Check that request uses GET, split its URL and decode the query for mock_get.
            Serialize the fixture reply into a byte stream so the production JSON decoder
            reads it normally. The keyword-only timeout matches the network call's
            signature.
            """
            self.assertEqual(request.get_method(), "GET")
            parsed = urlsplit(request.full_url)
            url = parsed._replace(query="").geturl()
            reply = self.mock_get(url, dict(parse_qsl(parsed.query)))
            return io.BytesIO(json.dumps(reply).encode())

        paper = "https://paper-api.alpaca.markets/v2/options/contracts"
        live = "https://api.alpaca.markets/v2/options/contracts"
        for key, override, catalog in [
            ("PK-test-only", "", paper),
            ("AK-test-only", "", live),
            ("AK-test-only", "https://paper-api.alpaca.markets/v2/", paper),
            ("other-format", "https://api.alpaca.markets", live),
        ]:
            with (
                self.subTest(key=key, override=override),
                patch.dict(os.environ, {"APCA_API_KEY_ID": key, "APCA_API_BASE_URL": override}),
                patch("modules.alpaca.client.urlopen", side_effect=respond),
            ):
                self.queries.clear()
                self.assertEqual(self.cli("collect", "--expiry", "2099-02-20"), 0)
                self.assertEqual(
                    [url for url, _ in self.queries],
                    [
                        "https://data.alpaca.markets/v2/stocks/AAPL/quotes/latest",
                        catalog,
                        catalog,
                        "https://data.alpaca.markets/v1beta1/options/quotes/latest",
                    ],
                )
        with patch.dict(os.environ, {"APCA_API_BASE_URL": "https://example.org"}):
            with self.assertRaisesRegex(AlpacaError, "APCA_API_BASE_URL"):
                contract_catalog_url()

    def test_request_errors_identify_endpoint_and_cause_without_disclosing_credentials(self):
        """Verify that collection failures produce useful diagnostics without exposing keys.

        Simulate DNS, certificate and timeout errors and HTTP authorization failures. For
        each case require a failing CLI status, the relevant endpoint and the expected
        cause in the captured output. Check that neither test credential appears, even when
        the simulated HTTP error contains one.
        """
        url = "https://data.alpaca.markets/v2/stocks/AAPL/quotes/latest"
        for error, expected in [
            (URLError(gaierror(8, "unresolved")), "DNS lookup failed"),
            (
                URLError(SSLCertVerificationError("untrusted")),
                "TLS certificate verification failed",
            ),
            (URLError(TimeoutError()), "connection timed out"),
            (HTTPError(url, 401, "test-only-secret", {}, None), "HTTP 401"),
            (HTTPError(url, 403, "test-only-secret", {}, None), "HTTP 403"),
        ]:
            with (
                self.subTest(expected=expected),
                patch("modules.alpaca.client.urlopen", side_effect=error),
            ):
                self.output.seek(0)
                self.output.truncate()
                self.assertEqual(self.cli("collect"), 1)
                diagnostic = self.output.getvalue()
                self.assertIn(url, diagnostic)
                self.assertIn(expected, diagnostic)
                self.assertNotIn("PK-test-only", diagnostic)
                self.assertNotIn("test-only-secret", diagnostic)

    def test_two_intervals_fixed_universe_raw_reimport_and_pinned_report(self):
        """Follow a two-capture session from the initial catalog selection to a pinned report.

        Check the pause, catalog request count and two raw files. Reimport one archive and
        assert stable database counts. Value its named capture and verify provenance, the
        call's passing quality status and the missing put quote. The put can still get a
        model value while its ask comparison stays empty.
        """
        with (
            patch("modules.alpaca.retrieval.authenticated_get", return_value=self.mock_get),
            patch("modules.alpaca.retrieval.sleep") as pause,
        ):
            self.assertEqual(
                self.cli(
                    "collect", "--count", "2", "--interval-seconds", "17", "--expiry", "2099-02-20"
                ),
                0,
            )
        pause.assert_called_once_with(17)
        self.assertEqual(sum(url == CONTRACTS_URL for url, _ in self.queries), 2)
        raw_paths = sorted((self.data / "raw").glob("*.json"))
        self.assertEqual(len(raw_paths), 2)
        raw = json.loads(raw_paths[0].read_text())
        self.assertEqual(self.cli("import-capture", str(raw_paths[0])), 0)
        with database(self.data / "options.sqlite3") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT count(*) FROM quotes").fetchone()[0], 4)
        self.assertEqual(self.cli("value", "--capture", raw["capture_id"]), 0)
        directory = next(self.reports.iterdir())
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["inputs"][0]["capture_id"], raw["capture_id"])
        with (directory / "valuations.csv").open() as stream:
            call, put = csv.DictReader(stream)
        self.assertEqual(call["quality_flags"], "ok")
        self.assertIn("missing_bid_ask", put["quality_flags"])
        self.assertTrue(put["model_per_share"])
        self.assertEqual(put["model_minus_ask"], "")

    def test_interrupted_session_keeps_its_completed_capture(self):
        """Interrupt collection during the pause before the second requested capture.

        Require the CLI's interrupt exit status and reopen the database to verify that the
        first capture and both of its quote rows were committed. The raw directory must
        contain exactly the archive for that completed capture.
        """
        with (
            patch("modules.alpaca.retrieval.authenticated_get", return_value=self.mock_get),
            patch("modules.alpaca.retrieval.sleep", side_effect=KeyboardInterrupt),
        ):
            self.assertEqual(self.cli("collect", "--count", "2"), 130)

        with database(self.data / "options.sqlite3") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 2)
        self.assertEqual(len(list((self.data / "raw").glob("*.json"))), 1)

    def test_missing_multiplier_does_not_use_deliverable_size(self):
        """Keep a missing premium multiplier visible when a size field is available.

        Remove multiplier from a collected contract while leaving its deliverable size in
        the reference response. Normalize the capture and require an unknown multiplier and
        its quality flag. Also check that the expiry cutoff inferred from a date-only
        contract is marked as assumed.
        """
        config = load_settings()
        raw = fetch_capture(self.mock_get, config.collection, date(2099, 2, 20))
        del raw["universe"]["pages"][0]["option_contracts"][0]["multiplier"]
        frame = normalize(raw)
        self.assertIsNone(frame.quotes[0].contract.multiplier)
        self.assertIn(
            "unknown_or_invalid_multiplier", quality_flags(frame, frame.quotes[0], config.quality)
        )
        self.assertTrue(frame.quotes[0].contract.expiry_time_assumed)

    def test_failed_pagination_does_not_publish_a_batch(self):
        """Check that an interrupted catalog search leaves no partial capture.

        Cause the second reference page to fail, then run collection through the CLI.
        Require a failure status, an empty snapshots table and no raw capture directory.
        This protects the invariant that the whole universe is selected before a capture
        can be archived.
        """

        def broken(url, params):
            """Raise a deterministic failure on the second page of the contract catalog.

            Forward the original url and params to mock_get for all earlier requests.
            Failing only when the next-page token appears tests the boundary between
            partial discovery and a complete stock-and-option capture.
            """
            if url == CONTRACTS_URL and "page_token" in params:
                raise ValueError("second page failed")
            return self.mock_get(url, params)

        with patch("modules.alpaca.retrieval.authenticated_get", return_value=broken):
            self.assertEqual(self.cli("collect", "--expiry", "2099-02-20"), 1)
        with database(self.data / "options.sqlite3") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 0)
        self.assertFalse((self.data / "raw").exists())

    def test_default_search_window_and_nearest_strikes(self):
        """Verify date bounds and nearest-strike selection from a fixed New York date.

        Offer two expiries and five strikes around a stock midpoint of 100. Check the
        inclusive date range sent to the provider and the three selected strikes at the
        earlier expiry. Providing contracts out of expiry order tests the selector's own
        ranking.
        """
        config = load_settings().collection
        books = [
            dict(
                underlying_symbol="AAPL",
                root_symbol="AAPL",
                expiration_date=end,
                symbol=f"{end}-C{k}",
                type="call",
                strike_price=str(k),
            )
            for end in ("2025-04-25", "2025-04-18")
            for k in (97, 98, 100, 102, 104)
        ]

        def get(url, params):
            """Check the outgoing expiry bounds and return an unsorted contract catalog.

            Accept the collector's URL and query arguments, assert the expected April
            bounds and return all test contracts on a single page. This isolates local
            expiry and strike ranking from the behavior of a live catalog service.
            """
            self.assertEqual(
                (params["expiration_date_gte"], params["expiration_date_lte"]),
                ("2025-04-15", "2025-04-29"),
            )
            return {"option_contracts": books, "next_page_token": None}

        universe = select_universe(get, config, 100, datetime(2025, 4, 1, 16, tzinfo=UTC), None)
        self.assertEqual(
            set(universe["symbols"]), {"2025-04-18-C98", "2025-04-18-C100", "2025-04-18-C102"}
        )

    def test_demo_outputs_are_reproducible_and_market_database_is_empty(self):
        """Verify fixture initialization, byte-reproducible reports and market-data isolation.

        A replay before demo loading must explain the missing fixture capture. Repeated
        demos and replays then resolve to a single output directory. Replaying to a
        separate report root must reproduce every file byte-for-byte. Finally check that
        the market database still has zero snapshots.
        """
        self.assertEqual(self.cli("init-db"), 0)
        self.assertEqual(self.cli("replay"), 1)
        self.assertIn("run demo", self.output.getvalue())
        self.assertEqual(self.cli("demo"), 0)
        directory = next(self.reports.iterdir())
        content = {p.name: p.read_bytes() for p in directory.iterdir()}
        self.assertEqual(self.cli("demo"), 0)
        self.assertEqual(self.cli("replay"), 0)
        self.assertEqual(list(self.reports.iterdir()), [directory])
        other = self.root / "repeat"
        self.assertEqual(
            main(["--data-dir", str(self.data), "--report-dir", str(other), "replay"]), 0
        )
        self.assertEqual(
            {p.name: p.read_bytes() for p in (other / directory.name).iterdir()}, content
        )
        with database(self.data / "options.sqlite3") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM snapshots").fetchone()[0], 0)
