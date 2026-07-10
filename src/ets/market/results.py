# Backward-compatibility shim — re-exports from core.market.reporting.
# New location: src/ets/core/market/reporting.py.
import warnings

from ..core.market.reporting import participant_results, scenario_summary

warnings.warn(
    "ets.market.results is deprecated; import from "
    "ets.core.market.reporting instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "participant_results",
    "scenario_summary",
]
