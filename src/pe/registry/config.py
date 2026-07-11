"""Environment-driven selection of the active model-registry ``StorageBackend``.

Follows this repo's "load via ``src/<pkg>/config.py`` from ``.env``"
convention (``CLAUDE.md``) for the one thing about the registry that is
genuinely a deployment choice — which storage adapter is active — while
filesystem LOCATIONS stay in ``pe.core.paths`` (``DATABASE_DIR``), exactly
like every other path constant in this codebase (``USER_SCENARIOS_DIR``,
``EXAMPLES_DIR``, ...). Every environment variable read here is mirrored in
``.env.example`` at the project root.

No caching: :func:`build_backend` constructs a fresh backend instance on
every call. Both implementations are cheap to construct — ``SqliteBackend``
only opens a connection to run ``CREATE TABLE IF NOT EXISTS`` and closes it
again — and skipping a cache sidesteps a real correctness hazard: a cached
singleton keyed by nothing would silently ignore a ``PE_REGISTRY_DB_PATH``
change between calls (e.g. across tests that monkeypatch the environment).
``pe.model_store`` is the one caller that's on any kind of hot path, and it
only calls this a handful of times per request, never inside a solver loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..core.paths import DATABASE_DIR, PROJECT_DIR, USER_SCENARIOS_DIR
from .backend import StorageBackend
from .sqlite_backend import SqliteBackend
from .supabase_backend import SupabaseBackend

ENV_BACKEND = "PE_REGISTRY_BACKEND"
ENV_DB_PATH = "PE_REGISTRY_DB_PATH"
ENV_SUPABASE_URL = "PE_SUPABASE_URL"
ENV_SUPABASE_KEY = "PE_SUPABASE_KEY"

SUPPORTED_BACKENDS: tuple[str, ...] = ("sqlite", "supabase")
DEFAULT_BACKEND = "sqlite"
DEFAULT_DB_PATH = DATABASE_DIR / "registry.sqlite"


@dataclass(frozen=True)
class RegistryConfig:
    """The active backend kind, plus (for ``"sqlite"``) its db file location.

    Args:
        backend: One of :data:`SUPPORTED_BACKENDS`.
        db_path: Where the SQLite registry file lives. Only meaningful when
            ``backend == "sqlite"``; ignored for ``"supabase"`` (that
            backend is addressed by URL/key, not a filesystem path).
    """

    backend: str
    db_path: Path


def load_registry_config() -> RegistryConfig:
    """Read ``PE_REGISTRY_BACKEND``/``PE_REGISTRY_DB_PATH`` from the environment.

    Returns:
        ``RegistryConfig(backend="sqlite", db_path=DATABASE_DIR/"registry.sqlite")``
        unless overridden. A relative ``PE_REGISTRY_DB_PATH`` resolves
        against ``pe.core.paths.PROJECT_DIR`` (mirroring how
        ``USER_SCENARIOS_DIR``/``EXAMPLES_DIR`` are always project-relative).

    Raises:
        ValueError: ``PE_REGISTRY_BACKEND`` is set to anything outside
            :data:`SUPPORTED_BACKENDS`.
    """
    backend = os.environ.get(ENV_BACKEND, DEFAULT_BACKEND).strip().lower() or DEFAULT_BACKEND
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"{ENV_BACKEND}={backend!r} is not a supported registry backend "
            f"(expected one of {SUPPORTED_BACKENDS})."
        )

    raw_db_path = os.environ.get(ENV_DB_PATH, "").strip()
    if raw_db_path:
        candidate = Path(raw_db_path)
        db_path = candidate if candidate.is_absolute() else PROJECT_DIR / candidate
    else:
        db_path = DEFAULT_DB_PATH
    return RegistryConfig(backend=backend, db_path=db_path)


def build_backend(config: RegistryConfig) -> StorageBackend:
    """Construct the :class:`~pe.registry.backend.StorageBackend` a config names.

    Args:
        config: Typically :func:`load_registry_config`'s result.

    Returns:
        A fresh backend instance — see module docstring for why this is
        never cached.

    Raises:
        ValueError: ``config.backend`` is outside :data:`SUPPORTED_BACKENDS`
            (unreachable via :func:`load_registry_config`, which already
            validates; guards direct/hand-built ``RegistryConfig`` callers).
    """
    if config.backend == "sqlite":
        return SqliteBackend(config.db_path)
    if config.backend == "supabase":
        return SupabaseBackend(
            url=os.environ.get(ENV_SUPABASE_URL),
            key=os.environ.get(ENV_SUPABASE_KEY),
        )
    raise ValueError(f"Unknown registry backend {config.backend!r}.")


def get_default_backend() -> StorageBackend:
    """The env-configured production backend: :func:`load_registry_config` + :func:`build_backend`."""
    return build_backend(load_registry_config())


def get_backend_for_directory(directory: Path) -> StorageBackend:
    """Resolve the :class:`~pe.registry.backend.StorageBackend` serving ``directory``.

    ``pe.model_store``'s public functions all accept a ``registry_dir``
    override (default ``pe.core.paths.USER_SCENARIOS_DIR``) — a convention
    that predates this backend seam, kept for backward compatibility (tests
    isolate their registry state by pointing ``registry_dir`` at a fresh
    ``tmp_path``, or by monkeypatching ``USER_SCENARIOS_DIR`` itself). This
    function is what lets that convention keep working under a
    backend-delegated registry:

    * ``directory == pe.core.paths.USER_SCENARIOS_DIR`` (the real,
      never-monkeypatched production constant) resolves to the
      env-configured backend (:func:`get_default_backend`) — production
      default: ``database/registry.sqlite``.
    * Any OTHER directory (an explicit ``registry_dir=`` override, or a
      caller module's own ``USER_SCENARIOS_DIR`` name monkeypatched to a
      ``tmp_path``) gets its own, independent SQLite file at
      ``<directory>/registry.sqlite`` — mirroring the pre-refactor
      one-JSON-file-per-model behaviour, where a different ``registry_dir``
      already meant a completely separate on-disk registry. Always SQLite
      here (never Supabase), regardless of ``PE_REGISTRY_BACKEND`` — an
      override exists for test/alternate-registry isolation, not
      production deployment, and must not require network access.

    Args:
        directory: The resolved ``registry_dir`` (never ``None`` — callers
            have already substituted the default).

    Returns:
        The backend instance to use for this directory.
    """
    if directory == USER_SCENARIOS_DIR:
        return get_default_backend()
    return SqliteBackend(directory / "registry.sqlite")
