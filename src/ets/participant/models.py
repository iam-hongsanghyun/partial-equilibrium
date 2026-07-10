# Backward-compatibility shim — re-exports from core.participant.models.
# New location: src/ets/core/participant/models.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.participant.models import (
    CostSpec,
    TechnologyOption,
    ComplianceOutcome,
    MarketParticipant,
)

__all__ = [
    "CostSpec",
    "TechnologyOption",
    "ComplianceOutcome",
    "MarketParticipant",
]
