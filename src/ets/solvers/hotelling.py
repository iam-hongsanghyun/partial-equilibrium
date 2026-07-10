# Backward-compatibility shim — the Hotelling runtime moved to
# features/hotelling/solver.py in the hotelling/nash feature order (v1 O11 /
# v2 O15, docs/feature-modules-plan.md). solve_hotelling_path re-exports the
# ENGINE-BOUND entry point (ets.engine.wiring), which injects the F2-frozen
# competitive-fallback cap rules exactly as this module used to construct
# them.
import warnings

from ..engine.wiring import solve_hotelling_path

warnings.warn(
    "ets.solvers.hotelling is deprecated; import solve_hotelling_path from "
    "ets.engine instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["solve_hotelling_path"]
