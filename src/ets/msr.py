# Backward-compatibility shim — re-exports the canonical homes directly
# (retargeted one hop past the solvers shim in the app-tier tidy order,
# v1 O13 / v2 O17): the MSR runtime lives in ets.features.msr, the defaults
# in ets.core.defaults.
import warnings

from .core.defaults import MSR_DEFAULTS
from .features.msr import MSRState

warnings.warn(
    "ets.msr is deprecated; import MSRState from ets.features.msr and "
    "MSR_DEFAULTS from ets.core.defaults instead. "
    "Removal milestone: after the frontend migrates to the graph API (v2.0).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["MSRState", "MSR_DEFAULTS"]
