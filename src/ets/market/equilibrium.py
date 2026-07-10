# Backward-compatibility shim — re-exports from core.market.clearing.
# New location: src/ets/core/market/clearing.py.
import warnings

from ..core.market.clearing import (
    total_net_demand,
    solve_equilibrium,
    _participant_outcome,
    _solve_for_supply,
)

warnings.warn(
    "ets.market.equilibrium is deprecated; import from "
    "ets.core.market.clearing instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "total_net_demand",
    "solve_equilibrium",
    "_participant_outcome",
    "_solve_for_supply",
]
