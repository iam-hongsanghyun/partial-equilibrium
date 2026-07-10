# Backward-compatibility shim — re-exports the canonical homes directly
# (retargeted one hop past the solvers shims in the app-tier tidy order,
# v1 O13 / v2 O17): solve entry points on ets.engine, the path-details
# ledger in ets.core.ledger, the perfect-foresight helper in
# ets.features.competitive.
import warnings

from .core.ledger import (
    collect_path_results as _collect_path_results,
    market_year_sort_key as _market_year_sort_key,
    simulate_path_details as _simulate_path_details,
)
from .engine.dispatch import (
    _rename_markets,
    run_simulation,
    run_simulation_from_config,
    run_simulation_from_file,
)
from .engine.wiring import solve_scenario_path
from .features.competitive.solver import _simulate_realized_prices

warnings.warn(
    "ets.simulation is deprecated; import from ets.engine instead "
    "(ledger internals: ets.core.ledger). "
    "Removal milestone: after the frontend migrates to the graph API (v2.0).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "solve_scenario_path",
    "run_simulation",
    "run_simulation_from_config",
    "run_simulation_from_file",
    "_simulate_path_details",
    "_simulate_realized_prices",
    "_collect_path_results",
    "_rename_markets",
    "_market_year_sort_key",
]
