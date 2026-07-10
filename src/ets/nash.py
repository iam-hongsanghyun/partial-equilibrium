# Backward-compatibility shim — re-exports the engine-bound entry point.
# New location: src/ets/engine (feature runtime:
# features/nash_cournot/solver.py; retargeted one hop past the solvers shim
# at v1 O11 / v2 O15).
import warnings

from .engine import solve_nash_path

warnings.warn(
    "ets.nash is deprecated; import from ets.engine instead. "
    "Removal milestone: after the frontend migrates to the graph API (v2.0).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["solve_nash_path"]
