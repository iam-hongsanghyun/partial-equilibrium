# Backward-compatibility shim package — every solver moved out of ets.solvers
# during the feature-module migration (docs/feature-modules-plan.md):
# solve entry points live on ets.engine (engine-bound, default wiring
# injected), rule/state runtimes under ets.features.*, defaults and the
# baseline-price map in ets.core. Re-exports below come one hop from the
# canonical homes so importing this package fires exactly ONE warning.
import warnings

from ..core.baseline import compute_baseline_prices
from ..core.defaults import BANKING_DEFAULTS, CCR_DEFAULTS, MSR_DEFAULTS
from ..core.expectations import (
    ALLOWED_EXPECTATION_RULES,
    ExpectationSpec,
    expectation_sort_key,
    validate_expectation_rule,
    build_expectation_specs,
    derive_expected_prices,
)
from ..engine import (
    run_simulation,
    run_simulation_from_config,
    run_simulation_from_file,
    solve_banking_path,
    solve_hotelling_path,
    solve_nash_path,
    solve_scenario_path,
    solve_transmission_path,
)
from ..features.ccr import CCRState
from ..features.msr import MSRState
from ..features.transmission import blend_prices

warnings.warn(
    "ets.solvers is deprecated; import solve entry points from ets.engine "
    "(rule/state runtimes: ets.features.*; defaults and "
    "compute_baseline_prices: ets.core). Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "run_simulation",
    "solve_scenario_path",
    "run_simulation_from_config",
    "run_simulation_from_file",
    "solve_hotelling_path",
    "solve_nash_path",
    "blend_prices",
    "solve_transmission_path",
    "BANKING_DEFAULTS",
    "solve_banking_path",
    "MSRState",
    "MSR_DEFAULTS",
    "CCRState",
    "CCR_DEFAULTS",
    "compute_baseline_prices",
    "ALLOWED_EXPECTATION_RULES",
    "ExpectationSpec",
    "expectation_sort_key",
    "validate_expectation_rule",
    "build_expectation_specs",
    "derive_expected_prices",
]
