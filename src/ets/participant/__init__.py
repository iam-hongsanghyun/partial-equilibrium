# Backward-compatibility shim package — re-exports from core.participant.
# New location: src/ets/core/participant/.
import warnings

from ..core.participant import (
    MarketParticipant,
    TechnologyOption,
    ComplianceOutcome,
    CostSpec,
)

warnings.warn(
    "ets.participant is deprecated; import from ets.core.participant "
    "instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "MarketParticipant",
    "TechnologyOption",
    "ComplianceOutcome",
    "CostSpec",
]
