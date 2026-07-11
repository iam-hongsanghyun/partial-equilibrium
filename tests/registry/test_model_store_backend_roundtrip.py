"""``pe.model_store`` delegated to the ``StorageBackend`` seam — the
integration layer between ``pe.registry`` and the transport-free registry
I/O every app tier (``pe.web.api``, ``pe.mcp.*``) shares.

Covers:
  (a) ``save_graph_as_model`` persists to BOTH the backend (source of
      truth for ``iter_registry_models``/``resolve_model_config``/
      ``resolve_model_graph``) and the on-disk ``<slug>.json``/
      ``<slug>.graph.json`` mirror (still read directly by
      ``pe.web.api``'s from-template handler).
  (b) save -> list -> resolve -> RUN round-trip: a saved model is runnable
      via ``run_simulation_from_config``, unmodified.
  (c) ``save_config_as_model`` (no composer graph): registered the same
      way, ``resolve_model_graph`` falls back to decompiling the config.
  (d) ``rename_registry_model`` changes the registry id (backend row
      re-keyed, mirror files renamed); the old id is gone.
  (e) ``delete_registry_model`` removes the backend row and mirror files.
  (f) Two different ``registry_dir`` values are fully isolated from each
      other (independent backends) — the mechanism the existing
      ``pe.mcp``/``pe.web.api`` test suites rely on via
      ``monkeypatch.setattr(model_store, "USER_SCENARIOS_DIR", tmp_path)``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pe.blocks import graph_from_config
from pe.config_io import load_config
from pe.engine import run_simulation_from_config
from pe.model_store import (
    ModelStoreError,
    delete_registry_model,
    iter_registry_models,
    rename_registry_model,
    resolve_model_config,
    resolve_model_graph,
    save_config_as_model,
    save_graph_as_model,
)
from pe.registry.config import get_backend_for_directory

# TEST INFRA (not the example library): the canonical minimal competitive
# scenario recovered under tests/fixtures/ as a generic valid config.
MINIMAL_SCENARIO = (
    next(p for p in Path(__file__).resolve().parents if p.name == "tests")
    / "fixtures"
    / "minimal_scenario.json"
)


def _sample_graph():
    config = load_config(MINIMAL_SCENARIO)
    return graph_from_config(config)


# ── (a) backend + file mirror both written ────────────────────────────────


def test_save_graph_as_model_writes_backend_row_and_file_mirror(tmp_path: Path) -> None:
    saved = save_graph_as_model(_sample_graph(), "My Model", registry_dir=tmp_path)

    assert saved.id == "user_my_model"
    assert saved.config_path.exists()
    assert saved.graph_path.exists()

    record = get_backend_for_directory(tmp_path).get_model("my_model")
    assert record is not None
    assert record.name == "My Model"
    assert record.source == "graph"
    assert record.config == saved.config
    assert record.graph == _sample_graph().to_dict()


# ── (b) save -> list -> resolve -> run round trip ─────────────────────────


def test_save_list_resolve_run_round_trip(tmp_path: Path) -> None:
    saved = save_graph_as_model(_sample_graph(), "Roundtrip Model", registry_dir=tmp_path)

    listed = dict(iter_registry_models(registry_dir=tmp_path))
    assert saved.id in listed
    assert listed[saved.id] == saved.config

    resolved_config = resolve_model_config(saved.id, registry_dir=tmp_path)
    assert resolved_config == saved.config

    summary_df, participant_df = run_simulation_from_config(resolved_config)
    assert not summary_df.empty
    assert not participant_df.empty
    assert "Equilibrium Carbon Price" in summary_df.columns


# ── (c) save_config_as_model: no graph, decompile fallback ───────────────


def test_save_config_as_model_falls_back_to_decompiled_graph(tmp_path: Path) -> None:
    config = load_config(MINIMAL_SCENARIO)
    saved = save_config_as_model(config, "Bare Config Model", registry_dir=tmp_path)

    assert saved.id == "user_bare_config_model"
    assert not saved.graph_path.exists(), "no sidecar for a graph-less save"

    record = get_backend_for_directory(tmp_path).get_model("bare_config_model")
    assert record is not None
    assert record.source == "config"
    assert record.graph is None

    graph = resolve_model_graph(saved.id, registry_dir=tmp_path)
    assert graph.to_dict() == graph_from_config(config).to_dict()


# ── (d) rename: id changes, old id gone, mirror files follow ─────────────


def test_rename_registry_model_rekeys_backend_and_mirror(tmp_path: Path) -> None:
    saved = save_graph_as_model(_sample_graph(), "Original Name", registry_dir=tmp_path)

    renamed = rename_registry_model(saved.id, "Renamed Model", registry_dir=tmp_path)

    assert renamed.id == "user_renamed_model"
    assert renamed.config_path.exists()
    assert renamed.graph_path.exists()
    assert not saved.config_path.exists()
    assert not saved.graph_path.exists()

    backend = get_backend_for_directory(tmp_path)
    assert backend.get_model("original_name") is None
    assert backend.get_model("renamed_model") is not None

    with pytest.raises(ModelStoreError, match="Unknown model id"):
        resolve_model_config(saved.id, registry_dir=tmp_path)
    assert resolve_model_config(renamed.id, registry_dir=tmp_path) == renamed.config


def test_rename_registry_model_collision_is_rejected(tmp_path: Path) -> None:
    save_graph_as_model(_sample_graph(), "Model A", registry_dir=tmp_path)
    saved_b = save_graph_as_model(_sample_graph(), "Model B", registry_dir=tmp_path)

    with pytest.raises(ModelStoreError, match="already exists"):
        rename_registry_model(saved_b.id, "Model A", registry_dir=tmp_path)


# ── (e) delete: backend row + mirror files gone ───────────────────────────


def test_delete_registry_model_removes_backend_row_and_files(tmp_path: Path) -> None:
    saved = save_graph_as_model(_sample_graph(), "Doomed Model", registry_dir=tmp_path)

    delete_registry_model(saved.id, registry_dir=tmp_path)

    assert get_backend_for_directory(tmp_path).get_model("doomed_model") is None
    assert not saved.config_path.exists()
    assert not saved.graph_path.exists()
    with pytest.raises(ModelStoreError, match="Unknown model id"):
        resolve_model_config(saved.id, registry_dir=tmp_path)


# ── (f) two registry_dir values are fully isolated ────────────────────────


def test_two_registry_dirs_are_isolated(tmp_path: Path) -> None:
    dir_a = tmp_path / "registry_a"
    dir_b = tmp_path / "registry_b"

    saved_a = save_graph_as_model(_sample_graph(), "Shared Name", registry_dir=dir_a)
    saved_b = save_graph_as_model(_sample_graph(), "Shared Name", registry_dir=dir_b)

    # Same slug, same id string — but two independent backends/db files.
    assert saved_a.id == saved_b.id == "user_shared_name"
    assert (dir_a / "registry.sqlite").exists()
    assert (dir_b / "registry.sqlite").exists()

    delete_registry_model(saved_a.id, registry_dir=dir_a)
    with pytest.raises(ModelStoreError, match="Unknown model id"):
        resolve_model_config(saved_a.id, registry_dir=dir_a)
    # dir_b's copy is untouched by dir_a's delete.
    assert resolve_model_config(saved_b.id, registry_dir=dir_b) == saved_b.config
