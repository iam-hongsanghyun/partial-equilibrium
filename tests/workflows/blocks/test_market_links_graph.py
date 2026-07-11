"""D1-4 gate: graph disentanglement — the composer draws and compiles market links.

Covers ``docs/platform-plan-d0-d1.md`` D1 "GRAPH DISENTANGLEMENT" and the
binding ``docs/platform-spec-d0-d1.md`` §3/§7 (R34-R36 rule texts):

(a) Every existing example graph round-trips ``compile(decompile(cfg)) ==
    normalize(cfg)`` bit-identically — the size-1-component proof (no
    existing graph changes) is ALREADY covered by
    ``test_blocks_decompile.py::test_decompile_compile_round_trip``, which
    is unmodified and still runs; nothing here duplicates it.
(b) A hand-built 2-market linked graph compiles to ``markets:[...]`` +
    ``links:[...]`` and decompiles back, both directions.
(c) R34 (cycle, self-link, malformed cardinality), R35 (channel whitelist,
    duplicate link), R36 (missing price_unit/phi_unit) — each a graph that
    ``validate_graph`` flags without raising.
(d) The compiled 2-market linked graph RUNS via ``run_simulation_from_config``
    and matches the D1-3 A1 hand-values (``tests/engine/test_multi_market.py``):
    P_A = sigma_A*(E0_A - Q_A) = 80, P_B = c_B + phi*P_A = 50.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from pe import run_simulation_from_config
from pe.blocks import Edge, Graph, Node, compile_graph, graph_from_config, validate_graph
from pe.blocks.compile import CompileError

# Mirrors tests/engine/test_multi_market.py's A1 anchor economy exactly (the
# composer -> engine round trip must reproduce the same hand-solved chain):
#   sigma_A = 2, E0_A = 100, Q_A = 60  =>  P_A = 2*(100-60) = 80
#   c_B = 10, phi = 0.5, A_B = 40, Q_B = 80  =>  P_B = 10 + 0.5*80 = 50
SIGMA_A = 2.0
E0_A = 100.0
Q_A = 60.0
P_A_IDEAL = SIGMA_A * (E0_A - Q_A)  # 80

C_B = 10.0
PHI = 0.5
Q_B = 80.0
P_B_IDEAL = C_B + PHI * P_A_IDEAL  # 50

PRICE_ATOL = 1e-6


# ── (b)/(d): a valid, fully-wired 2-market linked graph ──────────────────


def _linked_graph() -> Graph:
    """A -> B mac_cost link, drawn directly against BLOCK_CATALOGUE port names.

    Market A: one linear-MAC participant (pure buyer). Market B: one
    threshold-technology participant, mac_cost-linked from A. Both declare
    price_unit (R36); the link declares phi_unit (R36).
    """
    nodes = [
        Node(
            "mA", "carbon_market",
            {
                "name": "A", "order": 0, "price_unit": "USD/tCO2",
                "years": [
                    {"year": "2030", "total_cap": Q_A, "auction_mode": "explicit", "auction_offered": Q_A}
                ],
            },
        ),
        Node("mA_pf", "competitive_clearing", {}),
        Node("mA_ceil", "price_ceiling", {"price_upper_bound": 100000.0}),
        Node(
            "mA_p0", "participant",
            {
                "name": "A_firm", "initial_emissions": E0_A, "free_allocation_ratio": 0.0,
                "penalty_price": 100000.0, "abatement_type": "linear",
                "cost_slope": SIGMA_A, "max_abatement": E0_A,
            },
        ),
        Node(
            "mB", "carbon_market",
            {
                "name": "B", "order": 1, "price_unit": "USD/tCO2",
                "years": [
                    {"year": "2030", "total_cap": Q_B, "auction_mode": "explicit", "auction_offered": Q_B}
                ],
            },
        ),
        Node("mB_pf", "competitive_clearing", {}),
        Node("mB_ceil", "price_ceiling", {"price_upper_bound": 100000.0}),
        Node(
            "mB_p0", "participant",
            {
                "name": "B_firm", "initial_emissions": 100.0, "free_allocation_ratio": 0.0,
                "penalty_price": 100000.0, "abatement_type": "threshold",
                "threshold_cost": 999.0, "max_abatement": 0.0,
            },
        ),
        Node(
            "mB_p0_block", "technology_option",
            {
                "name": "block", "abatement_type": "threshold", "threshold_cost": C_B,
                "initial_emissions": 100.0, "max_abatement": 40.0,
                "free_allocation_ratio": 0.0, "penalty_price": 100000.0, "max_activity_share": 1.0,
            },
        ),
        Node(
            "link_ab", "market_link",
            {
                "channel": "mac_cost", "phi": PHI, "phi_unit": "1/1",
                "target_participants": ["B_firm"], "target_technologies": ["block"],
            },
        ),
    ]
    edges = [
        Edge("mA_pf", "price_formation", "mA", "price_formation"),
        Edge("mA_ceil", "policy", "mA", "policies"),
        Edge("mA_p0", "compliance", "mA", "participants"),
        Edge("mB_pf", "price_formation", "mB", "price_formation"),
        Edge("mB_ceil", "policy", "mB", "policies"),
        Edge("mB_p0", "compliance", "mB", "participants"),
        Edge("mB_p0_block", "option", "mB_p0", "options"),
        Edge("mA", "signal", "link_ab", "from"),
        Edge("link_ab", "link", "mB", "links"),
    ]
    return Graph(nodes=nodes, edges=edges)


def test_linked_graph_validates_clean() -> None:
    issues = validate_graph(_linked_graph())
    assert not [i for i in issues if i.level == "error"], issues


def test_linked_graph_compiles_to_markets_and_links() -> None:
    compiled = compile_graph(_linked_graph())
    assert len(compiled["scenarios"]) == 1
    scenario = compiled["scenarios"][0]
    assert scenario["name"] == "A"  # order-first market's own name, no scenario_name set
    market_ids = [m["market_id"] for m in scenario["markets"]]
    assert market_ids == ["A", "B"]
    assert len(scenario["links"]) == 1
    (link,) = scenario["links"]
    assert (link["from_market"], link["to_market"], link["channel"]) == ("A", "B", "mac_cost")
    assert link["phi"] == PHI
    assert link["phi_unit"] == "1/1"
    assert link["target_participants"] == ["B_firm"]
    assert link["target_technologies"] == ["block"]


def test_linked_graph_round_trips_both_directions() -> None:
    """compile -> decompile -> compile reproduces the same compiled config."""
    compiled = compile_graph(_linked_graph())
    decompiled = graph_from_config(compiled)
    recompiled = compile_graph(decompiled)
    assert recompiled == compiled


def test_decompiled_linked_graph_has_market_link_node() -> None:
    compiled = compile_graph(_linked_graph())
    decompiled = graph_from_config(compiled)
    link_nodes = [n for n in decompiled.nodes if n.block == "market_link"]
    assert len(link_nodes) == 1
    market_nodes = [n for n in decompiled.nodes if n.block == "carbon_market"]
    assert {n.params["name"] for n in market_nodes} == {"A", "B"}


# ── (d) composer -> engine: the compiled graph reproduces the A1 anchor ──


def _price(summary: pd.DataFrame, scenario_key: str) -> float:
    rows = summary[summary["Scenario"] == scenario_key]
    return float(rows["Equilibrium Carbon Price"].iloc[0])


def test_compiled_linked_graph_matches_a1_hand_values() -> None:
    """P_A = 80, P_B = 50 (atol 1e-6) — the composer -> engine round trip."""
    compiled = compile_graph(_linked_graph())
    summary, _ = run_simulation_from_config(compiled)
    np.testing.assert_allclose(_price(summary, "A :: A"), P_A_IDEAL, rtol=0, atol=PRICE_ATOL)
    np.testing.assert_allclose(_price(summary, "A :: B"), P_B_IDEAL, rtol=0, atol=PRICE_ATOL)


def test_compiled_linked_graph_diagnostic_columns_present() -> None:
    compiled = compile_graph(_linked_graph())
    summary, _ = run_simulation_from_config(compiled)
    b_row = summary[summary["Market"] == "B"]
    assert len(b_row) == 1
    np.testing.assert_allclose(
        float(b_row["Link A->B Price In"].iloc[0]), P_A_IDEAL, rtol=0, atol=PRICE_ATOL
    )


# ── scenario_name: agreement / disagreement / explicit override ──────────


def test_scenario_name_explicit_override_on_first_market() -> None:
    graph = _linked_graph()
    graph.node("mA").params["scenario_name"] = "Chain"
    compiled = compile_graph(graph)
    assert compiled["scenarios"][0]["name"] == "Chain"


def test_scenario_name_disagreement_raises() -> None:
    graph = _linked_graph()
    graph.node("mA").params["scenario_name"] = "Chain"
    graph.node("mB").params["scenario_name"] = "Different"
    with pytest.raises(CompileError, match="scenario_name"):
        compile_graph(graph)


def test_linked_market_id_forbids_double_colon() -> None:
    graph = _linked_graph()
    graph.node("mB").params["name"] = "steel::b"
    with pytest.raises(CompileError, match="::"):
        compile_graph(graph)


# ── (c) R34/R35/R36 — structural negatives (validate_graph never raises) ──


def _issue_rules(issues: list[Any], level: str = "error") -> set[str]:
    return {i.rule for i in issues if i.level == level}


def _two_market_graph() -> Graph:
    """Two minimal, unlinked, valid markets 'A'/'B' — the base every negative
    link test below adds exactly one broken market_link node to."""
    nodes = [
        Node(
            "mA", "carbon_market",
            {"name": "A", "order": 0, "years": [
                {"year": "2026", "total_cap": 100.0, "auction_mode": "explicit", "auction_offered": 50.0}
            ]},
        ),
        Node("mA_pf", "competitive_clearing", {}),
        Node(
            "mA_p0", "participant",
            {"name": "A_firm", "initial_emissions": 100.0, "penalty_price": 50.0, "max_abatement": 20.0, "cost_slope": 2.0},
        ),
        Node(
            "mB", "carbon_market",
            {"name": "B", "order": 1, "years": [
                {"year": "2026", "total_cap": 100.0, "auction_mode": "explicit", "auction_offered": 50.0}
            ]},
        ),
        Node("mB_pf", "competitive_clearing", {}),
        Node(
            "mB_p0", "participant",
            {"name": "B_firm", "initial_emissions": 100.0, "penalty_price": 50.0, "max_abatement": 20.0, "cost_slope": 2.0},
        ),
    ]
    edges = [
        Edge("mA_pf", "price_formation", "mA", "price_formation"),
        Edge("mA_p0", "compliance", "mA", "participants"),
        Edge("mB_pf", "price_formation", "mB", "price_formation"),
        Edge("mB_p0", "compliance", "mB", "participants"),
    ]
    return Graph(nodes=nodes, edges=edges)


def _add_link(
    graph: Graph, link_id: str, *, from_market: str = "mA", to_market: str = "mB", **overrides: Any
) -> Graph:
    params: dict[str, Any] = {
        "channel": "mac_cost", "phi": 0.5, "phi_unit": "1/1",
        "target_participants": ["B_firm"], "target_technologies": ["block"],
    }
    params.update(overrides)
    graph.nodes.append(Node(link_id, "market_link", params))
    graph.edges.append(Edge(from_market, "signal", link_id, "from"))
    graph.edges.append(Edge(link_id, "link", to_market, "links"))
    return graph


def test_r34_cycle_is_legal_no_error() -> None:
    """R34 FLIP (D2-3): a cycle A<->B is LEGAL — no R34 error (it is the joint SCC).

    Both markets are competitive (no banking / discrete-adoption member), so R37
    stays silent too even though this graph carries no damping declaration.
    """
    graph = _two_market_graph()
    _add_link(graph, "l1", from_market="mA", to_market="mB")
    _add_link(graph, "l2", from_market="mB", to_market="mA", target_participants=["A_firm"])
    issues = validate_graph(graph)
    assert "R34" not in _issue_rules(issues)
    assert not any("cycle" in i.message.lower() for i in issues if i.rule == "R34")
    assert "R37" not in _issue_rules(issues, level="warning")


def test_r34_self_link_rejected() -> None:
    graph = _two_market_graph()
    _add_link(graph, "l1", from_market="mA", to_market="mA")
    issues = validate_graph(graph)
    assert "R34" in _issue_rules(issues)
    assert any("self-link" in i.message.lower() for i in issues if i.rule == "R34")


def test_r34_malformed_cardinality_rejected() -> None:
    graph = _two_market_graph()
    # A market_link with neither a 'from' nor a 'link' edge.
    graph.nodes.append(
        Node("l1", "market_link", {"channel": "mac_cost", "phi": 0.5, "phi_unit": "1/1", "target_participants": ["B_firm"]})
    )
    assert "R34" in _issue_rules(validate_graph(graph))


def _make_banking(graph: Graph, market: str) -> Graph:
    """Swap a market's competitive price-formation node for rubin_schennach_banking."""
    pf_id = f"{market}_pf"
    graph.node(pf_id).block = "rubin_schennach_banking"
    return graph


