# Backward-compatibility shim — re-exports from core.market.clearing.
# New location: src/ets/core/market/clearing.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.market.clearing import (
    total_net_demand,
    solve_equilibrium,
    _participant_outcome,
    _solve_for_supply,
)

__all__ = [
    "total_net_demand",
    "solve_equilibrium",
    "_participant_outcome",
    "_solve_for_supply",
]
