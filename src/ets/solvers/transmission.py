# Backward-compatibility shim — the forward-transmission (λ) runtime moved
# to features/transmission/solver.py in the transmission feature order
# (v1 O12 / v2 O16, docs/feature-modules-plan.md). solve_transmission_path
# re-exports the ENGINE-BOUND entry point (ets.engine.wiring), which binds
# the component-path solvers exactly as this module's lazy imports used to
# (rule-carrying competitive + Hotelling; blend-then-clip stays internal to
# the feature, F3).
import warnings

from ..engine.wiring import solve_transmission_path
from ..features.transmission.solver import blend_prices

warnings.warn(
    "ets.solvers.transmission is deprecated; import solve_transmission_path "
    "from ets.engine (blend_prices: ets.features.transmission). "
    "Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "blend_prices",
    "solve_transmission_path",
]
