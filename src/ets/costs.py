# Backward-compatibility shim — re-exports from core.costs.
# New location: src/ets/core/costs.py.
import warnings

from .core.costs import linear_abatement_factory, piecewise_abatement_factory

warnings.warn(
    "ets.costs is deprecated; import from ets.core.costs instead. "
    "Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "linear_abatement_factory",
    "piecewise_abatement_factory",
]
