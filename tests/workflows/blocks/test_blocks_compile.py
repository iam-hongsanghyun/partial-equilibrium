"""Compile tests (blocks-graph-plan.md §4, Order 6).

(a) Four hand-built canonical drawings — built directly with
``Node``/``Edge``/``Graph`` against the real ``BLOCK_CATALOGUE`` port names
(never via ``decompile.graph_from_config``, which has its own dedicated
round-trip test in ``test_blocks_decompile.py``) — must ``compile_graph`` to
a config whose ``run_simulation_from_config`` output is cell-for-cell
identical (``rtol=0, atol=0``) to ``run_simulation_from_file`` on the
matching example. Per-year participant/policy values are pulled
programmatically from the example JSON (rather than hand-typed) purely to
keep this file a manageable size; the graph topology (nodes, edges, ports,
block choices) is authored directly.

(b) Validation-rejection tests: one per ERROR rule family (R1-R4, R5-R16,
R17-R23, R24-R27, R30), plus the specific cases the work order calls out
(two MSR blocks on one market, kmsr_decree without banking, zero and two
price-formation edges, a dangling edge).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from ets import run_simulation_from_config, run_simulation_from_file
from ets.blocks import Edge, Graph, Node, compile_graph, validate_graph
from ets.blocks.catalogue import BLOCK_CATALOGUE
from ets.blocks.compile import per_year_value

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"


def _load(stem: str) -> dict[str, Any]:
    return json.loads((EXAMPLES_DIR / f"{stem}.json").read_text())


def _collapse_field(values_by_year: dict[str, Any], default: Any) -> Any:
    values = list(values_by_year.values())
    if all(v == values[0] for v in values):
        return values[0]
    return per_year_value(values_by_year)


def _participant_node(node_id: str, years: list[dict], name: str, order: int) -> Node:
    """Build a participant Node by collapsing one participant's fields across years."""
    spec = BLOCK_CATALOGUE.get("participant")
    params: dict[str, Any] = {"order": order}
    for param in spec.params:
        values_by_year = {}
        for year in years:
            match = next((p for p in year["participants"] if p["name"] == name), None)
            if match is None:
                continue
            values_by_year[str(year["year"])] = match.get(param.config_key, param.default)
        if not values_by_year:
            continue
        collapsed = _collapse_field(values_by_year, param.default)
        if isinstance(collapsed, dict) and "__per_year__" in collapsed:
            params[param.name] = collapsed
        elif collapsed != param.default:
            params[param.name] = collapsed
    return Node(node_id, "participant", params)


def _bound_node(node_id: str, years: list[dict], block_id: str, config_key: str, default: float) -> Node | None:
    """price_floor/price_ceiling node, or None if every year matches the default.

    Bit-identical replay (not just numerically-close) requires this: the
    competitive solver's Brent bracket is seeded from price_upper_bound, so a
    missing price_ceiling block silently substitutes the catalogue default
    (100.0) for the bracket endpoint. Even when the equilibrium price itself
    is unaffected, a different bracket walks a different floating-point path
    to the same root — enough to fail an ``rtol=0, atol=0`` comparison.
    """
    values_by_year = {str(y["year"]): y.get(config_key, default) for y in years}
    if all(v == default for v in values_by_year.values()):
        return None
    return Node(node_id, block_id, {config_key: _collapse_field(values_by_year, default)})


def _attach_bounds(nodes: list[Node], edges: list[Edge], market_id: str, years: list[dict]) -> None:
    floor = _bound_node(f"{market_id}_floor", years, "price_floor", "price_lower_bound", 0.0)
    ceiling = _bound_node(f"{market_id}_ceiling", years, "price_ceiling", "price_upper_bound", 100.0)
    for node in (floor, ceiling):
        if node is not None:
            nodes.append(node)
            edges.append(Edge(node.id, "policy", market_id, "policies"))


def _market_years_grid(years: list[dict]) -> list[dict]:
    keys = (
        "year", "total_cap", "auction_mode", "auction_offered", "reserved_allowances",
        "carbon_budget", "banking_allowed", "borrowing_allowed", "borrowing_limit",
    )
    return [{k: y[k] for k in keys if k in y} for y in years]


def _assert_runs_identically(graph: Graph, example_stem: str) -> None:
    compiled = compile_graph(graph)
    summary_a, participants_a = run_simulation_from_config(compiled)
    summary_b, participants_b = run_simulation_from_file(EXAMPLES_DIR / f"{example_stem}.json")
    pd.testing.assert_frame_equal(summary_a, summary_b, check_exact=True)
    pd.testing.assert_frame_equal(participants_a, participants_b, check_exact=True)


