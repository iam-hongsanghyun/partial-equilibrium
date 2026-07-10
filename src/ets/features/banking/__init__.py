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

This ``__init__`` is the feature's deliberate public surface, resolved
LAZILY (PEP 562 ``__getattr__``): ``ets.engine.events`` imports this
feature's ``plugin`` door unconditionally (the ``BANK_CARRIER`` splice
literal), and importing ANY submodule of a package always runs that
package's ``__init__.py`` first — so an eager ``solver``/``window`` import
here would force-load the banking RUNTIME (scipy-backed fixed-point search)
for every simulation regardless of ``model_approach``. Attribute access
still returns the same objects; only the import TIMING moves to first use
(lazy, per-model feature activation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .solver import solve_banking_path as solve_banking_path
    from .window import solve_banking_window as solve_banking_window

__all__ = [
    "solve_banking_path",
    "solve_banking_window",
]


def __getattr__(name: str) -> object:
    """Lazily resolve this feature's public names on first access (PEP 562).

    Args:
        name: Attribute requested on the ``ets.features.banking`` package.

    Returns:
        The resolved callable.

    Raises:
        AttributeError: ``name`` is not one of this feature's public names.
    """
    if name == "solve_banking_path":
        from .solver import solve_banking_path

        return solve_banking_path
    if name == "solve_banking_window":
        from .window import solve_banking_window

        return solve_banking_window
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
