r"""D2-4 gate: the block-composer is cycles-legal — draw A<->B, drop a joint_solver.

Covers ``docs/joint-equilibrium-plan.md`` §4 (the composer half of D2): a user
DRAWS a cyclic market graph (A↔B) on the canvas and it compiles to ONE joint
``markets:[...]`` scenario whose ``links`` array keeps BOTH back-edges, and a
``joint_solver`` node configures the outer loop. D2-3 (merged) already made the
CONFIG + dispatch solve such a scenario; this proves the graph tier emits it.

Assertions, end to end:

(a) compile  — the cyclic graph → ONE ``markets``/``links`` scenario carrying
    both A→B and B→A links AND the ``joint_solver`` block (relaxation preserved,
    config_io defaults filled for the keys the user left unset).
(b) validate — the cycle is LEGAL (no R34 error); both markets competitive, so
    R37 stays silent even undamped.
(c) solve    — the compiled config runs through ``run_simulation_from_config``:
    the four ``Joint *`` columns appear, ``Joint Converged == 1``, and the prices
    reach the J1 hand fixed point (``tests/engine/test_joint_dispatch.py``).
(d) round-trip — ``compile(decompile(compiled)) == compiled``, and the decompiled
    graph carries the ``joint_solver`` node wired into the first market.
(e) inertness witness — an ACYCLIC two-market graph (one-way A→B, no joint_solver
    node) compiles to today's shape with NO ``joint_solver`` key; a CYCLIC graph
    WITHOUT a joint_solver node likewise emits no key (the block only appears when
    the user drops the node).

Hand anchor (J1, ``docs/joint-equilibrium.md`` §7): two symmetric interior
THRESHOLD markets pin at their (mac_cost-shifted) thresholds, so each clears at
``P_m = c_m + phi * P_neighbour``. With c_A=100, c_B=80, phi_A=0.4, phi_B=0.5 ⇒
P_A = (100 + 0.4*80)/0.8 = 165.0, P_B = (80 + 0.5*100)/0.8 = 162.5.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from pe import run_simulation_from_config
from pe.blocks import Edge, Graph, Node, compile_graph, graph_from_config, validate_graph

# J1 anchor constants (mirrors tests/engine/test_joint_dispatch.py).
C_A, C_B = 100.0, 80.0
PHI_A, PHI_B = 0.4, 0.5  # phi_A carries P_B into A; phi_B carries P_A into B
P_A_IDEAL = (C_A + PHI_A * C_B) / (1.0 - PHI_A * PHI_B)  # 165.0
P_B_IDEAL = (C_B + PHI_B * C_A) / (1.0 - PHI_A * PHI_B)  # 162.5

PRICE_ATOL = 1e-6
JOINT_COLUMNS = (
    "Joint Converged",
    "Joint Outer Iterations",
    "Joint Max Normalized Change",
    "Joint Cycle Detected",
)

# The joint_solver node the user drops: relaxation=0.5 (the deliverable's damped
# weight) plus a tight tolerance + generous cap so the STOPPED iterate reaches the
# J1 hand fixed point to atol 1e-6 (three of the five params exercised end to end).
RELAXATION = 0.5
TOLERANCE = 1e-9
MAX_ITERATIONS = 200


def _threshold_market(
    node_prefix: str,
    name: str,
    firm: str,
    block: str,
    threshold: float,
    *,
    order: int,
    scenario_name: str | None = None,
) -> tuple[list[Node], list[Edge]]:
    """One interior single-threshold-block market, drawn against BLOCK_CATALOGUE ports.

    Interior auction (60 < 80 < 100) pins the clearing price AT the shifted
    threshold — the J1 own-price pass-through ``s_m = 1``.
    """
    market_params: dict[str, Any] = {
        "name": name,
        "order": order,
        "price_unit": "USD/tCO2",
        "years": [
            {"year": "2030", "total_cap": 80.0, "auction_mode": "explicit", "auction_offered": 80.0}
        ],
    }
    if scenario_name is not None:
        market_params["scenario_name"] = scenario_name
    nodes = [
        Node(node_prefix, "carbon_market", market_params),
        Node(f"{node_prefix}_pf", "competitive_clearing", {}),
        Node(f"{node_prefix}_ceil", "price_ceiling", {"price_upper_bound": 100000.0}),
        Node(
            f"{node_prefix}_p0",
            "participant",
            {
                "name": firm,
                "initial_emissions": 100.0,
                "free_allocation_ratio": 0.0,
                "penalty_price": 100000.0,
                "abatement_type": "threshold",
                "threshold_cost": 999.0,
                "max_abatement": 0.0,
            },
        ),
        Node(
            f"{node_prefix}_block",
            "technology_option",
            {
                "name": block,
                "abatement_type": "threshold",
                "threshold_cost": threshold,
                "initial_emissions": 100.0,
                "max_abatement": 40.0,
                "free_allocation_ratio": 0.0,
                "penalty_price": 100000.0,
                "max_activity_share": 1.0,
            },
        ),
    ]
    edges = [
        Edge(f"{node_prefix}_pf", "price_formation", node_prefix, "price_formation"),
        Edge(f"{node_prefix}_ceil", "policy", node_prefix, "policies"),
        Edge(f"{node_prefix}_p0", "compliance", node_prefix, "participants"),
        Edge(f"{node_prefix}_block", "option", f"{node_prefix}_p0", "options"),
    ]
    return nodes, edges


def _mac_link(
    link_id: str, from_node: str, to_node: str, phi: float, firm: str, block: str
) -> tuple[Node, list[Edge]]:
    node = Node(
        link_id,
        "market_link",
        {
            "channel": "mac_cost",
            "phi": phi,
            "phi_unit": "1/1",
            "target_participants": [firm],
            "target_technologies": [block],
        },
    )
    edges = [Edge(from_node, "signal", link_id, "from"), Edge(link_id, "link", to_node, "links")]
    return node, edges


def _cyclic_graph() -> Graph:
    """Two threshold markets A,B with market_link A→B AND B→A (the cycle), plus a
    joint_solver node (relaxation=0.5) wired into A's joint_solver port."""
    a_nodes, a_edges = _threshold_market(
        "mA", "A", "A_firm", "blockA", C_A, order=0, scenario_name="cyc"
    )
    b_nodes, b_edges = _threshold_market("mB", "B", "B_firm", "blockB", C_B, order=1)
    # P_A into B (phi_B) and P_B into A (phi_A) — the two back-edges of the cycle.
    l_ab, l_ab_edges = _mac_link("l_ab", "mA", "mB", PHI_B, "B_firm", "blockB")
    l_ba, l_ba_edges = _mac_link("l_ba", "mB", "mA", PHI_A, "A_firm", "blockA")
    js = Node(
        "js",
        "joint_solver",
        {"relaxation": RELAXATION, "tolerance": TOLERANCE, "max_iterations": MAX_ITERATIONS},
    )
    nodes = [*a_nodes, *b_nodes, l_ab, l_ba, js]
    edges = [
        *a_edges,
        *b_edges,
        *l_ab_edges,
        *l_ba_edges,
        Edge("js", "joint_solver", "mA", "joint_solver"),
    ]
    return Graph(nodes=nodes, edges=edges)