# ── (a) four canonical drawings ─────────────────────────────────────────


def test_basic_linear_competitive_market() -> None:
    cfg = _load("climate_solutions_basic_linear")
    scenario = cfg["scenarios"][0]
    years = scenario["years"]

    nodes = [
        Node("market", "carbon_market", {"name": scenario["name"], "years": _market_years_grid(years)}),
        Node("pf", "competitive_clearing", {}),
    ]
    edges = [Edge("pf", "price_formation", "market", "price_formation")]
    for i, p in enumerate(years[0]["participants"]):
        pid = f"p{i}"
        nodes.append(_participant_node(pid, years, p["name"], i))
        edges.append(Edge(pid, "compliance", "market", "participants"))
    _attach_bounds(nodes, edges, "market", years)

    graph = Graph(nodes=nodes, edges=edges)
    issues = validate_graph(graph)
    assert not [i for i in issues if i.level == "error"]
    _assert_runs_identically(graph, "climate_solutions_basic_linear")


def test_msr_on_competitive_market() -> None:
    cfg = _load("climate_solutions_msr_stability")
    nodes: list[Node] = []
    edges: list[Edge] = []
    for scenario_index, scenario in enumerate(cfg["scenarios"]):
        years = scenario["years"]
        market_id = f"market{scenario_index}"
        nodes.append(
            Node(market_id, "carbon_market", {
                "name": scenario["name"], "years": _market_years_grid(years), "order": scenario_index,
            })
        )
        pf_id = f"{market_id}_pf"
        nodes.append(Node(pf_id, "competitive_clearing", {}))
        edges.append(Edge(pf_id, "price_formation", market_id, "price_formation"))
        for i, p in enumerate(years[0]["participants"]):
            pid = f"{market_id}_p{i}"
            nodes.append(_participant_node(pid, years, p["name"], i))
            edges.append(Edge(pid, "compliance", market_id, "participants"))
        _attach_bounds(nodes, edges, market_id, years)
        if scenario.get("msr_enabled"):
            msr_id = f"{market_id}_msr"
            nodes.append(
                Node(msr_id, "msr_bank_threshold", {
                    "msr_upper_threshold": scenario["msr_upper_threshold"],
                    "msr_lower_threshold": scenario["msr_lower_threshold"],
                    "msr_withhold_rate": scenario["msr_withhold_rate"],
                    "msr_release_rate": scenario["msr_release_rate"],
                    "msr_cancel_excess": scenario["msr_cancel_excess"],
                    "msr_cancel_threshold": scenario["msr_cancel_threshold"],
                })
            )
            edges.append(Edge(msr_id, "policy", market_id, "policies"))

    graph = Graph(nodes=nodes, edges=edges)
    issues = validate_graph(graph)
    assert not [i for i in issues if i.level == "error"]
    _assert_runs_identically(graph, "climate_solutions_msr_stability")


@pytest.mark.slow
def test_kmsr_decree_on_banking() -> None:
    """~150s: 15-year discrete-MAC banking window solve (matches the
    k_msr_P1_decree_banking golden baseline, itself marked slow at ~220s)."""
    cfg = _load("k_msr_P1_decree_banking")
    scenario = cfg["scenarios"][0]
    years = scenario["years"]

    nodes = [
        Node("market", "carbon_market", {"name": scenario["name"], "years": _market_years_grid(years)}),
        Node("pf", "rubin_schennach_banking", {
            "discount_rate": scenario["discount_rate"],
            "solver_penalty_price_multiplier": scenario["solver_penalty_price_multiplier"],
            "banking_initial_bank": scenario["banking_initial_bank"],
            "banking_strict_no_arbitrage": scenario["banking_strict_no_arbitrage"],
        }),
        Node("msr", "kmsr_decree", {
            "msr_mode": scenario["msr_mode"],
            "msr_price_band_high": scenario["msr_price_band_high"],
            "msr_price_band_low": scenario["msr_price_band_low"],
            "msr_surplus_upper_ratio": scenario["msr_surplus_upper_ratio"],
            "msr_surplus_lower_ratio": scenario["msr_surplus_lower_ratio"],
            "msr_max_intake_mt": scenario["msr_max_intake_mt"],
            "msr_max_release_mt": scenario["msr_max_release_mt"],
            "msr_initial_reserve_mt": scenario["msr_initial_reserve_mt"],
        }),
    ]
    edges = [
        Edge("pf", "price_formation", "market", "price_formation"),
        Edge("msr", "policy", "market", "policies"),
    ]
    for i, p in enumerate(years[0]["participants"]):
        pid = f"p{i}"
        nodes.append(_participant_node(pid, years, p["name"], i))
        edges.append(Edge(pid, "compliance", "market", "participants"))
    _attach_bounds(nodes, edges, "market", years)

    graph = Graph(nodes=nodes, edges=edges)
    issues = validate_graph(graph)
    assert not [i for i in issues if i.level == "error"]
    _assert_runs_identically(graph, "k_msr_P1_decree_banking")


