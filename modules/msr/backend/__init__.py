"""MSR feature (T2) — Market Stability Reserve state, rules, and decree.

Two-door layout (``docs/feature-modules-plan.md`` PLAN v2): ``plugin.py`` is
the config door (summary-placeholder reporter + the ``RESERVE_CARRIER``
splice declaration); the runtime modules are ``state.py`` (``MSRState``),
``rules.py`` (``MSRCapRule``, ``ThresholdMSRSupplyRule``), and ``decree.py``
(``decree_msr_action``, ``DecreeSupplyRule``) — moved from ``solvers/msr.py``
in the engine work order (v1 O8 / v2 O12) and wired exclusively by
``ets.engine``. ``ets/solvers/msr.py`` remains as a re-export shim.

This ``__init__`` is the feature's deliberate public surface, resolved
LAZILY (PEP 562 ``__getattr__``): ``ets.config_io`` imports this feature's
``plugin`` door unconditionally (the two-door contract), and importing ANY
submodule of a package always runs that package's ``__init__.py`` first —
so an eager ``rules``/``decree``/``state`` import here would force-load the
MSR RUNTIME for every scenario, MSR-enabled or not. Attribute access still
returns the same objects; only the import TIMING moves to first use (lazy,
per-model feature activation).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .decree import (
        DecreeSupplyRule as DecreeSupplyRule,
        decree_msr_action as decree_msr_action,
    )
    from .rules import (
        MSRCapRule as MSRCapRule,
        ThresholdMSRSupplyRule as ThresholdMSRSupplyRule,
    )
    from .state import MSRState as MSRState

__all__ = [
    "DecreeSupplyRule",
    "MSRCapRule",
    "MSRState",
    "ThresholdMSRSupplyRule",
    "decree_msr_action",
]


def __getattr__(name: str) -> object:
    """Lazily resolve this feature's public names on first access (PEP 562).

    Args:
        name: Attribute requested on the ``ets.features.msr`` package.

    Returns:
        The resolved class or function.

    Raises:
        AttributeError: ``name`` is not one of this feature's public names.
    """
    if name in {"DecreeSupplyRule", "decree_msr_action"}:
        from . import decree

        return getattr(decree, name)
    if name in {"MSRCapRule", "ThresholdMSRSupplyRule"}:
        from . import rules

        return getattr(rules, name)
    if name == "MSRState":
        from .state import MSRState

        return MSRState
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
