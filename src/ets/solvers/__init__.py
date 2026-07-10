from .simulation import run_simulation, solve_scenario_path, run_simulation_from_config, run_simulation_from_file
from .hotelling import solve_hotelling_path
from .nash import solve_nash_path
from .transmission import blend_prices, solve_transmission_path
from .banking import BANKING_DEFAULTS, solve_banking_path
from .msr import MSRState, MSR_DEFAULTS
from .ccr import CCRState, CCR_DEFAULTS
from .expectations import (
    ALLOWED_EXPECTATION_RULES,
    ExpectationSpec,
    expectation_sort_key,
    validate_expectation_rule,
    build_expectation_specs,
    derive_expected_prices,
)


def compute_baseline_prices(markets) -> dict[str, float]:
    """Compute baseline (no-banking) equilibrium price for each year."""
    return {str(market.year): market.find_equilibrium_price() for market in markets}


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
