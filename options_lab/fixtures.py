import json

from .config import ROOT
from .domain import Contract, Quote, Snapshot, digest, parse_time

FIXTURE = ROOT / "tests/fixtures/demo.json"


def fixture_inputs():
    data = json.loads(FIXTURE.read_text())
    contracts = [
        Contract(underlying=data["underlying"], expiry_at=parse_time(data["expiry_at"]), **fields)
        for fields in data["contracts"]
    ]
    inputs = []
    for row in data["observations"]:
        quotes = []
        for contract in contracts:
            stamp, bid, ask = row["quotes"][contract.symbol]
            quotes.append(Quote(contract, parse_time(stamp) if stamp else None, bid, ask))
        snapshot = Snapshot(
            row["id"],
            "synthetic",
            "fixture",
            "synthetic",
            "synthetic",
            parse_time(row["retrieved_at"]),
            data["underlying"],
            row["spot"],
            parse_time(row["underlying_at"]) if row["underlying_at"] else None,
            tuple(quotes),
        )
        input_hash = digest([data["underlying"], data["expiry_at"], data["contracts"], row])
        inputs.append((snapshot, input_hash))
    return parse_time(data["session_close"]), inputs
