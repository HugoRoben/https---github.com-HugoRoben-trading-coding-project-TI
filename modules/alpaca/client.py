"""Build authenticated read requests for Alpaca stock quotes, options and contract terms.

Quote requests use the data host. Contract discovery uses the paper or live account host
selected by contract_catalog_url. The notebook can load credentials from a dotenv file,
while the CLI reads its process environment. This module handles transport and endpoint
errors before any response is normalized or saved.
"""

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
    """Report a collection failure in terms the CLI or a notebook can display.

    Raised for missing credentials, unsupported account hosts and failed requests, as well
    as unusable contract selections in the collector. HTTP and connection failures retain
    their original exception as the cause. The displayed message identifies the endpoint or
    setting and omits credential headers and response bodies.
    """


def load_alpaca_keys(path: Path) -> bool:
    """Load Alpaca settings from a dotenv file into the current process.

    The optional notebook dependency python-dotenv reads path with interpolation disabled
    so special characters stay literal. Each of the two credential variables and the
    optional account base URL is overwritten when present in the file, even if its value is
    empty. Variables absent from the file keep their current environment values.

    Return True when both credentials are nonempty after loading. This checks their
    presence only. Authentication takes place when the collector sends a request.
    """
    from dotenv import dotenv_values  # Optional notebook dependency.

    values = dotenv_values(path, interpolate=False)
    required = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY")
    for name in (*required, "APCA_API_BASE_URL"):
        if name in values:
            os.environ[name] = values[name] or ""
    return all(os.environ.get(name) for name in required)


def contract_catalog_url() -> str:
    """Resolve the full contract-list URL for the configured Alpaca account.

    An explicit APCA_API_BASE_URL takes precedence and may include a trailing slash or /v2.
    The two supported bases are the paper and live account hosts. Without an override, a
    key ID starting with AK selects live and all other prefixes select paper.

    Return the chosen host with the contracts path appended. An unsupported override raises
    AlpacaError before the collector sends credentials.
    """
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
    """Create a reusable HTTP GET function bound to the current Alpaca credentials.

    Read APCA_API_KEY_ID and APCA_API_SECRET_KEY once from the environment. Raise
    AlpacaError immediately if either is empty. The returned callable accepts an endpoint
    URL and a mapping of query parameters. It sends the captured values in request headers
    and returns the decoded JSON for each call.

    This factory lets a collection session reuse the same credentials and lets offline
    tests supply a callable with the same interface.
    """
    key = os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise AlpacaError("Set APCA_API_KEY_ID and APCA_API_SECRET_KEY for collection.")

    def get(url, params):
        """Request one Alpaca endpoint and decode its JSON response.

        Encode params in the query string of url, attach the session's key headers and use
        a 15-second timeout. On an HTTP or connection failure, raise AlpacaError with the
        endpoint and a short diagnostic. A successful HTTP response with malformed JSON
        raises the decoder's error.
        """
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
