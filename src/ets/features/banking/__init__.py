"""banking feature (T2) — Rubin/Schennach banking equilibrium with endogenous window.

Two-door layout (``docs/feature-modules-plan.md`` PLAN v2): ``plugin.py`` is
the config door (the ``BANK_CARRIER`` splice declaration); the runtime
modules are ``window.py`` (window search + observables math, including the
hoarding HOST SET) and ``solver.py`` (``solve_banking_path`` — the
supply-rule fixed point, rule-injected per F4). Moved from
``solvers/banking.py`` in the banking feature order (v1 O9 / v2 O13) and
wired exclusively by ``ets.engine`` (the engine-bound entry point resolves
the default rule wiring). ``ets/solvers/banking.py`` remains as a re-export
shim.

This ``__init__`` is the feature's deliberate public surface.
"""

from .solver import solve_banking_path
from .window import solve_banking_window

__all__ = [
    "solve_banking_path",
    "solve_banking_window",
]