def test_r37_undamped_cyclic_banking_warns() -> None:
    """R37: a cycle over a banking market run UNDAMPED (relaxation=1.0) => WARNING."""
    graph = _make_banking(_two_market_graph(), "mB")
    _add_link(graph, "l1", from_market="mA", to_market="mB", relaxation=1.0)
    _add_link(graph, "l2", from_market="mB", to_market="mA", target_participants=["A_firm"], relaxation=1.0)
    warnings = _issue_rules(validate_graph(graph), level="warning")
    assert "R37" in warnings


def test_r37_damped_cyclic_banking_silent() -> None:
    """R37 stays silent when the cyclic SCC is damped (no relaxation param => default 0.5)."""
    graph = _make_banking(_two_market_graph(), "mB")
    _add_link(graph, "l1", from_market="mA", to_market="mB")  # no relaxation => damped
    _add_link(graph, "l2", from_market="mB", to_market="mA", target_participants=["A_firm"])
    assert "R37" not in _issue_rules(validate_graph(graph), level="warning")


def test_r37_undamped_cyclic_without_banking_or_discrete_silent() -> None:
    """R37 needs a banking/discrete member: an undamped competitive cycle is silent."""
    graph = _two_market_graph()  # both competitive
    _add_link(graph, "l1", from_market="mA", to_market="mB", relaxation=1.0)
    _add_link(graph, "l2", from_market="mB", to_market="mA", target_participants=["A_firm"], relaxation=1.0)
    assert "R37" not in _issue_rules(validate_graph(graph), level="warning")


