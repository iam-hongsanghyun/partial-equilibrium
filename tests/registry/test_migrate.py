"""``pe.registry.migrate.migrate_user_scenarios_to_sqlite`` — backfilling
pre-existing ``<slug>.json``/``<slug>.graph.json`` file pairs (from before
this backend seam existed) into the active ``StorageBackend``.

Covers:
  (a) An empty registry directory migrates nothing.
  (b) A ``<slug>.json`` + ``<slug>.graph.json`` pair (the composer-save
      shape) migrates with ``source="graph"`` and the graph payload intact.
  (c) A config-only file (no sidecar — the legacy raw-scenario-save shape)
      migrates with ``source="config"`` and ``graph=None``.
  (d) Re-running migration is idempotent: same slugs, same row count, no
      duplication (an upsert, not an insert).
  (e) A non-scenario / malformed JSON file in the directory is skipped, not
      fatal to the run.
  (f) End-to-end: after migrating, ``pe.model_store`` resolves and RUNS the
      migrated model via ``run_simulation_from_config`` — proving migration
      doesn't just copy bytes into a table, the result is usable exactly
      like a model ``pe.model_store`` saved directly.
"""

from __future__ import annotations

import json
from pathlib import Path

from pe.blocks import graph_from_config
from pe.config_io import load_config, save_config
from pe.engine import run_simulation_from_config
from pe.model_store import compile_graph_or_raise, resolve_model_config, resolve_model_graph
from pe.registry.config import get_backend_for_directory
from pe.registry.migrate import migrate_user_scenarios_to_sqlite

# TEST INFRA (not the example library): the canonical minimal competitive
# scenario recovered under tests/fixtures/ as a generic valid config.
MINIMAL_SCENARIO = (
    next(p for p in Path(__file__).resolve().parents if p.name == "tests")
    / "fixtures"
    / "minimal_scenario.json"
)


def _sample_graph():
    """A real, valid composer graph decompiled from the minimal test fixture."""
    config = load_config(MINIMAL_SCENARIO)
    return graph_from_config(config)


def _write_pre_backend_model(directory: Path, slug: str, *, with_graph: bool) -> None:
    """Write a ``<slug>.json`` (+ optional ``.graph.json``) pair directly to
    disk, bypassing ``pe.model_store`` entirely — simulating a model saved
    BEFORE this backend seam existed (exactly ``migrate`` exists to backfill).
    """
    graph = _sample_graph()
    config = compile_graph_or_raise(graph)
    directory.mkdir(parents=True, exist_ok=True)
    save_config(config, directory / f"{slug}.json")
    if with_graph:
        (directory / f"{slug}.graph.json").write_text(
            json.dumps(graph.to_dict(), indent=2), encoding="utf-8"
        )


# ── (a) empty directory ───────────────────────────────────────────────────


def test_migrate_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    assert migrate_user_scenarios_to_sqlite(registry_dir=tmp_path) == []


# ── (b) config + graph sidecar ────────────────────────────────────────────


def test_migrate_imports_config_and_graph_sidecar(tmp_path: Path) -> None:
    _write_pre_backend_model(tmp_path, "k_msr", with_graph=True)

    migrated = migrate_user_scenarios_to_sqlite(registry_dir=tmp_path)

    assert migrated == ["k_msr"]
    backend = get_backend_for_directory(tmp_path)
    record = backend.get_model("k_msr")
    assert record is not None
    assert record.source == "graph"
    assert record.graph is not None
    assert record.name == "K Msr"


# ── (c) config-only (no sidecar) ──────────────────────────────────────────


def test_migrate_config_only_file_has_source_config_and_no_graph(tmp_path: Path) -> None:
    _write_pre_backend_model(tmp_path, "legacy_scenario", with_graph=False)

    migrated = migrate_user_scenarios_to_sqlite(registry_dir=tmp_path)

    assert migrated == ["legacy_scenario"]
    record = get_backend_for_directory(tmp_path).get_model("legacy_scenario")
    assert record is not None
    assert record.source == "config"
    assert record.graph is None


# ── (d) idempotent ─────────────────────────────────────────────────────────


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    _write_pre_backend_model(tmp_path, "k_msr", with_graph=True)

    first = migrate_user_scenarios_to_sqlite(registry_dir=tmp_path)
    second = migrate_user_scenarios_to_sqlite(registry_dir=tmp_path)

    assert first == second == ["k_msr"]
    backend = get_backend_for_directory(tmp_path)
    assert [r.id for r in backend.list_models()] == ["k_msr"]


# ── (e) malformed file skipped ─────────────────────────────────────────────


def test_migrate_skips_unparseable_json(tmp_path: Path) -> None:
    _write_pre_backend_model(tmp_path, "good_model", with_graph=False)
    (tmp_path / "not_a_scenario.json").write_text("{not valid json", encoding="utf-8")

    migrated = migrate_user_scenarios_to_sqlite(registry_dir=tmp_path)

    assert migrated == ["good_model"]


# ── (f) end-to-end: migrated model resolves and runs ───────────────────────


def test_migrated_model_resolves_and_runs_via_model_store(tmp_path: Path) -> None:
    _write_pre_backend_model(tmp_path, "k_msr", with_graph=True)
    migrate_user_scenarios_to_sqlite(registry_dir=tmp_path)

    config = resolve_model_config("user_k_msr", registry_dir=tmp_path)
    summary_df, participant_df = run_simulation_from_config(config)
    assert not summary_df.empty
    assert not participant_df.empty

    graph = resolve_model_graph("user_k_msr", registry_dir=tmp_path)
    assert graph.to_dict() == _sample_graph().to_dict()
