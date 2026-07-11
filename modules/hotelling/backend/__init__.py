"""hotelling feature (T2) — the exhaustible-resource (Hotelling rule) price path.

Runtime-only feature (no config door): ``solver.py`` holds
``solve_hotelling_path`` (λ-bisection on the cumulative carbon budget) with
the competitive-fallback cap rules injected, moved from
``solvers/hotelling.py`` in the hotelling/nash feature order (v1 O11 /
v2 O15) and wired exclusively by ``ets.engine``.
``ets/solvers/hotelling.py`` remains as a re-export shim.

This ``__init__`` is the feature's deliberate public surface.
"""

from .solver import solve_hotelling_path

__all__ = [
    "solve_hotelling_path",
]
