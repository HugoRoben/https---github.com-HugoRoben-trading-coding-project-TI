"""Run the local collection, valuation and synthetic replay commands.

The parser defines one set of paths and subcommands for the terminal and notebooks. The
selected TOML profile routes work to Alpaca USD snapshots or Euronext Amsterdam EUR trade
windows. Each completed collection can be archived and imported separately. Valuation
commands return a report path for callers that want to inspect the outputs.
"""

import argparse
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
from time import sleep

from modules.alpaca.normalization import normalize
from modules.alpaca.retrieval import iter_captures
from modules.euronext.retrieval import fetch_trades
from modules.models.simulation import replay
from modules.storage_reporting.amsterdam import (
    amsterdam_database,
    read_report,
    save_window,
    write_trade_report,
)
from modules.storage_reporting.database import (
    database,
    latest_market_id,
    provenance,
    read_snapshot,
    save_snapshot,
)
from modules.storage_reporting.raw_captures import archive
from modules.storage_reporting.reporting import write_run

from .config import ROOT, AmsterdamSettings, load_settings
from .domain import digest
from .fixtures import FIXTURE, fixture_inputs
from .validation import quality_flags


def save_market(db, raw, directory, quality):
    """Normalize, archive and store one raw Alpaca capture and print an ingest summary.

    db is the open USD market database. directory is its data root, used for both the raw
    archive and its relative database reference. quality sets the flags recorded for each
    quote and the count shown in the progress message. An existing capture with matching
    input is reported as already present.

    The raw archive is written before the SQLite transaction, so it can be reimported after
    a database failure. This helper returns None. Malformed captures, conflicting IDs and
    storage errors propagate to the command boundary.
    """
    snapshot = normalize(raw)
    path = archive(raw, directory / "raw")
    new = save_snapshot(db, snapshot, str(path.relative_to(directory)), digest(raw), quality)
    flagged = sum(bool(quality_flags(snapshot, q, quality)) for q in snapshot.quotes)
    state = "saved" if new else "already present"
    print(
        f"{snapshot.capture_id} {state} | {len(snapshot.quotes)} quotes, {flagged} flagged | {path}",
        flush=True,
    )


def positive_int(value):
    """Parse a strictly positive whole number supplied to the command-line parser.

    Convert value with int and return the result when it is at least one. A zero or
    negative result raises argparse.ArgumentTypeError, and noninteger text raises a
    conversion error that argparse reports to the caller. The collector uses this for both
    capture count and interval seconds.
    """
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return n


def parser():
    """Build the argument parser shared by the shell entry point and both notebooks.

    Global options select the configuration file, data root and report root. The required
    subcommand chooses database initialization, collection, raw import, valuation, demo or
    replay. Collection accepts a count, pause and optional exact expiry. Valuation accepts
    a capture ID for repeatability.

    Return the configured ArgumentParser. Parsing and dispatch are separate, so a notebook
    can construct the same argument namespace and receive the report directory from run.
    """
    p = argparse.ArgumentParser(
        prog="python -m options_lab",
        description="Local options collection, valuation and synthetic replay",
    )
    p.add_argument("--config", type=Path, default=ROOT / "config/default.toml")
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--report-dir", type=Path, default=Path("reports"))
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db", help="initialize the local market database")
    commands.add_parser("demo", help="import synthetic captures and run the offline replay")
    commands.add_parser("replay", help="replay the stored demo captures")
    collect = commands.add_parser(
        "collect", help="collect market data using the selected configuration"
    )
    collect.add_argument("--count", type=positive_int, default=1)
    collect.add_argument(
        "--interval-seconds", type=positive_int, help="pause between completed captures"
    )
    collect.add_argument(
        "--expiry", type=date.fromisoformat, help="exact listed expiry (YYYY-MM-DD)"
    )
    value = commands.add_parser("value", help="value a stored market snapshot")
    value.add_argument("--capture", help="capture ID, defaults to latest market capture")
    imp = commands.add_parser(
        "import-capture", help="reimport an archived capture using its market configuration"
    )
    imp.add_argument("path", type=Path)
    return p


