# Backward-compatibility shim — re-exports from pe.registry.migrate.
# New location: src/pe/registry/migrate.py.
import warnings

from pe.registry.migrate import migrate_user_scenarios_to_sqlite

warnings.warn(
    "ets.registry.migrate is deprecated; import from pe.registry.migrate "
    "instead. Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "migrate_user_scenarios_to_sqlite",
]