def _acyclic_graph() -> Graph:
    """The same two markets, but a SINGLE one-way link A→B and NO joint_solver node."""
    a_nodes, a_edges = _threshold_market(
        "mA", "A", "A_firm", "blockA", C_A, order=0, scenario_name="acyc"
    )
    b_nodes, b_edges = _threshold_market("mB", "B", "B_firm", "blockB", C_B, order=1)
    l_ab, l_ab_edges = _mac_link("l_ab", "mA", "mB", PHI_B, "B_firm", "blockB")
    return Graph(nodes=[*a_nodes, *b_nodes, l_ab], edges=[*a_edges, *b_edges, *l_ab_edges])


def _cyclic_graph_no_joint_solver() -> Graph:
    """The cyclic graph with the joint_solver node removed (block-only-when-dropped)."""
    graph = _cyclic_graph()
    graph.nodes = [n for n in graph.nodes if n.block != "joint_solver"]
    graph.edges = [e for e in graph.edges if e.target_port != "joint_solver"]
    return graph


def _price(summary: pd.DataFrame, scenario_key: str) -> float:
    rows = summary[summary["Scenario"] == scenario_key]
    return float(rows["Equilibrium Carbon Price"].iloc[0])


# ── (a) compile: one joint markets{} scenario with both links + joint_solver ──


def test_cyclic_graph_compiles_to_one_joint_markets_scenario() -> None:
    compiled = compile_graph(_cyclic_graph())
    assert len(compiled["scenarios"]) == 1
    scenario = compiled["scenarios"][0]

    assert scenario["name"] == "cyc"
    assert [m["market_id"] for m in scenario["markets"]] == ["A", "B"]

    # Both back-edges of the cycle survive intact.
    pairs = {(link["from_market"], link["to_market"]) for link in scenario["links"]}
    assert pairs == {("A", "B"), ("B", "A")}

    # The joint_solver block: user-set keys preserved, config_io defaults filled.
    joint = scenario["joint_solver"]
    assert joint["relaxation"] == RELAXATION
    assert joint["tolerance"] == TOLERANCE
    assert joint["max_iterations"] == MAX_ITERATIONS
    assert joint["sweep"] == "gauss_seidel"  # config_io default, not hardcoded here
    assert joint["initial_guess"] == "one_way_seed"


