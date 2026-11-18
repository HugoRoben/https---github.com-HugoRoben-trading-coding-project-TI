"""Invented Amsterdam reports and reference records exercise the public-data adapter offline."""

from contextlib import redirect_stdout
import csv
from datetime import UTC, date, datetime
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from modules.euronext.observations import trade_rows
from modules.euronext.retrieval import TRADE_FIELDS, fetch_trades
from modules.storage_reporting.amsterdam import amsterdam_database, recent_windows
from options_lab.cli import parser, run
from options_lab.config import ROOT, load_settings

PROFILE = ROOT / "config/asml_amsterdam.toml"
NOW = datetime(2026, 6, 10, 10, tzinfo=UTC)
SHARE = "NL0010273215"
CALL, PUT = "TEST-CALL", "TEST-PUT"


def terms(isin, side, option_class="ASL"):
    return dict(
        isin=isin,
        mic="XEUE",
        gnr_short_name=f"ENXT NL/O 20260619 {side} A {option_class} 100",
        gnr_notional_curr_code="EUR",
        drv_underlng_isin=SHARE,
        drv_expiry_date="2026-06-19T00:00:00Z",
        mrkt_trdng_trmination_date="2026-06-19T15:30:00Z",
        drv_sp_prc_value_amount="100",
        drv_sp_prc_value_curr_code="EUR",
        drv_price_multiplier="100",
        drv_option_type="CALL" if side == "C" else "PUTO",
        drv_option_exercise_style="AMER",
    )


def execution(isin, tx, at, price, *, published=None, flag="-"):
    return dict(
        TradingDateTime=f"2026-06-10T{at}Z",
        PublicationDateTime=f"2026-06-10T{published or at}Z",
        MifidInstrumentID=isin,
        MifidPrice=str(price),
        MifidQuantity="2",
        MifidPriceNotation="MONE",
        MifidCurrency="EUR",
        MmtModificationIndicator=flag,
        Venue="XAMS" if isin == SHARE else "XEUE",
        TradeUniqueIdentifier=tx,
    )


def zipped(filename, rows):
    csv_text = StringIO()
    csv_text.write("(c) Euronext test data\n")
    writer = csv.DictWriter(csv_text, fieldnames=sorted(TRADE_FIELDS))
    writer.writeheader()
    writer.writerows(rows)
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr(filename, csv_text.getvalue())
    return data.getvalue()


class AmsterdamTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings(PROFILE)
        self.options = [
            execution(CALL, "opt", "09:00:00", 2.20),
            execution(CALL, "opt", "09:00:00", 2.20),
            execution(PUT, "old", "09:20:00", 2.0),
            execution(CALL, "early", "07:20:00", 2.1),
            execution(CALL, "canceled", "09:03:00", 2.3),
            execution(CALL, "canceled", "09:03:00", 2.3, published="09:04:00", flag="CANC"),
            execution("WRONG-CLASS", "other", "09:01:00", 4),
        ]
        self.stock = [
            execution(SHARE, "good", "08:59:57", 100),
            execution(SHARE, "late-publication", "08:59:59", 110, published="09:00:05"),
            execution(SHARE, "future", "09:01:00", 120),
        ]
        self.pages = []

    def get(self, url):
        if urlsplit(url).hostname == "registers.esma.europa.eu":
            params = parse_qs(urlsplit(url).query)
            offset = int(params["start"][0])
            self.pages.append(offset)
            self.assertIn("drv_underlng_isin:" + SHARE, params["q"][0])
            docs = (
                [terms(CALL, "C")]
                if offset == 0
                else [terms(PUT, "P"), terms("WRONG-CLASS", "C", "AS9")]
            )
            return json.dumps({"response": {"start": offset, "numFound": 3, "docs": docs}}).encode()
        if url.endswith("/EQUITIES/LAST_HOUR/AMS"):
            return zipped("Trades_Equities.csv", self.stock)
        self.assertTrue(url.endswith("/EQUITY_INDEX_DERIVATIVES/LAST_HOUR/AMS"))
        return zipped("Trades_EquityIndexDerivatives.csv", self.options)

    def capture(self):
        return fetch_trades(self.settings.euronext, get=self.get, now=lambda: NOW)

    def test_native_contracts_publication_times_and_cancellation(self):
        raw = self.capture()
        self.assertEqual(self.pages, [0, 1])
        self.assertEqual((raw["listed_contracts"], set(raw["contracts"])), (2, {CALL, PUT}))
        rows = {r["trade_id"]: r for r in trade_rows(raw, self.settings.euronext)}
        self.assertEqual(set(rows), {"opt", "old", "early"})
        self.assertEqual(rows["opt"]["stock_trade_id"], "good")
        self.assertEqual(rows["opt"]["stock_eur"], 100)
        self.assertEqual(rows["opt"]["expiry_utc"], "2026-06-19T15:30:00.000000Z")
        self.assertIsNone(rows["early"]["stock_eur"])

    def test_cli_collection_raw_reimport_and_pinned_eur_report(self):
        with TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            root = Path(tmp)

            def command(*cmd):
                args = parser().parse_args(
                    [
                        "--data-dir",
                        str(root / "data"),
                        "--report-dir",
                        str(root / "reports"),
                        "--config",
                        str(PROFILE),
                        *cmd,
                    ]
                )
                return run(args)

            raw = self.capture()
            with patch("options_lab.cli.fetch_trades", return_value=raw):
                command("collect")
            archive = next((root / "data/raw/euronext").glob("*.json"))
            command("import-capture", str(archive))
            with amsterdam_database(root / "data") as db:
                self.assertEqual(len(recent_windows(db, self.settings, 5)), 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM option_trades").fetchone()[0], 3)
            target = command("value", "--capture", archive.stem)
            with (target / "trades.csv").open() as f:
                rows = {r["trade_id"]: r for r in csv.DictReader(f)}
            self.assertEqual(rows["opt"]["valuation_status"], "ok")
            self.assertTrue(float(rows["opt"]["model_eur"]) > 0)
            self.assertEqual(
                (rows["old"]["model_eur"], rows["old"]["valuation_status"]),
                ("", "stale share trade"),
            )
            self.assertEqual(rows["early"]["valuation_status"], "missing earlier share trade")
            self.assertEqual(json.loads((target / "manifest.json").read_text())["currency"], "EUR")
            self.assertFalse((root / "data/options.sqlite3").exists())
            self.assertEqual(command("value"), target)

    def test_empty_tape_and_exact_expiry(self):
        self.options = []
        raw = self.capture()
        self.assertEqual(trade_rows(raw, self.settings.euronext), [])
        with self.assertRaisesRegex(ValueError, "no ASL options"):
            fetch_trades(self.settings.euronext, date(2026, 6, 22), get=self.get, now=lambda: NOW)

    def test_wrong_provider_or_malformed_download_is_rejected(self):
        raw = self.capture()
        raw["share_isin"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "does not match"):
            trade_rows(raw, self.settings.euronext)
        with self.assertRaisesRegex(ValueError, "ZIP"):
            fetch_trades(
                self.settings.euronext,
                get=lambda u: self.get(u) if "esma.europa.eu" in u else b"<html>error</html>",
                now=lambda: NOW,
            )
