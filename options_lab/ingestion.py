"""Read-only Alpaca market data. Each saved envelope can be imported without a network call."""

from datetime import UTC, date, datetime, time, timedelta
import json
from math import isfinite
import os
from pathlib import Path
from socket import gaierror
from ssl import SSLCertVerificationError
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from .config import Collection
from .domain import Contract, Quote, Snapshot, digest, iso, parse_time

DATA_URL = "https://data.alpaca.markets"
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
CONTRACTS_PATH = "/v2/options/contracts"
CONTRACTS_URL = PAPER_BASE_URL + CONTRACTS_PATH
NEW_YORK = ZoneInfo("America/New_York")
FORMAT = "alpaca-options-v1"


class AlpacaError(ValueError):
    """A collector diagnostic suitable for display without headers or response bodies."""


def contract_catalog_url() -> str:
    configured = os.getenv("APCA_API_BASE_URL", "").strip()
    if not configured:
        # Legacy key prefixes are a hint. An explicit account host takes precedence.
        if os.getenv("APCA_API_KEY_ID", "").startswith("AK"):
            return LIVE_BASE_URL + CONTRACTS_PATH
        return CONTRACTS_URL
    base = configured.rstrip("/").removesuffix("/v2")
    if base not in (PAPER_BASE_URL, LIVE_BASE_URL):
        raise AlpacaError(
            "APCA_API_BASE_URL must be https://paper-api.alpaca.markets "
            "or https://api.alpaca.markets."
        )
    return base + CONTRACTS_PATH


