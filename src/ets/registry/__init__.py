# Backward-compatibility shim package — re-exports from pe.registry.
# New location: src/pe/registry/.
import warnings

from pe.registry import (
    ModelRecord,
    RegistryConfig,
    SqliteBackend,
    StorageBackend,
    SupabaseBackend,
    get_backend_for_directory,
    get_default_backend,
    load_registry_config,
)

warnings.warn(
    "ets.registry is deprecated; import from pe.registry instead. "
    "Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ModelRecord",
    "StorageBackend",
    "RegistryConfig",
    "get_backend_for_directory",
    "get_default_backend",
    "load_registry_config",
    "SqliteBackend",
    "SupabaseBackend",
]
