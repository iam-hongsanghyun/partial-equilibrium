# Backward-compatibility shim — re-exports from core.costs.
# New location: src/ets/core/costs.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from .core.costs import linear_abatement_factory, piecewise_abatement_factory

__all__ = [
    "linear_abatement_factory",
    "piecewise_abatement_factory",
]
