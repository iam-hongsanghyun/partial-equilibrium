# Backward-compatibility shim package — re-exports from core.participant.
# New location: src/ets/core/participant/.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.participant import (
    MarketParticipant,
    TechnologyOption,
    ComplianceOutcome,
    CostSpec,
)

__all__ = [
    "MarketParticipant",
    "TechnologyOption",
    "ComplianceOutcome",
    "CostSpec",
]
