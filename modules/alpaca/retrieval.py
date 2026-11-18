"""Collect a bounded session of stock and option quotes from Alpaca."""

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from time import sleep
from uuid import uuid4

from options_lab.config import Collection
from options_lab.domain import iso

from .client import DATA_URL, AlpacaError, authenticated_get, contract_catalog_url
from .normalization import FORMAT, NEW_YORK, stock_midpoint


def iter_captures(
    config: Collection,
    *,
    count: int = 1,
    interval_seconds: int | None = None,
    expiry: date | None = None,
) -> Iterator[dict]:
    """Yield one raw capture at a time, reusing the first selection for the session."""
    pause = config.interval_seconds if interval_seconds is None else interval_seconds
    if count < 1 or pause <= 0:
        raise ValueError("count and interval_seconds must be positive")
    get = authenticated_get()
    universe = None
    for index in range(count):
        if index:
            sleep(pause)
        raw = fetch_capture(get, config, expiry, universe)
        universe = raw["universe"]
        yield raw


def fetch_capture(
    get, config: Collection, expiry: date | None = None, universe: dict | None = None
) -> dict:
    """Fetch the stock quote, select contracts if needed, then fetch their option quotes."""
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


def select_universe(
    get, config: Collection, spot: float, now: datetime, expiry: date | None
) -> dict:
    """Read every catalog page and choose the nearest strikes at the earliest matching expiry."""
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