def test_ccr_carbon_cap_rule() -> None:
    cfg = _load("benmir_ccr_carbon_cap_rule")
    nodes: list[Node] = []
    edges: list[Edge] = []
    for scenario_index, scenario in enumerate(cfg["scenarios"]):
        years = scenario["years"]
        market_id = f"market{scenario_index}"
        nodes.append(
            Node(market_id, "carbon_market", {
                "name": scenario["name"], "years": _market_years_grid(years), "order": scenario_index,
            })
        )
        pf_id = f"{market_id}_pf"
        nodes.append(Node(pf_id, "competitive_clearing", {}))
        edges.append(Edge(pf_id, "price_formation", market_id, "price_formation"))
        for i, p in enumerate(years[0]["participants"]):
            pid = f"{market_id}_p{i}"
            nodes.append(_participant_node(pid, years, p["name"], i))
            edges.append(Edge(pid, "compliance", market_id, "participants"))
        _attach_bounds(nodes, edges, market_id, years)
        if scenario.get("ccr_enabled"):
            ccr_id = f"{market_id}_ccr"
            nodes.append(
                Node(ccr_id, "ccr", {
                    "ccr_phi_emissions": scenario["ccr_phi_emissions"],
                    "ccr_phi_abatement_cost": scenario["ccr_phi_abatement_cost"],
                    "ccr_reference_emissions": scenario["ccr_reference_emissions"],
                    "ccr_reference_abatement_cost": scenario["ccr_reference_abatement_cost"],
                })
            )
            edges.append(Edge(ccr_id, "policy", market_id, "policies"))

    graph = Graph(nodes=nodes, edges=edges)
    issues = validate_graph(graph)
    assert not [i for i in issues if i.level == "error"]
    _assert_runs_identically(graph, "benmir_ccr_carbon_cap_rule")


# ── (b) validation rejections ────────────────────────────────────────────


def _minimal_graph(**overrides: Any) -> Graph:
    """One market, one participant, one competitive price-formation block."""
    nodes = [
        Node("market", "carbon_market", {
            "years": [{"year": "2026", "total_cap": 100.0, "auction_mode": "explicit", "auction_offered": 50.0}]
        }),
        Node("pf", "competitive_clearing", {}),
        Node("p0", "participant", {
            "name": "Steel", "initial_emissions": 100.0, "penalty_price": 50.0,
            "max_abatement": 20.0, "cost_slope": 2.0,
        }),
    ]
    edges = [
        Edge("pf", "price_formation", "market", "price_formation"),
        Edge("p0", "compliance", "market", "participants"),
    ]
    graph = Graph(nodes=nodes, edges=edges)
    for key, value in overrides.items():
        setattr(graph, key, value)
    return graph


def _issue_rules(issues, level="error") -> set[str]:
    return {i.rule for i in issues if i.level == level}


def test_r1_zero_price_formation_edges() -> None:
    graph = _minimal_graph()
    graph.edges = [e for e in graph.edges if e.target_port != "price_formation"]
    assert "R1" in _issue_rules(validate_graph(graph))


def test_r1_two_price_formation_edges() -> None:
    graph = _minimal_graph()
    graph.nodes.append(Node("pf2", "hotelling", {}))
    graph.edges.append(Edge("pf2", "price_formation", "market", "price_formation"))
    assert "R1" in _issue_rules(validate_graph(graph))


def test_r2_no_participants() -> None:
    graph = _minimal_graph()
    graph.edges = [e for e in graph.edges if e.target_port != "participants"]
    assert "R2" in _issue_rules(validate_graph(graph))


def test_r3_dangling_edge() -> None:
    graph = _minimal_graph()
    graph.edges.append(Edge("does-not-exist", "policy", "market", "policies"))
    assert "R3" in _issue_rules(validate_graph(graph))