def test_r37_undamped_acyclic_banking_silent() -> None:
    """R37 needs a CYCLE: an undamped one-way link into a banking market is silent."""
    graph = _make_banking(_two_market_graph(), "mB")
    _add_link(graph, "l1", from_market="mA", to_market="mB", relaxation=1.0)  # one-way, acyclic
    assert "R37" not in _issue_rules(validate_graph(graph), level="warning")


def test_r35_invalid_channel_rejected() -> None:
    """A price-indexed supply-side 'channel' bypassing the enum (R35 whitelist)."""
    graph = _two_market_graph()
    _add_link(graph, "l1", channel="supply_side_price_index")
    assert "R35" in _issue_rules(validate_graph(graph))


def test_r35_duplicate_link_rejected() -> None:
    graph = _two_market_graph()
    _add_link(graph, "l1")
    _add_link(graph, "l2")
    issues = validate_graph(graph)
    assert "R35" in _issue_rules(issues)
    assert any("duplicate" in i.message.lower() for i in issues if i.rule == "R35")


def test_r35_distinct_sources_are_not_duplicates() -> None:
    """Two DIFFERENT sources into one target on the same channel is fine (I6)."""
    graph = _two_market_graph()
    graph.nodes.append(
        Node("mC", "carbon_market", {"name": "C", "order": 2, "years": [
            {"year": "2026", "total_cap": 100.0, "auction_mode": "explicit", "auction_offered": 50.0}
        ]})
    )
    graph.nodes.append(Node("mC_pf", "competitive_clearing", {}))
    graph.nodes.append(
        Node("mC_p0", "participant", {"name": "C_firm", "initial_emissions": 100.0, "penalty_price": 50.0, "max_abatement": 20.0, "cost_slope": 2.0})
    )
    graph.edges.append(Edge("mC_pf", "price_formation", "mC", "price_formation"))
    graph.edges.append(Edge("mC_p0", "compliance", "mC", "participants"))
    _add_link(graph, "l1", from_market="mA", to_market="mB")
    _add_link(graph, "l2", from_market="mC", to_market="mB")
    assert "R35" not in _issue_rules(validate_graph(graph))


def test_r36_missing_price_unit_rejected() -> None:
    graph = _two_market_graph()
    _add_link(graph, "l1")  # neither mA nor mB declares price_unit
    issues = validate_graph(graph)
    assert "R36" in _issue_rules(issues)
    messages = " ".join(i.message for i in issues if i.rule == "R36")
    assert "price_unit" in messages


def test_r36_missing_phi_unit_rejected() -> None:
    graph = _two_market_graph()
    graph.node("mA").params["price_unit"] = "USD/tCO2"
    graph.node("mB").params["price_unit"] = "USD/tCO2"
    _add_link(graph, "l1", phi_unit="")
    issues = validate_graph(graph)
    assert "R36" in _issue_rules(issues)
    messages = " ".join(i.message for i in issues if i.rule == "R36")
    assert "phi_unit" in messages