# ── (b) validate: the cycle is legal; R37 silent for two competitive markets ──


def test_cyclic_graph_validates_clean_cycle_is_legal() -> None:
    issues = validate_graph(_cyclic_graph())
    assert not [i for i in issues if i.level == "error"], issues
    assert "R34" not in {i.rule for i in issues}
    assert "R37" not in {i.rule for i in issues if i.level == "warning"}


def _banking_cyclic_graph(relaxation: float) -> Graph:
    """The cyclic graph, but market B is a banking market and the joint_solver
    node carries the given relaxation — the R37 carrier under test."""
    graph = _cyclic_graph()
    banking_pf = graph.node("mB_pf")
    assert banking_pf is not None
    banking_pf.block = "rubin_schennach_banking"
    joint = graph.node("js")
    assert joint is not None
    joint.params["relaxation"] = relaxation
    return graph


def test_r37_fires_via_joint_solver_node_relaxation() -> None:
    """R37 reads the joint_solver COMPOSER node (D2-4 carrier): relaxation=1.0 over
    a banking cycle ⇒ the undamped-hazard WARNING (no link-node hint involved)."""
    warnings = {i.rule for i in validate_graph(_banking_cyclic_graph(1.0)) if i.level == "warning"}
    assert "R37" in warnings


def test_r37_silent_when_joint_solver_node_damps() -> None:
    """A damped joint_solver node (relaxation=0.5) over the same banking cycle keeps
    R37 silent — the composer node governs the SCC's damping."""
    warnings = {i.rule for i in validate_graph(_banking_cyclic_graph(0.5)) if i.level == "warning"}
    assert "R37" not in warnings


# ── (c) solve: dispatch stamps the four Joint columns; prices hit the J1 anchor ──


def test_compiled_cyclic_graph_solves_with_joint_columns_converged() -> None:
    compiled = compile_graph(_cyclic_graph())
    summary, participants = run_simulation_from_config(compiled)

    for column in JOINT_COLUMNS:
        assert column in summary.columns, f"missing guarded column {column!r}"
    assert all(summary["Joint Converged"] == 1.0)
    assert all(summary["Joint Cycle Detected"] == 0.0)

    assert set(summary["Scenario"]) == {"cyc :: A", "cyc :: B"}
    np.testing.assert_allclose(_price(summary, "cyc :: A"), P_A_IDEAL, rtol=0.0, atol=PRICE_ATOL)
    np.testing.assert_allclose(_price(summary, "cyc :: B"), P_B_IDEAL, rtol=0.0, atol=PRICE_ATOL)
    assert set(participants["Scenario"]) == {"cyc :: A", "cyc :: B"}


# ── (d) round-trip: compile -> decompile -> compile is idempotent ────────────


def test_cyclic_graph_round_trips_through_decompile() -> None:
    compiled = compile_graph(_cyclic_graph())
    recompiled = compile_graph(graph_from_config(compiled))
    assert recompiled == compiled


def test_decompiled_cyclic_graph_has_joint_solver_node_on_first_market() -> None:
    compiled = compile_graph(_cyclic_graph())
    decompiled = graph_from_config(compiled)

    joint_nodes = [n for n in decompiled.nodes if n.block == "joint_solver"]
    assert len(joint_nodes) == 1
    assert joint_nodes[0].params["relaxation"] == RELAXATION

    # Wired into a carbon_market's joint_solver in-port (the first market).
    joint_edges = [e for e in decompiled.edges if e.target_port == "joint_solver"]
    assert len(joint_edges) == 1
    target = decompiled.node(joint_edges[0].target)
    assert target is not None and target.block == "carbon_market"

    # Both cyclic back-edges also round-trip as market_link nodes.
    assert len([n for n in decompiled.nodes if n.block == "market_link"]) == 2


# ── (e) inertness witness: no joint_solver node ⇒ no joint_solver key ────────


def test_acyclic_graph_has_no_joint_solver_key() -> None:
    """The inertness witness: an acyclic two-market graph compiles to today's
    markets/links shape with NO joint_solver key."""
    compiled = compile_graph(_acyclic_graph())
    assert len(compiled["scenarios"]) == 1
    scenario = compiled["scenarios"][0]
    assert "markets" in scenario  # still the linked shape
    assert "joint_solver" not in scenario


def test_cyclic_graph_without_joint_solver_node_emits_no_key() -> None:
    """The block appears ONLY when the user drops the node: a legal cycle with no
    joint_solver node still emits both links but NO joint_solver key."""
    compiled = compile_graph(_cyclic_graph_no_joint_solver())
    scenario = compiled["scenarios"][0]
    pairs = {(link["from_market"], link["to_market"]) for link in scenario["links"]}
    assert pairs == {("A", "B"), ("B", "A")}
    assert "joint_solver" not in scenario
