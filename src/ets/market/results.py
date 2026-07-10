# Backward-compatibility shim — re-exports from core.market.reporting.
# New location: src/ets/core/market/reporting.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.market.reporting import participant_results, scenario_summary

__all__ = [
    "participant_results",
    "scenario_summary",
]
