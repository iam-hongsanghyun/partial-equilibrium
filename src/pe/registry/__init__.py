"""The model-registry storage-backend seam.

``pe.model_store`` (the transport-free scenario-registry I/O every app tier
shares — ``pe.web.api``, ``pe.mcp.*``) delegates USER-model persistence to
whichever :class:`~pe.registry.backend.StorageBackend` is active here.
Bundled ``examples/*.json`` never come through this package — they stay
read-only files resolved directly by ``pe.model_store`` (see that module's
docstring).

Public surface:

* :class:`~pe.registry.backend.StorageBackend` — the Protocol every adapter
  implements; :class:`~pe.registry.backend.ModelRecord` — its wire type.
* :class:`~pe.registry.sqlite_backend.SqliteBackend` — the default,
  stdlib-``sqlite3`` implementation.
* :class:`~pe.registry.supabase_backend.SupabaseBackend` — an
  interface-only stub sketching a future hosted-Postgres implementation.
* :func:`~pe.registry.config.load_registry_config`,
  :func:`~pe.registry.config.get_default_backend`,
  :func:`~pe.registry.config.get_backend_for_directory` — environment-driven
  backend selection (``PE_REGISTRY_BACKEND``/``PE_REGISTRY_DB_PATH``, see
  ``.env.example``).
* ``pe.registry.migrate.migrate_user_scenarios_to_sqlite`` — one-time
  backfill of pre-existing ``user-scenarios/*.json`` files; also runnable
  as ``python -m pe.registry.migrate``. Deliberately NOT re-exported here:
  eagerly importing ``.migrate`` from this ``__init__`` would make ``python
  -m pe.registry.migrate`` re-execute an already-imported module as
  ``__main__`` (a spurious ``RuntimeWarning`` from ``runpy``) — import it
  directly, ``from pe.registry.migrate import
  migrate_user_scenarios_to_sqlite``.
"""

from __future__ import annotations

from .backend import ModelRecord, StorageBackend
from .config import (
    RegistryConfig,
    get_backend_for_directory,
    get_default_backend,
    load_registry_config,
)
from .sqlite_backend import SqliteBackend
from .supabase_backend import SupabaseBackend

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
