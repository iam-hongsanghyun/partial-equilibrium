# Backward-compatibility shim — the policy-event splicer moved to
# engine/events.py in the engine work order (v1 O8 / v2 O12,
# docs/feature-modules-plan.md).
import warnings

from ..engine.events import solve_scenario_with_events, validate_policy_events

warnings.warn(
    "ets.solvers.events is deprecated; import from ets.engine instead. "
    "Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "solve_scenario_with_events",
    "validate_policy_events",
]
