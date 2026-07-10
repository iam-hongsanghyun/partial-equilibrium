# Backward-compatibility shim — the Nash-Cournot runtime moved to
# features/nash_cournot/solver.py in the hotelling/nash feature order
# (v1 O11 / v2 O15, docs/feature-modules-plan.md). solve_nash_path
# re-exports the ENGINE-BOUND entry point (ets.engine.wiring), which injects
# the duck-typed MSR state exactly as this module used to construct it
# inline (F2 preserved bit-for-bit).
import warnings

from ..engine.wiring import solve_nash_path

warnings.warn(
    "ets.solvers.nash is deprecated; import solve_nash_path from "
    "ets.engine instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["solve_nash_path"]
