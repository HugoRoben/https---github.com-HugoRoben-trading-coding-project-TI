"""Build valuation tables, summarize completed simulated trades and write report bundles.

Market quote reports retain the observed bid, ask, spot, feed provenance and quality flags
alongside a per-share model scenario. Synthetic replay reports also include an event
ledger. The shared file writer stages CSV and JSON together so a reader can open a
completed report directory as a unit.
"""

import csv
from dataclasses import asdict
from decimal import Decimal
import errno
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.models.black_scholes import model_value
from options_lab import __version__
from options_lab.config import Settings
from options_lab.domain import Snapshot, digest, iso
from options_lab.validation import quality_flags


def closed_trade_rows(events: list[dict]):
    """Yield one report row for each matched buy and sell in a chronological replay ledger.

    events follows the single-position simulator's event format. A buy opens the pending
    entry and a sell for the same symbol closes it. Signals and cancellations pass through
    without producing rows. A final unmatched buy represents an open position and
    contributes no completed trade.

    Each row includes entry and exit times, contracts, multiplier, per-share fills, total
    fees, net USD P&L, remaining cash and exit reason. Monetary fields are Decimals. A
    second buy before the exit or a sell without its matching entry raises ValueError as
    the generator is consumed.
    """
    entry = None
    for event in events:
        if event["action"] == "buy":
            if entry is not None:
                raise ValueError("replay has two entries for one open position")
            entry = event
        elif event["action"] == "sell":
            if entry is None or entry["symbol"] != event["symbol"]:
                raise ValueError("replay exit has no matching entry")
            yield {
                "symbol": event["symbol"],
                "entry_utc": entry["at"],
                "exit_utc": event["at"],
                "contracts": entry["quantity"],
                "multiplier": entry["multiplier"],
                "buy_per_share": Decimal(entry["price_per_share"]),
                "sell_per_share": Decimal(event["price_per_share"]),
                "fees_usd": Decimal(entry["fee_usd"]) + Decimal(event["fee_usd"]),
                "net_pnl_usd": Decimal(event["trade_pnl_usd"]),
                "cash_after_usd": Decimal(event["cash_usd"]),
                "exit_reason": event["reason"],
            }
            entry = None


def valuation_rows(snapshots: list[Snapshot], settings: Settings):
    """Yield one provenance-labelled USD valuation row per option in each input snapshot.

    Use settings.quality to assess the observation clocks and quotes, and settings.model
    for the European per-share price. An unusable underlying, unsupported currency or
    expired contract suppresses the model value. A missing option quote can still have a
    model value if the underlying and expiry are usable.

    Calculate model_minus_ask only for a row with no quality flags. Price outputs are
    rounded to six decimal places. Observed sides, feed names, UTC times, contract terms
    and flags remain in the row so a reader can assess the comparison.
    """
    for s in snapshots:
        for q in s.quotes:
            c = q.contract
            flags = quality_flags(s, q, settings.quality)
            # A suitable stock observation can price a share even if the option quote is missing.
            invalid_inputs = {
                "missing_or_invalid_spot",
                "missing_underlying_time",
                "future_underlying",
                "stale_underlying",
                "expired",
                "unsupported_currency",
            }
            value = (
                None if invalid_inputs.intersection(flags) else model_value(s, q, settings.model)
            )
            yield dict(
                capture_id=s.capture_id,
                source=s.source,
                provider=s.provider,
                option_feed=s.option_feed,
                underlying_feed=s.underlying_feed,
                retrieved_at_utc=iso(s.retrieved_at),
                underlying=s.underlying,
                underlying_at_utc=iso(s.underlying_at) if s.underlying_at else None,
                spot=s.spot,
                symbol=c.symbol,
                kind=c.kind,
                expiry_utc=iso(c.expiry_at),
                expiry_time_assumed=c.expiry_time_assumed,
                strike=c.strike,
                exercise_style=c.exercise_style,
                currency=c.currency,
                multiplier=c.multiplier,
                quote_at_utc=iso(q.quote_at) if q.quote_at else None,
                bid=q.bid,
                ask=q.ask,
                model_per_share=round(value, 6) if value is not None else None,
                model_minus_ask=round(value - q.ask, 6)
                if value is not None and not flags
                else None,
                quality_flags="|".join(flags) or "ok",
            )


def write_run(
    directory: Path,
    snapshots: list[Snapshot],
    inputs: list[dict],
    settings: Settings,
    simulation: dict | None = None,
) -> Path:
    """Write a reproducible USD valuation or synthetic replay report under directory.

    snapshots supply quote rows, inputs supply the corresponding provenance dictionaries
    and settings records the model and simulation assumptions. Passing a simulation result
    also saves its ledger and includes the session and execution rules in the manifest. At
    least one quote row is required.

    Return the report directory containing valuations.csv and manifest.json, with
    replay.json for a simulated run. Its name includes a digest of the manifest, rows and
    simulation, so repeating the same run resolves to the same directory.
    """
    rows = list(valuation_rows(snapshots, settings))
    if not rows:
        raise ValueError("no quote rows to report")
    manifest = dict(
        version=__version__,
        inputs=inputs,
        settings=asdict(settings),
        pricing="European Black–Scholes–Merton; ACT/365F from retrieval to expiry. Constant annual "
        "volatility and continuously compounded rate/yield are scenarios. Early exercise "
        "and discrete dividends are omitted.",
        prices="USD per share; premiums use the observed contract multiplier.",
        feed_note=(
            "Invented fixture quotes and simulated outcomes."
            if snapshots[0].source == "synthetic"
            else "Alpaca indicative option quotes and IEX stock bid/ask midpoints. "
            "Indicative quotes are modified. Expiry time assumes 16:00 America/New_York."
        ),
    )
    if simulation is not None:
        manifest["session_close_utc"] = simulation["session_close_utc"]
        manifest["execution"] = (
            "One long call. Buy at a later eligible ask plus slippage; sell at "
            "an eligible bid less slippage. One fee per contract on each side."
        )
    kind = "replay" if simulation is not None else "valuation"
    run_id = digest([manifest, rows, simulation])[:16]
    outputs = {"manifest.json": manifest}
    if simulation is not None:
        outputs["replay.json"] = simulation
    return write_report_files(
        directory / f"{kind}-{run_id}", "valuations.csv", list(rows[0]), rows, outputs
    )


def write_report_files(target: Path, csv_name: str, columns, rows, outputs: dict) -> Path:
    """Write a CSV and its associated JSON files as one completed report directory.

    target is the caller's final report path. csv_name, columns and rows define the CSV,
    including its header when rows is empty. outputs maps companion filenames to
    JSON-serializable objects. Stage all files under the same parent, then rename the
    completed directory into place.

    Return target if a report already occupies it or if another writer finishes the same
    target first. Serialization and unrelated filesystem errors propagate. The temporary
    staging directory is cleaned up on exit.
    """
    if target.is_dir():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target.parent) as tmp:
        staging = Path(tmp) / "run"
        staging.mkdir()
        with (staging / csv_name).open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        for name, data in outputs.items():
            (staging / name).write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
        try:
            staging.rename(target)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY) or not target.is_dir():
                raise
    return target
