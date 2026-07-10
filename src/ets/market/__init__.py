# Backward-compatibility shim package — re-exports from core.market.
# New location: src/ets/core/market/ (core.py -> model.py,
# equilibrium.py -> clearing.py, results.py -> reporting.py).
# Importing this package imports core.market, which performs the
# CarbonMarket method attachment exactly as before the move.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.market import CarbonMarket

__all__ = ["CarbonMarket"]
