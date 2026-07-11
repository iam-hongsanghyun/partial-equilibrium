"""MCP models (governor) server tests.

Exercises the tool FUNCTIONS directly (``pe.mcp.models_tools``) — no MCP
transport involved for most cases, mirroring
``tests/apps/mcp/test_mcp_composer.py``. Covers:

  (a) ``list_models``/``describe_model`` on a model saved through the
      composer's ``save_model`` into a tmp registry (monkeypatched
      ``USER_SCENARIOS_DIR``, same pattern as the composer tests).
  (b) ``run_model`` compact shape on a bundled example
      (``climate_solutions_basic_linear``).
  (c) ``compare_models`` on two fast, same-year-grid examples: aligned
      years, deterministic model-id ordering, and the >4-models rejection.
  (d) ``sweep_model`` on a dotted config path with 2 values, plus the
      empty/>8-values guards.
  (e) ``rename_model``/``delete_model`` guards: an example id is rejected
      (immutable), a registry id round-trips (rename re-slugs, delete
      removes both files).
  (f) One in-process MCP protocol smoke test over the SDK's in-memory
      transport: the server starts and lists all 8 tools.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pe import model_store
from pe.mcp import models_tools, tools

# TEST INFRA (not the example library): drive the models-governor tools off the
# recovered minimal scenarios under tests/fixtures/ by pointing model_store's
# example root at that directory. The two example ids below are the fixture
# stems (minimal_scenario == the deleted climate_solutions_basic_linear;
# minimal_auction_scenario == the deleted climate_solutions_auction_controls).
FIXTURES_DIR = next(p for p in Path(__file__).resolve().parents if p.name == "tests") / "fixtures"

_BASIC_LINEAR = "minimal_scenario"
_AUCTION_CONTROLS = "minimal_auction_scenario"


@pytest.fixture(autouse=True)
def _use_fixture_examples(monkeypatch) -> None:
    """Point ``model_store.EXAMPLES_DIR`` at ``tests/fixtures/`` for every case.

    The tools resolve example ids through ``model_store`` (module-global
    ``EXAMPLES_DIR``); with the real example library empty, only the recovered
    fixtures stand in for bundled examples.
    """
    monkeypatch.setattr(model_store, "EXAMPLES_DIR", FIXTURES_DIR)


# ── (a) list_models / describe_model on a saved model ────────────────────


def test_list_and_describe_model_on_a_saved_registry_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "USER_SCENARIOS_DIR", tmp_path)

    graph = tools.new_graph()["graph"]
    saved = tools.save_model(graph, "My Saved Model")

    listed = models_tools.list_models()
    registry_entry = next(m for m in listed["models"] if m["id"] == saved["id"])
    assert registry_entry["source"] == "registry"
    assert registry_entry["name"] == "My Saved Model"
    assert "core" in registry_entry["features"]

    described = models_tools.describe_model(saved["id"])
    assert described["id"] == saved["id"]
    assert described["source"] == "registry"
    assert described["scenarios"] == ["New Model"]
    assert described["years"] == {"start": "2026", "end": "2026", "count": 1}
    assert described["participants"] == ["Participant 1"]
    assert described["mechanisms"] == {"price_formation": ["competitive_clearing"]}


def test_describe_model_on_example_reports_manifest_and_span() -> None:
    described = models_tools.describe_model(_BASIC_LINEAR)
    assert described["id"] == _BASIC_LINEAR
    assert described["source"] == "example"
    assert described["scenarios"] == ["Climate Solutions Basic Linear"]
    assert described["years"]["start"] == "2025"
    assert described["years"]["end"] == "2050"
    assert described["years"]["count"] == 6
    assert "Steel_BlastFurnace" in described["participants"]
    assert "price_formation" in described["mechanisms"]


def test_describe_model_unknown_id_raises() -> None:
    with pytest.raises(model_store.ModelStoreError, match="Unknown model id"):
        models_tools.describe_model("not_a_real_model")


def test_model_manifest_is_raw_derive_manifest_passthrough() -> None:
    from pe.blocks import derive_manifest
    from pe.config_io import load_config

    expected = derive_manifest(load_config(FIXTURES_DIR / f"{_BASIC_LINEAR}.json"))
    assert models_tools.model_manifest(_BASIC_LINEAR) == expected


# ── (b) run_model compact shape on a bundled example ─────────────────────


def test_run_model_on_example_returns_compact_summary() -> None:
    result = models_tools.run_model(_BASIC_LINEAR)

    assert result["ok"] is True
    assert result["model_id"] == _BASIC_LINEAR
    scenario = result["scenarios"]["Climate Solutions Basic Linear"]
    assert scenario["total_years"] == 6
    assert scenario["truncated"] is False
    first_year = scenario["years"][0]
    assert first_year["year"] == "2025"
    assert isinstance(first_year["price"], float)
    assert first_year["price"] >= 0.0


def test_run_model_unknown_id_raises() -> None:
    with pytest.raises(model_store.ModelStoreError, match="Unknown model id"):
        models_tools.run_model("not_a_real_model")


def test_run_model_unknown_scenario_raises() -> None:
    with pytest.raises(ValueError, match="Unknown scenario"):
        models_tools.run_model(_BASIC_LINEAR, scenario="Does Not Exist")


# ── (c) compare_models: aligned years, deterministic order, >4 rejected ──


def test_compare_models_aligns_years_and_orders_deterministically() -> None:
    result = models_tools.compare_models([_BASIC_LINEAR, _AUCTION_CONTROLS])

    assert result["model_ids"] == [_BASIC_LINEAR, _AUCTION_CONTROLS]
    assert result["scenario"] == {
        _BASIC_LINEAR: "Climate Solutions Basic Linear",
        _AUCTION_CONTROLS: "Climate Solutions Auction Controls",
    }

    years = [row["year"] for row in result["years"]]
    assert years == ["2025", "2030", "2035", "2040", "2045", "2050"]
    for row in result["years"]:
        assert set(row.keys()) == {"year", _BASIC_LINEAR, _AUCTION_CONTROLS}
        for model_id in result["model_ids"]:
            assert isinstance(row[model_id]["price"], float)

    assert "price_delta_min" in result["summary"]
    assert "price_delta_max" in result["summary"]
    assert result["summary"]["price_delta_max"] >= result["summary"]["price_delta_min"] >= 0.0


def test_compare_models_rejects_more_than_four() -> None:
    with pytest.raises(ValueError, match="at most 4"):
        models_tools.compare_models(
            [
                _BASIC_LINEAR,
                _AUCTION_CONTROLS,
                "climate_solutions_mac_pathway",
                "climate_solutions_cbam_exposure",
                "climate_solutions_technology_switching",
            ]
        )


def test_compare_models_rejects_fewer_than_two() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        models_tools.compare_models([_BASIC_LINEAR])


def test_compare_models_multi_scenario_model_needs_scenario_kwarg() -> None:
    with pytest.raises(ValueError, match="scenario="):
        models_tools.compare_models([_BASIC_LINEAR, "minimal_msr_scenario"])


# ── (d) sweep_model ────────────────────────────────────────────────────────


def test_sweep_model_two_values_returns_headline_results() -> None:
    result = models_tools.sweep_model(
        _BASIC_LINEAR, "scenarios[0].years[*].total_cap", [500.0, 600.0]
    )

    assert result["model_id"] == _BASIC_LINEAR
    assert result["parameter_path"] == "scenarios[0].years[*].total_cap"
    assert result["n_runs"] == 2
    assert result["n_errors"] == 0
    assert len(result["runs"]) == 2
    for run in result["runs"]:
        assert run["error"] is None
        assert run["final_year"] == "2050"
        assert isinstance(run["final_price"], float)
        assert isinstance(run["cumulative_abatement"], float)


def test_sweep_model_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="at least one"):
        models_tools.sweep_model(_BASIC_LINEAR, "scenarios[0].years[*].total_cap", [])


def test_sweep_model_rejects_more_than_eight_values() -> None:
    with pytest.raises(ValueError, match="at most 8"):
        models_tools.sweep_model(_BASIC_LINEAR, "scenarios[0].years[*].total_cap", list(range(9)))


# ── (e) rename_model / delete_model guards ────────────────────────────────


def test_rename_and_delete_example_id_rejected() -> None:
    with pytest.raises(model_store.ModelStoreError, match="registry model id"):
        models_tools.rename_model(_BASIC_LINEAR, "New Name")
    with pytest.raises(model_store.ModelStoreError, match="registry model id"):
        models_tools.delete_model(_BASIC_LINEAR)


def test_rename_and_delete_registry_model_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "USER_SCENARIOS_DIR", tmp_path)

    graph = tools.new_graph()["graph"]
    saved = tools.save_model(graph, "Original Name")
    assert saved["id"] == "user_original_name"

    renamed = models_tools.rename_model(saved["id"], "Renamed Model")
    assert renamed["id"] == "user_renamed_model"
    assert renamed["name"] == "Renamed Model"

    # Old id is gone, new id resolves and still runs.
    with pytest.raises(model_store.ModelStoreError, match="Unknown model id"):
        models_tools.describe_model(saved["id"])
    reopened = models_tools.describe_model(renamed["id"])
    assert reopened["id"] == renamed["id"]

    models_tools.delete_model(renamed["id"])
    with pytest.raises(model_store.ModelStoreError, match="Unknown model id"):
        models_tools.describe_model(renamed["id"])
    assert not (tmp_path / "renamed_model.json").exists()
    assert not (tmp_path / "renamed_model.graph.json").exists()


def test_rename_model_empty_name_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "USER_SCENARIOS_DIR", tmp_path)
    graph = tools.new_graph()["graph"]
    saved = tools.save_model(graph, "Some Model")
    with pytest.raises(model_store.ModelStoreError):
        models_tools.rename_model(saved["id"], "   ")


# ── (f) in-process MCP protocol smoke test (in-memory transport) ─────────


def test_mcp_models_server_lists_all_tools_over_memory_transport() -> None:
    mcp_client = pytest.importorskip("mcp.shared.memory")
    from pe.mcp.models_server import mcp as server

    async def _run() -> None:
        async with mcp_client.create_connected_server_and_client_session(server) as session:
            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            assert names == {
                "list_models",
                "describe_model",
                "run_model",
                "compare_models",
                "sweep_model",
                "rename_model",
                "delete_model",
                "model_manifest",
            }

            result = await session.call_tool("list_models", {})
            assert result.isError is False

    asyncio.run(_run())
