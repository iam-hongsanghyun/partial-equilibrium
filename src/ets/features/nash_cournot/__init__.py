"""nash_cournot feature (T2) — Cournot-Nash equilibrium in abatement quantities.

Runtime-only feature (no config door): ``solver.py`` holds
``solve_nash_path`` (best-response iteration; F2-frozen inline MSR with an
injected duck-typed state), moved from ``solvers/nash.py`` in the
hotelling/nash feature order (v1 O11 / v2 O15) and wired exclusively by
``ets.engine``. ``ets/solvers/nash.py`` remains as a re-export shim.

This ``__init__`` is the feature's deliberate public surface.
"""

from .solver import solve_nash_path

__all__ = [
    "solve_nash_path",
]
