"""Authenticated HTTP requests and Alpaca endpoint selection."""

import json
import os
from pathlib import Path
from socket import gaierror
from ssl import SSLCertVerificationError
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATA_URL = "https://data.alpaca.markets"
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"
CONTRACTS_PATH = "/v2/options/contracts"
CONTRACTS_URL = PAPER_BASE_URL + CONTRACTS_PATH


class AlpacaError(ValueError):
    """A collector diagnostic suitable for display without headers or response bodies."""


def load_alpaca_keys(path: Path) -> bool:
    """Load the notebook's Alpaca settings and report whether both credentials are available."""
    from dotenv import dotenv_values  # Optional notebook dependency.

    values = dotenv_values(path, interpolate=False)
    required = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
    for name in (*required, "APCA_API_BASE_URL"):
        if name in values:
            os.environ[name] = values[name] or ""
    return all(os.environ.get(name) for name in required)


def contract_catalog_url() -> str:
    """Choose the contract metadata host for the configured account."""
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
    """Build a JSON GET callable using the Alpaca credentials in the environment."""
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