def run_amsterdam(args, settings: AmsterdamSettings) -> Path | None:
    """Dispatch a parsed command against the Amsterdam execution database.

    args supplies paths and command options. settings selects the exchange share, option
    class, capture window and pricing assumptions. Collection retrieves and commits each
    delayed window separately, and import-capture can rebuild it from archived JSON. The
    value command reads a pinned or latest matching capture and writes a EUR trade report.

    Return the directory for value and None for initialization, import or collection. A
    missing valuation capture or a request for the USD synthetic demo or replay under this
    profile raises ValueError.
    """
    market = settings.euronext
    if args.command in ("demo", "replay"):
        raise ValueError(
            "The synthetic USD replay uses config/default.toml. Use collect or value for Amsterdam trades."
        )
    with amsterdam_database(args.data_dir) as db:
        if args.command == "init-db":
            print(f"Amsterdam database ready: {args.data_dir / 'amsterdam.sqlite3'}")
        elif args.command == "value":
            info, rows = read_report(db, settings, args.capture)
            if info is None:
                raise ValueError(
                    "No matching Amsterdam capture. Run collect with this configuration first."
                )
            path = write_trade_report(args.report_dir, info, rows, settings)
            print(f"{len(rows)} Amsterdam option trades | EUR per share | {path}")
            return path
        elif args.command == "import-capture":
            capture_id, count = save_window(
                db, json.loads(args.path.read_text()), args.data_dir, settings
            )
            print(f"{capture_id} | {count} Amsterdam option executions in archived window")
        elif args.command == "collect":
            for i in range(args.count):
                if i:
                    sleep(args.interval_seconds or market.interval_seconds)
                raw = fetch_trades(market, args.expiry)
                capture_id, count = save_window(db, raw, args.data_dir, settings)
                print(
                    f"{capture_id} | {market.underlying} Amsterdam | {count} option executions "
                    f"in delayed window | retrieved {raw['retrieved_at']}",
                    flush=True,
                )
    return None


def run(args) -> Path | None:
    """Execute a parsed project command and return a report path when one is produced.

    Load args.config and dispatch Amsterdam work to run_amsterdam. Under the U.S. profile,
    market collection and valuation use options.sqlite3. The demo and replay use
    demo.sqlite3, and both verify stored input hashes against the bundled fixture before
    replay. demo loads missing fixture captures first.

    Collect and import write raw market data and normalized quotes. value reports either a
    requested market snapshot or the latest stored one. A report-producing command prints
    its summary and returns its directory. Other successful commands return None.
    Exceptions propagate to the caller for notebook display or CLI handling.
    """
    settings = load_settings(args.config)
    if isinstance(settings, AmsterdamSettings):
        return run_amsterdam(args, settings)
    demo = args.command in ("demo", "replay")
    db_path = args.data_dir / ("demo.sqlite3" if demo else "options.sqlite3")
    with database(db_path) as db:
        if args.command == "init-db":
            print(f"Market database ready: {db_path}")
        elif demo:
            close_at, inputs = fixture_inputs()
            if args.command == "demo":
                added = sum(
                    save_snapshot(db, s, str(FIXTURE.relative_to(ROOT)), sha, settings.quality)
                    for s, sha in inputs
                )
                print(
                    f"Synthetic database: {db_path} | {added} new, {len(inputs)} selected captures"
                )
            ids = [s.capture_id for s, _ in inputs]
            sources = [provenance(db, i) for i in ids]
            if any(p["input_sha256"] != sha for p, (_, sha) in zip(sources, inputs)):
                raise ValueError("stored demo differs from the bundled fixture")
            frames = [read_snapshot(db, i) for i in ids]
            result = replay(frames, close_at, settings)
            path = write_run(args.report_dir, frames, sources, settings, result)
            print(
                f"Synthetic replay | closed trades: {result['closed_trades']} | "
                f"realized P&L USD {result['realized_pnl_usd']} | {result['position_status']}"
            )
            print(f"Report: {path}")
            return path
        elif args.command == "collect":
            for raw in iter_captures(
                settings.collection,
                count=args.count,
                interval_seconds=args.interval_seconds,
                expiry=args.expiry,
            ):
                save_market(db, raw, args.data_dir, settings.quality)
        elif args.command == "import-capture":
            save_market(db, json.loads(args.path.read_text()), args.data_dir, settings.quality)
        elif args.command == "value":
            capture_id = args.capture or latest_market_id(db)
            frame = read_snapshot(db, capture_id)
            if frame.source != "market":
                raise ValueError("value requires a market capture")
            path = write_run(args.report_dir, [frame], [provenance(db, capture_id)], settings)
            print(f"Valued {capture_id}: {path}")
            return path
    return None


def main(argv=None):
    """Run the shell entry point and return its process exit status.

    argv may be a sequence of argument strings. The default lets argparse read the process
    arguments. After successful parsing, dispatch through run. Return 0 on success, 1 after
    reporting a handled input, file or database error to stderr, or 130 when interrupted.
    Previously completed captures survive an interrupted session.

    Argument parsing occurs before command error handling, so help and invalid syntax
    follow argparse's usual SystemExit behavior.
    """
    args = parser().parse_args(argv)
    try:
        run(args)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        print(f"options_lab: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Collection interrupted. Completed captures are saved.", file=sys.stderr)
        return 130
    return 0
