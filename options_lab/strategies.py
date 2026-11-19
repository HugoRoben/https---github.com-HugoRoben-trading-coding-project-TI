"""Expose the synthetic trading rule and fill arithmetic at their original import path.

entry_candidate selects an eligible long call from a snapshot. fill_amount applies
slippage, the contract multiplier and a fee to compute cash movement. money preserves
decimal inputs for that calculation. The implementations live in modules.models.strategies
and are shared with the replay engine.
"""

from modules.models.strategies import entry_candidate, fill_amount, money

__all__ = ["entry_candidate", "fill_amount", "money"]
