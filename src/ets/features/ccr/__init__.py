"""CCR feature (T2) — the Benmir-Roman-Taschini carbon cap rule.

Two-door layout (``docs/feature-modules-plan.md`` PLAN v2): ``plugin.py`` is
the config door (summary-placeholder reporter); the runtime modules are
``state.py`` (``CCRState``) and ``rules.py`` (``CCRCapRule``) — moved from
``solvers/ccr.py`` in the engine work order (v1 O8 / v2 O12) and wired
exclusively by ``ets.engine``. ``ets/solvers/ccr.py`` remains as a
re-export shim.

This ``__init__`` is the feature's deliberate public surface, resolved
LAZILY (PEP 562 ``__getattr__``): ``ets.config_io`` imports this feature's
``plugin`` door unconditionally (the two-door contract), and importing ANY
submodule of a package always runs that package's ``__init__.py`` first —
so an eager ``rules``/``state`` import here would force-load the CCR
RUNTIME for every scenario, CCR-enabled or not. Attribute access still
returns the same objects; only the import TIMING moves to first use (lazy,
per-model feature activation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rules import CCRCapRule as CCRCapRule
    from .state import CCRState as CCRState

__all__ = [
    "CCRCapRule",
    "CCRState",
]


def __getattr__(name: str) -> object:
    """Lazily resolve this feature's public names on first access (PEP 562).

    Args:
        name: Attribute requested on the ``ets.features.ccr`` package.

    Returns:
        The resolved class.

    Raises:
        AttributeError: ``name`` is not one of this feature's public names.
    """
    if name == "CCRCapRule":
        from .rules import CCRCapRule

        return CCRCapRule
    if name == "CCRState":
        from .state import CCRState

        return CCRState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
