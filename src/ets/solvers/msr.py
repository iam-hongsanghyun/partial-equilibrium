# Backward-compatibility shim — the MSR runtime moved to features/msr/
# (state.py / rules.py / decree.py) in the engine work order (v1 O8 / v2 O12,
# docs/feature-modules-plan.md); the defaults re-export from core.defaults
# (O1/O6) stays.
import warnings

from ..core.defaults import (
    DECREE_MSR_MAX_INTAKE_MT,
    DECREE_MSR_MAX_RELEASE_MT,
    DECREE_MSR_PRICE_BAND_HIGH,
    DECREE_MSR_PRICE_BAND_LOW,
    DECREE_MSR_SURPLUS_LOWER_RATIO,
    DECREE_MSR_SURPLUS_UPPER_RATIO,
    MSR_DEFAULTS,
)
from ..features.msr.decree import (
    DecreeSupplyRule,
    decree_msr_action,
    decree_msr_action as _decree_msr_action,
)
from ..features.msr.rules import MSRCapRule, ThresholdMSRSupplyRule
from ..features.msr.state import MSRState

warnings.warn(
    "ets.solvers.msr is deprecated; import from ets.features.msr "
    "(defaults: ets.core.defaults). Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "DECREE_MSR_MAX_INTAKE_MT",
    "DECREE_MSR_MAX_RELEASE_MT",
    "DECREE_MSR_PRICE_BAND_HIGH",
    "DECREE_MSR_PRICE_BAND_LOW",
    "DECREE_MSR_SURPLUS_LOWER_RATIO",
    "DECREE_MSR_SURPLUS_UPPER_RATIO",
    "DecreeSupplyRule",
    "MSRCapRule",
    "MSRState",
    "MSR_DEFAULTS",
    "ThresholdMSRSupplyRule",
    "_decree_msr_action",
    "decree_msr_action",
]
