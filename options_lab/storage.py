"""Expose SQLite quote persistence at the original application import path.

database opens and initializes a quote store. save_snapshot and read_snapshot write and
reconstruct individual captures with versioned contract terms. provenance and
latest_market_id select inputs for valuation reports. These names refer directly to their
implementations in modules.storage_reporting.database.
"""

from modules.storage_reporting.database import (
    database,
    latest_market_id,
    provenance,
    read_snapshot,
    save_snapshot,
)

__all__ = ["database", "latest_market_id", "provenance", "read_snapshot", "save_snapshot"]
