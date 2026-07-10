# Backward-compatibility shim — re-exports from core.participant.technology.
# New location: src/ets/core/participant/technology.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.participant.technology import (
    _default_technology,
    _available_technologies,
)

__all__ = [
    "_default_technology",
    "_available_technologies",
]