def test_r4_policy_to_policy_edge_rejected() -> None:
    graph = _minimal_graph()
    graph.nodes.append(Node("floor", "price_floor", {"price_lower_bound": 5.0}))
    graph.nodes.append(Node("ceil", "price_ceiling", {"price_upper_bound": 90.0}))
    graph.edges.append(Edge("floor", "policy", "market", "policies"))
    graph.edges.append(Edge("ceil", "policy", "market", "policies"))
    # Decorative edge directly between two policy blocks (not into the market).
    graph.edges.append(Edge("floor", "policy", "ceil", "policy"))
    assert "R4" in _issue_rules(validate_graph(graph))


def test_two_msr_blocks_on_one_market() -> None:
    graph = _minimal_graph()
    graph.nodes.append(Node("msr1", "msr_bank_threshold", {}))
    graph.nodes.append(Node("msr2", "msr_bank_threshold", {}))
    graph.edges.append(Edge("msr1", "policy", "market", "policies"))
    graph.edges.append(Edge("msr2", "policy", "market", "policies"))
    with pytest.raises(Exception):
        compile_graph(graph)


def test_r5_kmsr_decree_without_banking() -> None:
    graph = _minimal_graph()  # price formation is competitive_clearing
    graph.nodes.append(Node("decree", "kmsr_decree", {"msr_mode": "hybrid"}))
    graph.edges.append(Edge("decree", "policy", "market", "policies"))
    assert "R5" in _issue_rules(validate_graph(graph))


def test_r9_ccr_requires_competitive() -> None:
    graph = _minimal_graph()
    graph.nodes[1] = Node("pf", "hotelling", {})
    graph.nodes.append(Node("ccr", "ccr", {"ccr_reference_emissions": 100.0}))
    graph.edges.append(Edge("ccr", "policy", "market", "policies"))
    assert "R9" in _issue_rules(validate_graph(graph))


def test_r14_hotelling_requires_budget_or_cap() -> None:
    graph = _minimal_graph()
    graph.nodes[1] = Node("pf", "hotelling", {})
    graph.nodes[0].params["years"] = [
        {"year": "2026", "total_cap": 0.0, "auction_mode": "explicit", "auction_offered": 0.0, "carbon_budget": 0.0}
    ]
    assert "R14" in _issue_rules(validate_graph(graph))


def test_r18_banking_forbids_borrowing() -> None:
    graph = _minimal_graph()
    graph.nodes[1] = Node("pf", "rubin_schennach_banking", {})
    graph.nodes[0].params["years"] = [
        {
            "year": "2026", "total_cap": 100.0, "auction_mode": "explicit", "auction_offered": 50.0,
            "banking_allowed": True, "borrowing_allowed": True,
        }
    ]
    assert "R18" in _issue_rules(validate_graph(graph))


def test_r23_banking_negative_discount_plus_premium() -> None:
    graph = _minimal_graph()
    graph.nodes[1] = Node("pf", "rubin_schennach_banking", {"discount_rate": -0.5, "risk_premium": -0.5})
    assert "R23" in _issue_rules(validate_graph(graph))


def test_r24_reserve_price_exceeds_ceiling() -> None:
    graph = _minimal_graph()
    graph.nodes.append(Node("ceil", "price_ceiling", {"price_upper_bound": 50.0}))
    graph.nodes.append(Node("reserve", "auction_reserve", {"auction_reserve_price": 999.0}))
    graph.edges.append(Edge("ceil", "policy", "market", "policies"))
    graph.edges.append(Edge("reserve", "policy", "market", "policies"))
    assert "R24" in _issue_rules(validate_graph(graph))


def test_r25_no_ceiling_and_zero_penalty_with_auction() -> None:
    graph = _minimal_graph()
    graph.nodes[2].params["penalty_price"] = 0.0
    assert "R25" in _issue_rules(validate_graph(graph))


def test_r26_cap_consistency_violation() -> None:
    graph = _minimal_graph()
    graph.nodes[0].params["years"] = [
        {"year": "2026", "total_cap": 10.0, "auction_mode": "explicit", "auction_offered": 50.0}
    ]
    assert "R26" in _issue_rules(validate_graph(graph))


def test_r30_announced_year_outside_horizon() -> None:
    graph = _minimal_graph()
    graph.nodes.append(Node("cancel", "cancellation", {"cancelled_allowances": 5.0, "announced": "1999"}))
    graph.edges.append(Edge("cancel", "policy", "market", "policies"))
    assert "R30" in _issue_rules(validate_graph(graph))
