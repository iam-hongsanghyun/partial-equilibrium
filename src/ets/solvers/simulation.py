# Backward-compatibility shim — everything this module once held has moved
# (docs/feature-modules-plan.md):
#   * the path-details ledger -> core/ledger.py (v1 O7 / v2 O11), public
#     names; the underscore spellings are re-exported below;
#   * run_simulation / _rename_markets / run_simulation_from_config /
#     run_simulation_from_file -> engine/dispatch.py (v1 O8 / v2 O12);
#   * solve_scenario_path + _simulate_realized_prices ->
#     features/competitive/solver.py (v1 O10 / v2 O14); solve_scenario_path
#     re-exports the ENGINE-BOUND entry point (ets.engine.wiring), which
#     injects today's default cap rules exactly as this module used to.
import warnings

from ..core.ledger import (
    collect_path_results as _collect_path_results,
    market_year_sort_key as _market_year_sort_key,
    simulate_path_details as _simulate_path_details,
)
from ..engine.dispatch import (
    _rename_markets,
    run_simulation,
    run_simulation_from_config,
    run_simulation_from_file,
)
from ..engine.wiring import solve_scenario_path
from ..features.competitive.solver import _simulate_realized_prices

warnings.warn(
    "ets.solvers.simulation is deprecated; import run_simulation* and "
    "solve_scenario_path from ets.engine (ledger internals: "
    "ets.core.ledger). Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "_collect_path_results",
    "_market_year_sort_key",
    "_rename_markets",
    "_simulate_path_details",
    "_simulate_realized_prices",
    "run_simulation",
    "run_simulation_from_config",
    "run_simulation_from_file",
    "solve_scenario_path",
]
