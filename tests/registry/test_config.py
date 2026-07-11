"""``pe.registry.config`` — environment-driven backend selection.

Covers:
  (a) ``load_registry_config`` defaults to sqlite at
      ``DATABASE_DIR/registry.sqlite`` with no environment overrides.
  (b) ``PE_REGISTRY_DB_PATH`` (relative and absolute) and
      ``PE_REGISTRY_BACKEND=supabase`` are honoured; an unsupported backend
      name raises ``ValueError`` naming the invalid value.
  (c) ``build_backend`` constructs the right concrete type per backend kind.
  (d) ``get_backend_for_directory``: the real ``USER_SCENARIOS_DIR`` routes
      to the configured default backend; any other directory gets its own
      SQLite file at ``<directory>/registry.sqlite``, always SQLite
      regardless of ``PE_REGISTRY_BACKEND``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pe.registry import config as registry_config
from pe.registry.sqlite_backend import SqliteBackend
from pe.registry.supabase_backend import SupabaseBackend


# ── (a) defaults ──────────────────────────────────────────────────────────


def test_load_registry_config_defaults_to_sqlite_at_database_dir(monkeypatch) -> None:
    monkeypatch.delenv(registry_config.ENV_BACKEND, raising=False)
    monkeypatch.delenv(registry_config.ENV_DB_PATH, raising=False)

    cfg = registry_config.load_registry_config()

    assert cfg.backend == "sqlite"
    assert cfg.db_path == registry_config.DEFAULT_DB_PATH
    assert cfg.db_path.name == "registry.sqlite"
    assert cfg.db_path.parent.name == "database"


# ── (b) environment overrides ────────────────────────────────────────────


def test_relative_db_path_resolves_against_project_dir(monkeypatch) -> None:
    monkeypatch.setenv(registry_config.ENV_DB_PATH, "some/nested/registry.sqlite")
    cfg = registry_config.load_registry_config()
    assert cfg.db_path == registry_config.PROJECT_DIR / "some" / "nested" / "registry.sqlite"


def test_absolute_db_path_used_as_is(monkeypatch, tmp_path: Path) -> None:
    absolute = tmp_path / "elsewhere" / "registry.sqlite"
    monkeypatch.setenv(registry_config.ENV_DB_PATH, str(absolute))
    cfg = registry_config.load_registry_config()
    assert cfg.db_path == absolute


def test_backend_supabase_is_honoured(monkeypatch) -> None:
    monkeypatch.setenv(registry_config.ENV_BACKEND, "supabase")
    cfg = registry_config.load_registry_config()
    assert cfg.backend == "supabase"


def test_backend_env_var_is_case_and_whitespace_insensitive(monkeypatch) -> None:
    monkeypatch.setenv(registry_config.ENV_BACKEND, "  SQLite  ")
    cfg = registry_config.load_registry_config()
    assert cfg.backend == "sqlite"


def test_unsupported_backend_raises_value_error(monkeypatch) -> None:
    monkeypatch.setenv(registry_config.ENV_BACKEND, "mongo")
    with pytest.raises(ValueError, match="mongo"):
        registry_config.load_registry_config()


# ── (c) build_backend dispatch ────────────────────────────────────────────


def test_build_backend_sqlite(tmp_path: Path) -> None:
    cfg = registry_config.RegistryConfig(backend="sqlite", db_path=tmp_path / "registry.sqlite")
    backend = registry_config.build_backend(cfg)
    assert isinstance(backend, SqliteBackend)
    assert backend.db_path == cfg.db_path


def test_build_backend_supabase(monkeypatch) -> None:
    monkeypatch.setenv(registry_config.ENV_SUPABASE_URL, "https://example.supabase.co")
    monkeypatch.setenv(registry_config.ENV_SUPABASE_KEY, "test-key")
    cfg = registry_config.RegistryConfig(backend="supabase", db_path=Path("/unused"))
    backend = registry_config.build_backend(cfg)
    assert isinstance(backend, SupabaseBackend)
    with pytest.raises(NotImplementedError):
        backend.list_models()


# ── (d) get_backend_for_directory: default vs. override ──────────────────


def test_get_backend_for_directory_default_uses_configured_backend(
    monkeypatch, tmp_path: Path
) -> None:
    configured_path = tmp_path / "configured" / "registry.sqlite"
    monkeypatch.setenv(registry_config.ENV_DB_PATH, str(configured_path))
    monkeypatch.setattr(registry_config, "USER_SCENARIOS_DIR", tmp_path / "user-scenarios")

    backend = registry_config.get_backend_for_directory(tmp_path / "user-scenarios")

    assert isinstance(backend, SqliteBackend)
    assert backend.db_path == configured_path


def test_get_backend_for_directory_override_gets_its_own_sqlite_file(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(registry_config, "USER_SCENARIOS_DIR", tmp_path / "production-only")
    override_dir = tmp_path / "isolated-test-registry"

    backend = registry_config.get_backend_for_directory(override_dir)

    assert isinstance(backend, SqliteBackend)
    assert backend.db_path == override_dir / "registry.sqlite"


def test_get_backend_for_directory_override_is_always_sqlite_even_if_supabase_configured(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(registry_config.ENV_BACKEND, "supabase")
    monkeypatch.setattr(registry_config, "USER_SCENARIOS_DIR", tmp_path / "production-only")

    backend = registry_config.get_backend_for_directory(tmp_path / "override")

    assert isinstance(backend, SqliteBackend)
