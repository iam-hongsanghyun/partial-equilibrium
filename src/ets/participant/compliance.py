# Backward-compatibility shim — re-exports from core.participant.compliance.
# New location: src/ets/core/participant/compliance.py.
import warnings

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

warnings.warn(
    "ets.participant.compliance is deprecated; import from "
    "ets.core.participant.compliance instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
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
