# Backward-compatibility shim — re-exports from core.market.model.
# New location: src/ets/core/market/model.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.market.model import CarbonMarket

__all__ = ["CarbonMarket"]
