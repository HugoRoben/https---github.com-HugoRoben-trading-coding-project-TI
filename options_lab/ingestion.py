"""Expose the original import paths for Alpaca collection and raw archiving.

Earlier callers can import the client, endpoint constants, strike selection, response
normalization and archive helper from this module. The implementations live in
modules.alpaca and modules.storage_reporting.raw_captures. The objects are re-exported
directly, so their signatures, exceptions and docstrings match those at the implementation
paths.
"""

from modules.alpaca.client import (
    CONTRACTS_PATH,
    CONTRACTS_URL,
    DATA_URL,
    LIVE_BASE_URL,
    PAPER_BASE_URL,
    AlpacaError,
    authenticated_get,
    contract_catalog_url,
)
from modules.alpaca.normalization import FORMAT, NEW_YORK, normalize, number, stock_midpoint
from modules.alpaca.retrieval import fetch_capture, select_universe
from modules.storage_reporting.raw_captures import archive

__all__ = [
    "CONTRACTS_PATH",
    "CONTRACTS_URL",
    "DATA_URL",
    "FORMAT",
    "LIVE_BASE_URL",
    "NEW_YORK",
    "PAPER_BASE_URL",
    "AlpacaError",
    "archive",
    "authenticated_get",
    "contract_catalog_url",
    "fetch_capture",
    "normalize",
    "number",
    "select_universe",
    "stock_midpoint",
]
