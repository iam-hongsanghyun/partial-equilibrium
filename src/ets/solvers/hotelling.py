# Backward-compatibility shim — the Hotelling runtime moved to
# features/hotelling/solver.py in the hotelling/nash feature order (v1 O11 /
# v2 O15, docs/feature-modules-plan.md). solve_hotelling_path re-exports the
# ENGINE-BOUND entry point (ets.engine.wiring), which injects the F2-frozen
# competitive-fallback cap rules exactly as this module used to construct
# them. DeprecationWarning arms in the app-tier tidy order (v1 O13 / v2 O17,
# milestone 0.3.0).

from ..engine.wiring import solve_hotelling_path

__all__ = ["solve_hotelling_path"]
