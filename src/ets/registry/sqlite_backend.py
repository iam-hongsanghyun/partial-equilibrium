# Backward-compatibility shim — re-exports from pe.registry.sqlite_backend.
# New location: src/pe/registry/sqlite_backend.py.
import warnings

from pe.registry.sqlite_backend import SqliteBackend

warnings.warn(
    "ets.registry.sqlite_backend is deprecated; import from "
    "pe.registry.sqlite_backend instead. Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "SqliteBackend",
]
