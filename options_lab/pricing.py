"""Expose the European pricing functions at their original application import path.

black_scholes prices scalar inputs and model_value adapts a captured quote to those inputs.
YEAR_SECONDS is their fixed 365-day time basis for timestamps. All three names are imported
directly from modules.models.black_scholes, where the per-share units and boundary cases
are documented.
"""

from modules.models.black_scholes import YEAR_SECONDS, black_scholes, model_value

__all__ = ["YEAR_SECONDS", "black_scholes", "model_value"]
