# Backward-compatibility shim — re-exports from core.participant.compliance.
# New location: src/ets/core/participant/compliance.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.participant.compliance import (
    optimize_compliance,
    _scale_for_activity,
    _abatement_cost,
    _finalize_inventory,
    _total_compliance_cost,
    _optimize_for_technology,
    _optimize_mixed_technology_portfolio,
    _default_technology,
)

__all__ = [
    "optimize_compliance",
    "_scale_for_activity",
    "_abatement_cost",
    "_finalize_inventory",
    "_total_compliance_cost",
    "_optimize_for_technology",
    "_optimize_mixed_technology_portfolio",
    "_default_technology",
]
