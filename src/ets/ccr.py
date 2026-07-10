# Backward-compatibility shim — re-exports the canonical homes directly
# (retargeted one hop past the solvers shim in the app-tier tidy order,
# v1 O13 / v2 O17): the CCR runtime lives in ets.features.ccr, the defaults
# in ets.core.defaults.
import warnings

from .core.defaults import CCR_DEFAULTS
from .features.ccr import CCRState

warnings.warn(
    "ets.ccr is deprecated; import CCRState from ets.features.ccr and "
    "CCR_DEFAULTS from ets.core.defaults instead. "
    "Removal milestone: after the frontend migrates to the graph API (v2.0).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["CCRState", "CCR_DEFAULTS"]
