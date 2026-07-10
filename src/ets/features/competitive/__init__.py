"""competitive feature (T2) — the per-year competitive clearing path.

Runtime-only feature (no config door yet): ``solver.py`` holds
``solve_scenario_path`` with injected cap rules, moved from
``solvers/simulation.py`` in the competitive feature order (v1 O10 /
v2 O14) and wired exclusively by ``ets.engine`` (the engine-bound entry
point constructs today's default cap rules). ``ets/solvers/simulation.py``
remains as a re-export shim.

This ``__init__`` is the feature's deliberate public surface.
"""

from .solver import solve_scenario_path

__all__ = [
    "solve_scenario_path",
]
