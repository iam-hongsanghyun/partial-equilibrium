# Backward-compatibility shim package — re-exports from core.market.
# New location: src/ets/core/market/ (core.py -> model.py,
# equilibrium.py -> clearing.py, results.py -> reporting.py).
# Importing this package imports core.market, which performs the
# CarbonMarket method attachment exactly as before the move.
import warnings

from ..core.market import CarbonMarket

warnings.warn(
    "ets.market is deprecated; import from ets.core.market instead. "
    "Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["CarbonMarket"]
