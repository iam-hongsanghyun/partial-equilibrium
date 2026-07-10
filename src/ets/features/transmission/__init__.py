"""transmission feature (T2) — forward-transmission (λ) blending of price paths.

Runtime-only feature (no config door): ``solver.py`` holds ``blend_prices``
and ``solve_transmission_path`` (strip floors → blend → clip-last, the F3
operation order — one internal function, never split), with the
component-path solvers injected, moved from ``solvers/transmission.py`` in
the transmission feature order (v1 O12 / v2 O16) and wired exclusively by
``ets.engine``. ``ets/solvers/transmission.py`` remains as a re-export shim.

This ``__init__`` is the feature's deliberate public surface.
"""

from .solver import blend_prices, solve_transmission_path

__all__ = [
    "blend_prices",
    "solve_transmission_path",
]
