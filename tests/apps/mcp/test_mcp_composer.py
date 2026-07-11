"""MCP composer server tests.

Exercises the tool FUNCTIONS directly (``pe.mcp.tools``) — no MCP transport
involved for most cases, mirroring how ``tests/apps/web/test_web_graph_api.py``
drives the WSGI app in-process. Covers:

  (a) ``new_graph()``'s blank skeleton is already ``check()``-clean.
  (b) ``add_block(msr_bank_threshold)`` on a competitive graph yields the
      R6-driven ``next_steps``; applying the suggestion (banking_allowed +
      a non-myopic expectations rule) clears it.
  (c) ``run_model`` on the skeleton returns the compact summary shape with a
      solved price, never a raw DataFrame.
  (d) ``save_model`` round-trips through ``new_graph(template_id=...)``, and
      shows up in ``list_models()``.
  (e) ``add_block``'s generic port-kind auto-wiring: the "obvious edge" for
      a policy block, and the singular-port conflict/``replace_existing``
      behaviour for price-formation blocks (the R1 guidance path).
  (f) ``list_blocks``/``describe_block`` cover the whole catalogue and
      reject an unknown id; ``set_params``/``remove_node`` reject an unknown
      node id.
  (g) One in-process MCP protocol smoke test over the SDK's in-memory
      transport: the server starts, lists all 10 tools, and answers a
      ``call_tool`` round trip.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from pe import model_store
from pe.mcp import tools

# TEST INFRA (not the example library): the recovered minimal competitive
# scenario stands in for a bundled example when a case asserts the example
# listing is non-empty (its stem is ``minimal_scenario``).
FIXTURES_DIR = next(p for p in Path(__file__).resolve().parents if p.name == "tests") / "fixtures"


# ── (a) new_graph() minimal skeleton ─────────────────────────────────────


def test_new_graph_blank_skeleton_validates_clean() -> None:
    graph = tools.new_graph()["graph"]
    assert {n["block"] for n in graph["nodes"]} == {
        "carbon_market",
        "competitive_clearing",
        "participant",
    }

    result = tools.check(graph)
    assert result["ok"] is True, result["issues"]
    assert result["issues"] == []
    assert result["next_steps"] == []


# ── (b) add_block(msr_bank_threshold) -> R6 next_steps -> resolved ───────


def test_add_msr_bank_threshold_yields_r6_next_step() -> None:
    graph = tools.new_graph()["graph"]
    added = tools.add_block(graph, "msr_bank_threshold")
    assert added["node_id"] == "msr_bank_threshold"
    assert added["notes"] == []

    result = tools.check(added["graph"])
    assert result["ok"] is False
    rules = {step["rule"] for step in result["next_steps"]}
    assert "R6" in rules
    r6 = next(step for step in result["next_steps"] if step["rule"] == "R6")
    assert r6["node"] == "msr_bank_threshold"
    assert "banking_allowed" in r6["suggestion"]
    assert r6["suggestion"].strip().endswith("?")


def test_applying_r6_suggestion_clears_it() -> None:
    graph = tools.new_graph()["graph"]
    added = tools.add_block(graph, "msr_bank_threshold")["graph"]

    market = next(n for n in added["nodes"] if n["id"] == "market")
    market["params"]["years"][0]["banking_allowed"] = True
    with_expectations = tools.add_block(
        added, "expectations", params={"expectation_rule": "next_year_baseline"}
    )["graph"]

    result = tools.check(with_expectations)
    assert result["ok"] is True, result["issues"]
    assert result["next_steps"] == []


# ── (c) run_model compact summary ────────────────────────────────────────


def test_run_model_on_skeleton_returns_compact_summary_with_solved_price() -> None:
    graph = tools.new_graph()["graph"]
    result = tools.run_model(graph)

    assert result["ok"] is True
    assert set(result.keys()) == {"ok", "scenarios"}
    scenario = result["scenarios"]["New Model"]
    assert scenario["total_years"] == 1
    assert scenario["truncated"] is False
    (year_row,) = scenario["years"]
    assert year_row["year"] == "2026"
    assert isinstance(year_row["price"], float)
    assert year_row["price"] >= 0.0
    # Compact: no participant-level columns, no bank/MSR/CCR noise on a
    # plain competitive skeleton.
    assert set(year_row.keys()) == {
        "year",
        "price",
        "auction_offered",
        "auction_sold",
        "total_abatement",
    }


def test_run_model_unknown_scenario_raises() -> None:
    graph = tools.new_graph()["graph"]
    with pytest.raises(ValueError, match="Unknown scenario"):
        tools.run_model(graph, scenario="Does Not Exist")


def test_run_model_invalid_graph_raises_model_store_error() -> None:
    graph = tools.new_graph()["graph"]
    graph["nodes"] = [n for n in graph["nodes"] if n["block"] != "competitive_clearing"]
    graph["edges"] = [e for e in graph["edges"] if e["targetPort"] != "price_formation"]
    with pytest.raises(model_store.ModelStoreError, match="R1"):
        tools.run_model(graph)


# ── (d) save_model round-trips through new_graph(template_id=...) ───────


def test_save_model_round_trips_and_lists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "USER_SCENARIOS_DIR", tmp_path)
    monkeypatch.setattr(model_store, "EXAMPLES_DIR", FIXTURES_DIR)

    graph = tools.new_graph()["graph"]
    saved = tools.save_model(graph, "My Saved Model")
    assert saved["id"] == "user_my_saved_model"
    assert saved["name"] == "My Saved Model"
    assert "note" in saved

    listed = tools.list_models()
    registry_ids = {m["id"] for m in listed["models"] if m["source"] == "registry"}
    assert saved["id"] in registry_ids
    registry_entry = next(m for m in listed["models"] if m["id"] == saved["id"])
    assert "core" in registry_entry["features"]
    assert "competitive" in registry_entry["approach"]

    reopened = tools.new_graph(template_id=saved["id"])["graph"]
    assert reopened == graph

    example_ids = {m["id"] for m in listed["models"] if m["source"] == "example"}
    assert "minimal_scenario" in example_ids


def test_save_model_empty_name_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_store, "USER_SCENARIOS_DIR", tmp_path)
    graph = tools.new_graph()["graph"]
    with pytest.raises(model_store.ModelStoreError):
        tools.save_model(graph, "   ")


# ── (e) add_block auto-wiring ─────────────────────────────────────────────


def test_add_block_policy_wires_the_obvious_policies_edge() -> None:
    graph = tools.new_graph()["graph"]
    added = tools.add_block(graph, "price_ceiling", params={"price_upper_bound": 250.0})
    edge = next(e for e in added["graph"]["edges"] if e["source"] == "price_ceiling")
    assert edge == {
        "source": "price_ceiling",
        "sourcePort": "policy",
        "target": "market",
        "targetPort": "policies",
    }
    assert tools.check(added["graph"])["ok"] is True


def test_add_block_second_price_formation_creates_r1_conflict_by_default() -> None:
    graph = tools.new_graph()["graph"]
    added = tools.add_block(graph, "hotelling")
    assert "wired anyway" in added["notes"][0]

    issues = tools.check(added["graph"])["issues"]
    assert any(issue["rule"] == "R1" for issue in issues)


def test_add_block_replace_existing_swaps_price_formation_cleanly() -> None:
    graph = tools.new_graph()["graph"]
    added = tools.add_block(graph, "hotelling", replace_existing=True)
    assert "Removed the existing" in added["notes"][0]

    pf_edges = [e for e in added["graph"]["edges"] if e["targetPort"] == "price_formation"]
    assert len(pf_edges) == 1
    assert pf_edges[0]["source"] == "hotelling"
    issues = tools.check(added["graph"])["issues"]
    assert not any(issue["rule"] == "R1" for issue in issues)


def test_add_block_unknown_block_id_raises() -> None:
    graph = tools.new_graph()["graph"]
    with pytest.raises(ValueError, match="Unknown block id"):
        tools.add_block(graph, "not_a_real_block")


def test_add_block_ambiguous_target_market_raises() -> None:
    graph = tools.new_graph()["graph"]
    second_market = tools.add_block(graph, "carbon_market", params={"name": "Second Market"})[
        "graph"
    ]
    with pytest.raises(ValueError, match="target_market"):
        tools.add_block(second_market, "participant", params={"name": "P2"})


# ── (f) list_blocks / describe_block / set_params / remove_node ─────────


def test_list_blocks_and_describe_block_cover_the_catalogue() -> None:
    from pe.blocks import BLOCK_CATALOGUE

    all_blocks = tools.list_blocks()["blocks"]
    assert {b["id"] for b in all_blocks} == set(BLOCK_CATALOGUE.ids())

    policy_blocks = tools.list_blocks(category="policy")["blocks"]
    assert policy_blocks
    assert all(b["category"] == "policy" for b in policy_blocks)

    described = tools.describe_block("msr_bank_threshold")
    assert described["id"] == "msr_bank_threshold"
    assert any(c["kind"] == "excludes" for c in described["constraints"])


def test_describe_block_unknown_id_raises() -> None:
    with pytest.raises(ValueError, match="Unknown block id"):
        tools.describe_block("not_a_real_block")


def test_set_params_merges_and_none_clears() -> None:
    graph = tools.new_graph()["graph"]
    updated = tools.set_params(graph, "p1", {"penalty_price": 999.0})["graph"]
    p1 = next(n for n in updated["nodes"] if n["id"] == "p1")
    assert p1["params"]["penalty_price"] == 999.0
    assert p1["params"]["initial_emissions"] == 100.0  # untouched

    cleared = tools.set_params(updated, "p1", {"penalty_price": None})["graph"]
    p1_cleared = next(n for n in cleared["nodes"] if n["id"] == "p1")
    assert "penalty_price" not in p1_cleared["params"]


def test_set_params_unknown_node_raises() -> None:
    graph = tools.new_graph()["graph"]
    with pytest.raises(ValueError, match="Unknown node id"):
        tools.set_params(graph, "does-not-exist", {"x": 1})


def test_remove_node_drops_node_and_its_edges() -> None:
    graph = tools.new_graph()["graph"]
    updated = tools.remove_node(graph, "p1")["graph"]
    assert "p1" not in {n["id"] for n in updated["nodes"]}
    assert not any(e["source"] == "p1" or e["target"] == "p1" for e in updated["edges"])
    # No participants left -> R2.
    issues = tools.check(updated)["issues"]
    assert any(issue["rule"] == "R2" for issue in issues)


def test_remove_node_unknown_node_raises() -> None:
    graph = tools.new_graph()["graph"]
    with pytest.raises(ValueError, match="Unknown node id"):
        tools.remove_node(graph, "does-not-exist")


# ── (g) in-process MCP protocol smoke test (in-memory transport) ────────


def test_mcp_server_lists_tools_and_answers_call_tool_over_memory_transport() -> None:
    mcp_client = pytest.importorskip("mcp.shared.memory")
    from pe.mcp.server import mcp as server

    async def _run() -> None:
        async with mcp_client.create_connected_server_and_client_session(server) as session:
            listed = await session.list_tools()
            names = {t.name for t in listed.tools}
            assert names == {
                "list_models",
                "list_blocks",
                "describe_block",
                "new_graph",
                "add_block",
                "set_params",
                "remove_node",
                "check",
                "run_model",
                "save_model",
            }

            result = await session.call_tool("new_graph", {})
            assert result.isError is False

    asyncio.run(_run())
