# Backward-compatibility shim — re-exports from core.participant.technology.
# New location: src/ets/core/participant/technology.py.
import warnings

from ..core.participant.technology import (
    _default_technology,
    _available_technologies,
)

warnings.warn(
    "ets.participant.technology is deprecated; import from "
    "ets.core.participant.technology instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "_default_technology",
    "_available_technologies",
]
