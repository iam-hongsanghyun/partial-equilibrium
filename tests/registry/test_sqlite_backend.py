"""``SqliteBackend`` round-trip tests: save/get/list/rename/delete, plus the
storage guarantees ``pe.model_store`` relies on (WAL mode, upsert timestamp
semantics, the ``database/`` default location).

Covers:
  (a) save -> get round-trips every field, including a ``None`` graph.
  (b) A second ``save_model`` for the same id upserts: fields change,
      ``created_at`` is preserved, ``updated_at`` never goes backwards.
  (c) ``list_models`` returns every row, ordered deterministically by id.
  (d) ``get_model``/``rename_model``/``delete_model`` on a missing id:
      ``get_model`` returns ``None``; the mutators raise ``KeyError``.
  (e) The db file is created (with its parent directory) at construction,
      and WAL journal mode is active.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pe.registry.sqlite_backend import SqliteBackend


@pytest.fixture
def backend(tmp_path: Path) -> SqliteBackend:
    return SqliteBackend(tmp_path / "nested" / "registry.sqlite")


# ── (a) save -> get round trip ───────────────────────────────────────────


def test_save_then_get_round_trips_every_field(backend: SqliteBackend) -> None:
    record = backend.save_model(
        "k_msr",
        "K-MSR",
        {"scenarios": [{"name": "K-MSR"}]},
        {"nodes": [], "edges": [], "version": 1},
        source="graph",
        domain=None,
    )
    assert record.id == "k_msr"
    assert record.name == "K-MSR"
    assert record.config == {"scenarios": [{"name": "K-MSR"}]}
    assert record.graph == {"nodes": [], "edges": [], "version": 1}
    assert record.source == "graph"
    assert record.domain is None
    assert record.created_at == record.updated_at

    fetched = backend.get_model("k_msr")
    assert fetched == record


def test_save_with_no_graph_round_trips_none(backend: SqliteBackend) -> None:
    record = backend.save_model(
        "legacy", "Legacy", {"scenarios": []}, None, source="config", domain="ets"
    )
    assert record.graph is None
    assert record.domain == "ets"
    assert backend.get_model("legacy") == record


# ── (b) upsert: created_at preserved, fields updated ─────────────────────


def test_second_save_upserts_preserving_created_at(backend: SqliteBackend) -> None:
    first = backend.save_model("m1", "First Name", {"scenarios": [1]}, None, source="config")
    second = backend.save_model(
        "m1", "Second Name", {"scenarios": [2]}, {"nodes": []}, source="graph", domain="x"
    )

    assert second.created_at == first.created_at, "created_at must survive an upsert"
    assert second.updated_at >= first.updated_at, "updated_at is monotone (ISO-8601 sorts lexically)"
    assert second.name == "Second Name"
    assert second.config == {"scenarios": [2]}
    assert second.graph == {"nodes": []}
    assert second.domain == "x"

    # And it's really one row, not two.
    assert [r.id for r in backend.list_models()] == ["m1"]


# ── (c) list_models: every row, id-ordered ───────────────────────────────


def test_list_models_returns_every_row_ordered_by_id(backend: SqliteBackend) -> None:
    for slug in ("zeta", "alpha", "mu"):
        backend.save_model(slug, slug.title(), {"scenarios": []}, None, source="config")

    ids = [record.id for record in backend.list_models()]
    assert ids == ["alpha", "mu", "zeta"]


def test_list_models_empty_backend_returns_empty_list(backend: SqliteBackend) -> None:
    assert backend.list_models() == []


# ── (d) missing-id semantics ──────────────────────────────────────────────


def test_get_model_missing_returns_none(backend: SqliteBackend) -> None:
    assert backend.get_model("does-not-exist") is None


def test_rename_model_missing_raises_keyerror(backend: SqliteBackend) -> None:
    with pytest.raises(KeyError):
        backend.rename_model("does-not-exist", "New Name")


def test_delete_model_missing_raises_keyerror(backend: SqliteBackend) -> None:
    with pytest.raises(KeyError):
        backend.delete_model("does-not-exist")


def test_rename_model_updates_name_keeps_id(backend: SqliteBackend) -> None:
    backend.save_model("k1", "Old Name", {"scenarios": []}, None, source="config")
    renamed = backend.rename_model("k1", "New Name")
    assert renamed.id == "k1"
    assert renamed.name == "New Name"
    assert backend.get_model("k1").name == "New Name"  # type: ignore[union-attr]


def test_delete_model_removes_the_row(backend: SqliteBackend) -> None:
    backend.save_model("k1", "K1", {"scenarios": []}, None, source="config")
    backend.delete_model("k1")
    assert backend.get_model("k1") is None
    assert backend.list_models() == []


# ── (e) db file creation + WAL mode ───────────────────────────────────────


def test_db_file_and_parent_directory_created_on_construction(tmp_path: Path) -> None:
    db_path = tmp_path / "database" / "registry.sqlite"
    assert not db_path.exists()
    SqliteBackend(db_path)
    assert db_path.exists()
    assert db_path.parent.name == "database"


def test_journal_mode_is_wal(backend: SqliteBackend) -> None:
    with backend._connection() as conn:  # noqa: SLF001 — WAL mode is an implementation guarantee this test asserts directly
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()
    assert mode.lower() == "wal"