def authenticated_get():
    key = os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise AlpacaError("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY for collection.")

    def get(url, params):
        request = Request(
            f"{url}?{urlencode(params)}",
            method="GET",
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                return json.load(response)
        except HTTPError as error:
            help_text = {
                400: "Alpaca rejected the request parameters",
                401: "check that the key ID and secret belong to the account for this host",
                403: "check account permissions for this endpoint or feed",
                429: "rate limit reached; retry later",
            }.get(error.code, "request failed")
            raise AlpacaError(f"GET {url} returned HTTP {error.code}: {help_text}.") from error
        except OSError as error:
            reason = error.reason if isinstance(error, URLError) else error
            if isinstance(reason, gaierror):
                detail = "DNS lookup failed"
            elif isinstance(reason, SSLCertVerificationError):
                detail = "TLS certificate verification failed"
            elif isinstance(reason, TimeoutError):
                detail = "connection timed out"
            else:
                detail = "network connection failed"
            raise AlpacaError(f"GET {url} failed: {detail}.") from error

    return get


def number(value) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    return result if isfinite(result) else None


def stock_midpoint(response: dict) -> float | None:
    quote = response.get("quote") or {}
    bid, ask = number(quote.get("bp")), number(quote.get("ap"))
    if bid is None or ask is None or not 0 < bid <= ask:
        return None
    return (bid + ask) / 2


def select_universe(get, config: Collection, spot: float, now: datetime, expiry: date | None):
    today = now.astimezone(NEW_YORK).date()
    if expiry and expiry <= today:
        raise ValueError("choose a listed expiry after today (New York date)")
    params = dict(
        underlying_symbols=config.underlying,
        root_symbol=config.underlying,
        status="active",
        limit=1000,
        strike_price_gte=f"{spot * (1 - config.strike_band_fraction):.2f}",
        strike_price_lte=f"{spot * (1 + config.strike_band_fraction):.2f}",
    )
    if expiry:
        params["expiration_date"] = expiry.isoformat()
    else:
        params["expiration_date_gte"] = (
            today + timedelta(days=config.min_days_to_expiry)
        ).isoformat()
        params["expiration_date_lte"] = (
            today + timedelta(days=config.max_days_to_expiry)
        ).isoformat()
    pages, tokens = [], set()
    query = params.copy()
    endpoint = contract_catalog_url()
    while True:
        page = get(endpoint, query)
        pages.append(page)
        token = page.get("next_page_token")
        if not token:
            break
        if token in tokens:
            raise AlpacaError("Alpaca returned a repeated contract-list pagination token.")
        tokens.add(token)
        query = {**params, "page_token": token}
    contracts = [
        c
        for page in pages
        for c in (page["option_contracts"] or [])
        if c["underlying_symbol"] == config.underlying
        and c["root_symbol"] == config.underlying
        and c["type"] in ("call", "put")
    ]
    if not contracts:
        raise AlpacaError(
            "No listed contracts matched the requested expiry window and strike band."
        )
    first_expiry = min(c["expiration_date"] for c in contracts)
    contracts = [c for c in contracts if c["expiration_date"] == first_expiry]
    strikes = sorted(
        {float(c["strike_price"]) for c in contracts}, key=lambda k: (abs(k - spot), k)
    )
    chosen = set(strikes[: config.nearest_strikes])
    symbols = sorted(c["symbol"] for c in contracts if float(c["strike_price"]) in chosen)
    if len(symbols) > 100 or len(symbols) != len(set(symbols)):
        raise AlpacaError("Alpaca returned an invalid or oversized contract selection.")
    return dict(
        selection_spot=spot,
        selected_at=iso(now),
        endpoint=endpoint,
        query=params,
        pages=pages,
        symbols=symbols,
    )


def fetch_capture(get, config: Collection, expiry: date | None, universe=None):
    symbol = config.underlying
    stock = get(f"{DATA_URL}/v2/stocks/{symbol}/quotes/latest", {"feed": "iex", "currency": "USD"})
    stock_received = datetime.now(UTC)
    if universe is None:
        spot = stock_midpoint(stock)
        if spot is None:
            raise AlpacaError(
                f"The first IEX quote for {symbol} needs a positive, uncrossed bid "
                "and ask to select nearby strikes."
            )
        universe = select_universe(get, config, spot, stock_received, expiry)
    options = get(
        f"{DATA_URL}/v1beta1/options/quotes/latest",
        {"feed": "indicative", "symbols": ",".join(universe["symbols"])},
    )
    return dict(
        format=FORMAT,
        capture_id=uuid4().hex,
        retrieved_at=iso(datetime.now(UTC)),
        underlying=symbol,
        option_feed="indicative",
        underlying_feed="iex",
        stock_received_at=iso(stock_received),
        stock_response=stock,
        universe=universe,
        options_response=options,
    )


def normalize(raw: dict) -> Snapshot:
    if raw["format"] != FORMAT or (raw["option_feed"], raw["underlying_feed"]) != (
        "indicative",
        "iex",
    ):
        raise ValueError("unsupported capture format or feeds")
    symbol = raw["underlying"]
    stock = raw["stock_response"]
    if stock.get("symbol", symbol) != symbol:
        raise ValueError("stock response does not match the requested underlying")
    universe = raw["universe"]
    metadata = {
        c["symbol"]: c for page in universe["pages"] for c in (page["option_contracts"] or [])
    }
    book = raw["options_response"]["quotes"] or {}
    quotes = []
    for name in universe["symbols"]:
        c = metadata[name]
        # The provider supplies an expiry date. The local cutoff is a model convention.
        expiry_at = datetime.combine(date.fromisoformat(c["expiration_date"]), time(16), NEW_YORK)
        contract = Contract(
            name,
            c["underlying_symbol"],
            expiry_at.astimezone(UTC),
            c["type"],
            float(c["strike_price"]),
            "USD",
            number(c.get("multiplier")),
            c.get("style") or "unknown",
            expiry_time_assumed=True,
        )
        q = book.get(name) or {}
        quotes.append(
            Quote(
                contract,
                parse_time(q["t"]) if q.get("t") else None,
                number(q.get("bp")),
                number(q.get("ap")),
            )
        )
    timestamp = (stock.get("quote") or {}).get("t")
    return Snapshot(
        raw["capture_id"],
        "market",
        "alpaca",
        raw["option_feed"],
        raw["underlying_feed"],
        parse_time(raw["retrieved_at"]),
        symbol,
        stock_midpoint(stock),
        parse_time(timestamp) if timestamp else None,
        tuple(quotes),
    )


def archive(raw: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest(raw)}.json"
    if not path.exists():
        with NamedTemporaryFile(mode="w", dir=directory, delete=False) as tmp:
            temp = Path(tmp.name)
            try:
                json.dump(raw, tmp, indent=2, allow_nan=False)
                tmp.write("\n")
                tmp.flush()
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
    return path
