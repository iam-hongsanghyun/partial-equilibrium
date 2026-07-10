# Backward-compatibility shim — the banking runtime moved to features/banking/
# (window.py / solver.py) in the banking feature order (v1 O9 / v2 O13,
# docs/feature-modules-plan.md). solve_banking_path re-exports the
# ENGINE-BOUND entry point (ets.engine.wiring), which resolves today's
# default rule wiring exactly as this module used to (decree XOR
# bank-threshold from the first market's flags, floor-cancellation slot,
# hoarding friction, delivered-floor clip); the transitional _default_*
# delegates are alias re-exports of the wiring builders.
import warnings

from ..core.defaults import BANKING_DEFAULTS
from ..engine.wiring import (
    default_friction as _default_friction,
    default_supply_rule_factories as _default_supply_rule_factories,
    solve_banking_path,
)
from ..features.banking.window import solve_banking_window

# Re-exports carried over from the pre-move module surface (O6): the decree
# action and both MSR supply rules, importable from here until retirement
# (sourced one hop from the feature so only THIS shim's warning fires).
from ..features.msr import (
    DecreeSupplyRule,
    MSRState,
    ThresholdMSRSupplyRule,
    decree_msr_action as _decree_msr_action,
)

warnings.warn(
    "ets.solvers.banking is deprecated; import solve_banking_path from "
    "ets.engine (runtime: ets.features.banking; default wiring: "
    "ets.engine.wiring). Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "BANKING_DEFAULTS",
    "DecreeSupplyRule",
    "MSRState",
    "ThresholdMSRSupplyRule",
    "_decree_msr_action",
    "_default_friction",
    "_default_supply_rule_factories",
    "solve_banking_path",
    "solve_banking_window",
]
