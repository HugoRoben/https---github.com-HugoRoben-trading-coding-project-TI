"""Collect a fixed selection of Alpaca option contracts over one supervised session.

The first usable IEX stock midpoint determines the strike band and the first matching
expiry. Each collection interval retrieves a new stock quote and the latest indicative
quotes for the selected symbols. The resulting dictionaries carry the catalog pages,
selection inputs and retrieval times needed to reconstruct the observations.
"""

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
    """Yield one completed raw capture at a time for a single collection session.

    config supplies the underlying, expiry window, strike selection and default pause.
    count bounds the number of captures. interval_seconds overrides the pause between
    captures, and expiry restricts the first catalog search to a listed date. Both count
    and the effective interval must be positive.

    The first request runs when iteration starts. Later captures reuse the selected
    contract universe and are separated by a sleep. Results already yielded can be archived
    independently if a subsequent request fails or the session is interrupted.
    """
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
    """Retrieve one U.S. stock quote and a batch of indicative option quotes.

    get must accept an endpoint URL and query mapping and return decoded JSON. With
    universe omitted, use the latest stock midpoint and config to select contracts,
    optionally for expiry. An unusable initial midpoint raises AlpacaError. Passing a
    previous universe reuses its selection even if the stock has moved.

    Return the original responses, selection metadata, feed labels, a fresh capture ID, the
    stock receipt time and the final retrieval time. Both local timestamps are UTC.
    Normalization, quality checks and persistence happen downstream.
    """
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
    """Select nearby strikes at the earliest expiry returned by the contract catalog.

    Use spot in USD per share to build a symmetric strike band. Derive calendar-day expiry
    bounds from now in New York, or request the exact future date supplied as expiry.
    Follow every catalog page through get and retain eligible calls and puts for the
    configured underlying and root.

    Rank distinct strikes by distance to spot, resolving ties in favor of the lower strike.
    Return their sorted symbols with the original query, pages, selection time and spot.
    Empty selections, repeated page tokens, duplicate selected symbols and selections over
    100 symbols raise AlpacaError.
    """
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
