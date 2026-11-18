"""Compatibility imports for the original Alpaca adapter."""

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
