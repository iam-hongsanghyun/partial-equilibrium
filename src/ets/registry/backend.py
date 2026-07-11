# Backward-compatibility shim — re-exports from pe.registry.backend.
# New location: src/pe/registry/backend.py.
import warnings

from pe.registry.backend import ModelRecord, StorageBackend

warnings.warn(
    "ets.registry.backend is deprecated; import from pe.registry.backend "
    "instead. Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ModelRecord",
    "StorageBackend",
]
