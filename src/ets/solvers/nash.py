# Backward-compatibility shim — the Nash-Cournot runtime moved to
# features/nash_cournot/solver.py in the hotelling/nash feature order
# (v1 O11 / v2 O15, docs/feature-modules-plan.md). solve_nash_path
# re-exports the ENGINE-BOUND entry point (ets.engine.wiring), which injects
# the duck-typed MSR state exactly as this module used to construct it
# inline (F2 preserved bit-for-bit). DeprecationWarning arms in the app-tier
# tidy order (v1 O13 / v2 O17, milestone 0.3.0).

from ..engine.wiring import solve_nash_path

__all__ = ["solve_nash_path"]
