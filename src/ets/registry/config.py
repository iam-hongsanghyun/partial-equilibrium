# Backward-compatibility shim — re-exports from pe.registry.config.
# New location: src/pe/registry/config.py.
import warnings

from pe.registry.config import (
    DEFAULT_BACKEND,
    DEFAULT_DB_PATH,
    ENV_BACKEND,
    ENV_DB_PATH,
    ENV_SUPABASE_KEY,
    ENV_SUPABASE_URL,
    SUPPORTED_BACKENDS,
    RegistryConfig,
    build_backend,
    get_backend_for_directory,
    get_default_backend,
    load_registry_config,
)

warnings.warn(
    "ets.registry.config is deprecated; import from pe.registry.config "
    "instead. Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ENV_BACKEND",
    "ENV_DB_PATH",
    "ENV_SUPABASE_URL",
    "ENV_SUPABASE_KEY",
    "SUPPORTED_BACKENDS",
    "DEFAULT_BACKEND",
    "DEFAULT_DB_PATH",
    "RegistryConfig",
    "load_registry_config",
    "build_backend",
    "get_default_backend",
    "get_backend_for_directory",
]
