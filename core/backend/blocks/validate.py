"""Structural graph validation — rules R1-R36 (``docs/blocks-composition-rules.md``
R1-R33; ``docs/platform-spec-d0-d1.md`` §3/§7 R34-R36).

Value-level validation (numeric ranges, enum membership, cross-field
consistency once trajectories are applied, ...) is delegated to
``config_io`` normalisation and is *not* duplicated here: this module only
checks what the compiler needs to know before it can safely build a config
(graph shape, port-kind compatibility, cardinalities) and the economically
meaningful composition rules that ``compile_graph`` cannot detect on its own
(mutually-exclusive mechanisms, missing prerequisites, silently-ignored
combinations).

Rule R10 (blocks-composition-rules.md §4): "MSR and CCR both enabled on one
competitive scenario" was an ERROR *until F1 was fixed*
(``solvers/simulation.py`` used to overwrite the CCR cap adjustment with the
MSR one instead of composing them additively). F1 has landed
(``effective_carry = carry_forward_allowances + ccr_adjustment + msr_net``,
see ``solvers/simulation.py`` and ``tests/test_msr_ccr_composition.py``), so
R10 is now ALLOWED — this module intentionally emits nothing for it. Do not
resurrect it as an error without re-breaking F1 first.

R34-R36 (D1-4, ``docs/platform-plan-d0-d1.md`` D1 "GRAPH DISENTANGLEMENT";
binding spec ``docs/platform-spec-d0-d1.md`` §3 rule texts, §7 E8) are
GRAPH-GLOBAL, not per-market: a ``market_link`` edge crosses two
``carbon_market`` nodes, so they run once per graph (:func:`_check_market_links`),
mirroring ``_check_policy_policy_edges``/``_check_unconnected_nodes`` rather
than the per-market ``_rule_r*`` family below. They are DELIBERATELY
redundant with engine/config-tier enforcement (``engine/links.py``'s
``topological_market_order`` for R34's cycle check; ``modules/market_links/
backend/plugin.py``'s ``validate_links`` for R35's channel whitelist and
R36's price_unit check) — the same "check early, structurally, before
compile" doctrine every other R-rule here already follows.

Dependency law: this module imports only ``ets.blocks`` siblings and stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .catalogue import BLOCK_CATALOGUE
from .compile import resolve_year_value
from .graph import Edge, Graph, Node

Level = Literal["error", "warning"]

_MSR_BLOCKS = ("msr_bank_threshold", "kmsr_decree")
_NON_COMPETITIVE_LIKE = ("rubin_schennach_banking", "hotelling", "nash_cournot")
_COMPETITIVE_LIKE = ("competitive_clearing", "forward_transmission")


@dataclass(frozen=True)
class ValidationIssue:
    """One validator finding.

    Args:
        level: ``"error"`` (refuse to run) or ``"warning"`` (run with notice).
        rule: Rule id, e.g. ``"R1"``.
        message: Human-readable explanation.
        node: Attributed node id, if any.
        edge: Attributed edge index (into ``Graph.edges``), if any.
    """

    level: Level
    rule: str
    message: str
    node: str | None = None
    edge: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"level": self.level, "rule": self.rule, "message": self.message}
        if self.node is not None:
            out["node"] = self.node
        if self.edge is not None:
            out["edge"] = self.edge
        return out


def _is_positive_any_year(raw: Any, market_years: list[str]) -> bool:
    if raw is None:
        return False
    from .compile import is_per_year_value

    if is_per_year_value(raw):
        return any(float(v or 0.0) > 0 for v in raw["__per_year__"].values())
    try:
        return float(raw) > 0
    except (TypeError, ValueError):
        return bool(raw)


def validate_graph(graph: Graph) -> list[ValidationIssue]:
    """Structurally validate a graph. Never raises — always returns issues.

    Args:
        graph: The drawn block graph.

    Returns:
        A list of :class:`ValidationIssue`, possibly empty.
    """
    issues: list[ValidationIssue] = []
    node_ids = {n.id for n in graph.nodes}

    _check_unknown_blocks(graph, issues)
    _check_dangling_and_port_kinds(graph, issues, node_ids)
    _check_policy_policy_edges(graph, issues)
    _check_market_links(graph, issues)

    for market_node in graph.nodes:
        if market_node.block != "carbon_market":
            continue
        _validate_market(graph, market_node, issues)

    _check_unconnected_nodes(graph, issues)
    return issues


# ── graph-global structural checks ──────────────────────────────────────


def _check_unknown_blocks(graph: Graph, issues: list[ValidationIssue]) -> None:
    for node in graph.nodes:
        if node.block not in BLOCK_CATALOGUE:
            issues.append(
                ValidationIssue("error", "R3", f"Unknown block id '{node.block}'.", node=node.id)
            )


def _check_dangling_and_port_kinds(
    graph: Graph, issues: list[ValidationIssue], node_ids: set[str]
) -> None:
    for index, edge in enumerate(graph.edges):
        if edge.source not in node_ids or edge.target not in node_ids:
            issues.append(
                ValidationIssue(
                    "error", "R3",
                    f"Dangling edge: '{edge.source}'.{edge.source_port} -> "
                    f"'{edge.target}'.{edge.target_port} references a missing node.",
                    edge=index,
                )
            )
            continue
        source_node = graph.node(edge.source)
        target_node = graph.node(edge.target)
        assert source_node is not None and target_node is not None
        if source_node.block not in BLOCK_CATALOGUE or target_node.block not in BLOCK_CATALOGUE:
            continue
        source_spec = BLOCK_CATALOGUE.get(source_node.block)
        target_spec = BLOCK_CATALOGUE.get(target_node.block)
        out_port = source_spec.port(edge.source_port, "out")
        in_port = target_spec.port(edge.target_port, "in")
        if out_port is None or in_port is None or out_port.kind != in_port.kind:
            issues.append(
                ValidationIssue(
                    "error", "R3",
                    f"Edge '{edge.source}'.{edge.source_port} -> '{edge.target}'.{edge.target_port} "
                    "does not compile to a config field or engine state read (port-kind mismatch).",
                    edge=index,
                )
            )


def _check_policy_policy_edges(graph: Graph, issues: list[ValidationIssue]) -> None:
    for index, edge in enumerate(graph.edges):
        source_node = graph.node(edge.source)
        target_node = graph.node(edge.target)
        if source_node is None or target_node is None:
            continue
        if source_node.block not in BLOCK_CATALOGUE or target_node.block not in BLOCK_CATALOGUE:
            continue
        source_cat = BLOCK_CATALOGUE.get(source_node.block).category
        target_cat = BLOCK_CATALOGUE.get(target_node.block).category
        if source_cat == "policy" and target_cat == "policy":
            issues.append(
                ValidationIssue(
                    "error", "R4",
                    "No user-drawn edges between two policy blocks; their order is engine-fixed.",
                    edge=index,
                )
            )


def _check_unconnected_nodes(graph: Graph, issues: list[ValidationIssue]) -> None:
    connected = {e.source for e in graph.edges} | {e.target for e in graph.edges}
    for node in graph.nodes:
        if node.block == "carbon_market":
            continue
        if node.id not in connected:
            issues.append(
                ValidationIssue("warning", "R-unconnected", f"Node '{node.id}' is not connected to anything.", node=node.id)
            )


# ── market links: R34 (DAG), R35 (channel whitelist + duplicates),
#    R36 (unit declarations) — docs/platform-spec-d0-d1.md §3, §7 ─────────

# Mirrors modules/market_links/backend/plugin.py:ALLOWED_LINK_CHANNELS and
# catalogue.py's own _LINK_CHANNELS — duplicated here only as strings, per
# this module's dependency law (stdlib + blocks siblings only).
_LINK_CHANNELS = frozenset({"mac_cost", "invest_break_even"})


def _market_link_nodes(graph: Graph) -> list[Node]:
    return [n for n in graph.nodes if n.block == "market_link"]


def _resolve_link_endpoint_markets(graph: Graph, link_node: Node) -> tuple[str, str] | None:
    """Resolve one ``market_link`` node's ``(from_market_node_id, to_market_node_id)``.

    Never raises (``validate_graph``'s contract): returns ``None`` when the
    node's cardinality is wrong (not exactly one inbound ``from`` edge and
    one outbound ``link`` edge) — :func:`_rule_r34_link_dag` reports that
    case itself; every other caller treats ``None`` as "already reported,
    skip" (one issue per malformed node, not one per rule).

    Args:
        graph: The drawn block graph.
        link_node: A ``market_link`` node.

    Returns:
        ``(from_node_id, to_node_id)``, or ``None`` if malformed.
    """
    from_edges = graph.edges_into(link_node.id, "from")
    link_edges = [e for e in graph.edges if e.source == link_node.id and e.source_port == "link"]
    if len(from_edges) != 1 or len(link_edges) != 1:
        return None
    return from_edges[0].source, link_edges[0].target


def _rule_r34_link_dag(graph: Graph, link_nodes: list[Node], issues: list[ValidationIssue]) -> None:
    r"""R34: the link graph must be a DAG (self-links and cycles rejected).

    Graph-tier cycle detection, redundant by design with the engine's own
    enforcement (``engine/links.py:topological_market_order``, which owns
    the full Kahn's-algorithm ordering docstring — LaTeX/ASCII/symbols —
    this function mirrors only the DETECTION half, since ``validate_graph``
    reports issues rather than computing a solve order):

    Algorithm:
        LaTeX:
        $$ \text{in-deg}(v) = \big|\{(u,v) : u \to v \in E\}\big|, \qquad
           R_0 = \{v : \text{in-deg}(v) = 0\} $$
        $$ |{\textstyle\bigcup} \text{visited}| \neq |V|
           \;\Longrightarrow\; \text{a cycle remains among the unvisited} $$

        ASCII fallback:
            E = { (from, to) } deduped per market_link edge
            in_deg[v] = number of distinct edges into v
            ready = { v : in_deg[v] == 0 }
            while ready: pop v; emit v; in_deg[w] -= 1 for each edge (v, w);
                         w joins ready when in_deg[w] hits 0
            visited != |V|  =>  a cycle remains among the unvisited markets

        Symbols:
            V : the carbon_market node ids [-]
            E : market_link (from, to) edges, deduped per pair [-]

    Args:
        graph: The drawn block graph.
        link_nodes: Every ``market_link`` node.
        issues: Accumulating issue list (mutated in place).
    """
    market_ids = {n.id for n in graph.nodes if n.block == "carbon_market"}
    edges: list[tuple[str, str]] = []
    for link_node in link_nodes:
        endpoints = _resolve_link_endpoint_markets(graph, link_node)
        if endpoints is None:
            issues.append(
                ValidationIssue(
                    "error", "R34",
                    f"market_link '{link_node.id}' must have exactly one inbound 'from' "
                    "edge (from a carbon_market's 'signal' port) and exactly one outbound "
                    "'link' edge (into a carbon_market's 'links' port).",
                    node=link_node.id,
                )
            )
            continue
        source_id, target_id = endpoints
        if source_id not in market_ids or target_id not in market_ids:
            continue  # port-kind mismatch / dangling — R3 already attributes it
        if source_id == target_id:
            issues.append(
                ValidationIssue(
                    "error", "R34",
                    f"market_link '{link_node.id}': 'from' and 'link' both resolve to "
                    f"market '{source_id}' — self-links are forbidden.",
                    node=link_node.id,
                )
            )
            continue
        edges.append((source_id, target_id))

    successors: dict[str, set[str]] = {m: set() for m in market_ids}
    for source_id, target_id in edges:
        successors[source_id].add(target_id)
    in_degree: dict[str, int] = {m: 0 for m in market_ids}
    for targets in successors.values():
        for target_id in targets:
            in_degree[target_id] += 1

    ready = [m for m in sorted(market_ids) if in_degree[m] == 0]
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for target_id in sorted(successors[node_id]):
            in_degree[target_id] -= 1
            if in_degree[target_id] == 0:
                ready.append(target_id)
    if visited != len(market_ids):
        cyclic = sorted(m for m in market_ids if in_degree[m] > 0)
        issues.append(
            ValidationIssue(
                "error", "R34",
                f"Market link graph has a cycle among {cyclic} — D1 solves DAGs only "
                "(cyclic links are the joint fixed point, D2).",
            )
        )


def _rule_r35_link_whitelist(graph: Graph, link_nodes: list[Node], issues: list[ValidationIssue]) -> None:
    """R35: demand-side channel whitelist only; duplicate (source, target, channel) rejected."""
    seen: dict[tuple[str, str, str], str] = {}
    for link_node in link_nodes:
        channel = link_node.params.get("channel")
        if channel not in _LINK_CHANNELS:
            issues.append(
                ValidationIssue(
                    "error", "R35",
                    f"market_link '{link_node.id}': channel must be one of "
                    f"{sorted(_LINK_CHANNELS)} (demand-side only — a price-indexed supply "
                    "instrument is a SupplyRule inside its own market's fixed point, never "
                    f"a link), got {channel!r}.",
                    node=link_node.id,
                )
            )
            continue
        endpoints = _resolve_link_endpoint_markets(graph, link_node)
        if endpoints is None:
            continue  # R34 already reported the malformed cardinality
        key = (endpoints[0], endpoints[1], channel)
        if key in seen:
            issues.append(
                ValidationIssue(
                    "error", "R35",
                    f"market_link '{link_node.id}' duplicates market_link '{seen[key]}': "
                    f"both link '{endpoints[0]}' -> '{endpoints[1]}' on channel {channel!r} "
                    "— duplicate (source, target, channel) is rejected (distinct SOURCES "
                    "into one target are fine and sum order-invariantly).",
                    node=link_node.id,
                )
            )
        else:
            seen[key] = link_node.id


def _rule_r36_link_units(graph: Graph, link_nodes: list[Node], issues: list[ValidationIssue]) -> None:
    """R36: every linked market declares price_unit; every link declares phi_unit."""
    market_by_id = {n.id: n for n in graph.nodes if n.block == "carbon_market"}
    touched: set[str] = set()
    for link_node in link_nodes:
        if not link_node.params.get("phi_unit"):
            issues.append(
                ValidationIssue(
                    "error", "R36",
                    f"market_link '{link_node.id}': phi_unit is required — a silent "
                    "dimensionless fallback is an economic constant hiding in a default "
                    "(spec §2e).",
                    node=link_node.id,
                )
            )
        endpoints = _resolve_link_endpoint_markets(graph, link_node)
        if endpoints is None:
            continue  # R34 already reported the malformed cardinality
        touched.update(m for m in endpoints if m in market_by_id)
    for market_id in sorted(touched):
        market_node = market_by_id[market_id]
        if not market_node.params.get("price_unit"):
            issues.append(
                ValidationIssue(
                    "error", "R36",
                    f"Market '{market_id}' participates in a link but declares no "
                    "price_unit — every linked market must declare price_unit "
                    "(spec §2e/§6).",
                    node=market_id,
                )
            )


def _check_market_links(graph: Graph, issues: list[ValidationIssue]) -> None:
    link_nodes = _market_link_nodes(graph)
    if not link_nodes:
        return
    _rule_r34_link_dag(graph, link_nodes, issues)
    _rule_r35_link_whitelist(graph, link_nodes, issues)
    _rule_r36_link_units(graph, link_nodes, issues)


# ── per-market checks ────────────────────────────────────────────────────


def _validate_market(graph: Graph, market: Node, issues: list[ValidationIssue]) -> None:
    years_grid: list[dict[str, Any]] = list(market.params.get("years") or [])
    year_labels = [str(y.get("year")) for y in years_grid]

    pf_edges = graph.edges_into(market.id, "price_formation")
    _rule_r1(market, pf_edges, issues)

    participant_edges = graph.edges_into(market.id, "participants")
    participant_nodes: list[Node] = [
        n for n in (graph.node(e.source) for e in participant_edges) if n is not None
    ]
    _rule_r2(market, participant_nodes, year_labels, issues)

    if len(pf_edges) != 1:
        return  # remaining rules assume a resolvable price-formation block
    pf_node = graph.node(pf_edges[0].source)
    if pf_node is None or pf_node.block not in BLOCK_CATALOGUE:
        return
    pf_block = pf_node.block

    policy_edges = graph.edges_into(market.id, "policies")
    policy_nodes: list[Node] = [
        n for n in (graph.node(e.source) for e in policy_edges) if n is not None
    ]
    by_block: dict[str, list[Node]] = {}
    for n in policy_nodes:
        by_block.setdefault(n.block, []).append(n)

    exp_edges = graph.edges_into(market.id, "expectations")
    exp_node = graph.node(exp_edges[0].source) if exp_edges else None

    msr_nodes = by_block.get("msr_bank_threshold", []) + by_block.get("kmsr_decree", [])
    ccr_nodes = by_block.get("ccr", [])

    _rule_r5(market, by_block, pf_block, issues)
    _rule_r6(market, by_block, pf_block, years_grid, exp_node, issues)
    _rule_r7(market, by_block, issues)
    _rule_r8(market, msr_nodes, pf_block, issues)
    _rule_r9(market, ccr_nodes, pf_block, issues)
    _rule_r11_r12(market, ccr_nodes, issues)
    _rule_r13(market, pf_node, issues)
    _rule_r14(market, pf_block, years_grid, issues)
    _rule_r15_r16(graph, market, pf_node, pf_block, participant_nodes, msr_nodes, issues)
    _rule_r17_r18(market, pf_node, pf_block, years_grid, issues)
    _rule_r19_r20(market, by_block, pf_node, pf_block, year_labels, issues)
    _rule_r21_r22(market, by_block, pf_block, year_labels, issues)
    _rule_r23(market, pf_node, pf_block, issues)
    _rule_r24_r25(market, by_block, participant_nodes, years_grid, year_labels, issues)
    _rule_r26(market, participant_nodes, by_block, years_grid, year_labels, issues)
    _rule_r27(market, by_block, year_labels, issues)
    _rule_r28_r29(market, exp_node, pf_block, msr_nodes, ccr_nodes, issues)
    _rule_r30(market, policy_nodes, year_labels, issues)
    _rule_r31(market, by_block, issues)
    _rule_r32(market, participant_nodes, issues)
    _rule_r33(market, by_block, pf_block, issues)


def _rule_r1(market: Node, pf_edges: list[Edge], issues: list[ValidationIssue]) -> None:
    if len(pf_edges) == 0:
        issues.append(ValidationIssue("error", "R1", f"Market '{market.id}' has no price-formation block attached.", node=market.id))
    elif len(pf_edges) > 1:
        issues.append(
            ValidationIssue(
                "error", "R1",
                f"Market '{market.id}' has {len(pf_edges)} price-formation blocks attached; exactly one is required.",
                node=market.id,
            )
        )


def _rule_r2(market: Node, participant_nodes: list[Node], year_labels: list[str], issues: list[ValidationIssue]) -> None:
    has_positive = any(
        _is_positive_any_year(n.params.get("initial_emissions", 0.0), year_labels) for n in participant_nodes
    )
    if not participant_nodes or not has_positive or not year_labels:
        issues.append(
            ValidationIssue(
                "error", "R2",
                f"Market '{market.id}' needs >=1 participant with initial_emissions > 0 and >=1 market year.",
                node=market.id,
            )
        )


def _rule_r5(market: Node, by_block: dict[str, list[Node]], pf_block: str, issues: list[ValidationIssue]) -> None:
    for node in by_block.get("kmsr_decree", []):
        if pf_block != "rubin_schennach_banking":
            issues.append(
                ValidationIssue(
                    "error", "R5",
                    f"kmsr_decree '{node.id}' requires the rubin_schennach_banking price-formation block.",
                    node=node.id,
                )
            )


def _rule_r6(
    market: Node,
    by_block: dict[str, list[Node]],
    pf_block: str,
    years_grid: list[dict[str, Any]],
    exp_node: Node | None,
    issues: list[ValidationIssue],
) -> None:
    if pf_block not in (*_COMPETITIVE_LIKE, "nash_cournot"):
        return
    for node in by_block.get("msr_bank_threshold", []):
        any_banking = any(bool(y.get("banking_allowed")) for y in years_grid)
        rule = exp_node.params.get("expectation_rule", "next_year_baseline") if exp_node else "next_year_baseline"
        if not any_banking or rule == "myopic":
            issues.append(
                ValidationIssue(
                    "error", "R6",
                    f"msr_bank_threshold '{node.id}' under {pf_block} requires >=1 year with "
                    "banking_allowed=true and a non-myopic expectations rule.",
                    node=node.id,
                )
            )


def _rule_r7(market: Node, by_block: dict[str, list[Node]], issues: list[ValidationIssue]) -> None:
    for node in by_block.get("msr_bank_threshold", []):
        if float(node.params.get("msr_initial_reserve_mt", 0.0) or 0.0) > 0:
            issues.append(
                ValidationIssue(
                    "error", "R7",
                    f"msr_bank_threshold '{node.id}' sets msr_initial_reserve_mt > 0; that field "
                    "only funds releases under a decree mode (kmsr_decree).",
                    node=node.id,
                )
            )


def _rule_r8(market: Node, msr_nodes: list[Node], pf_block: str, issues: list[ValidationIssue]) -> None:
    if pf_block == "hotelling":
        for node in msr_nodes:
            issues.append(
                ValidationIssue("error", "R8", f"MSR '{node.id}' cannot coexist with Hotelling price formation.", node=node.id)
            )


def _rule_r9(market: Node, ccr_nodes: list[Node], pf_block: str, issues: list[ValidationIssue]) -> None:
    if pf_block not in _COMPETITIVE_LIKE:
        for node in ccr_nodes:
            issues.append(
                ValidationIssue("error", "R9", f"CCR '{node.id}' requires competitive price formation.", node=node.id)
            )


def _rule_r11_r12(market: Node, ccr_nodes: list[Node], issues: list[ValidationIssue]) -> None:
    for node in ccr_nodes:
        ref_e = float(node.params.get("ccr_reference_emissions", 0.0) or 0.0)
        ref_z = float(node.params.get("ccr_reference_abatement_cost", 0.0) or 0.0)
        if ref_e == 0.0 and ref_z == 0.0:
            issues.append(
                ValidationIssue("error", "R11", f"CCR '{node.id}' is enabled with both reference values at 0 (inert).", node=node.id)
            )
        phi_e = float(node.params.get("ccr_phi_emissions", 0.0) or 0.0)
        phi_z = float(node.params.get("ccr_phi_abatement_cost", 0.0) or 0.0)
        if phi_e > 0 or phi_z < 0:
            issues.append(
                ValidationIssue(
                    "warning", "R12",
                    f"CCR '{node.id}' has phi signs opposite the paper's optimum (phi_e>0 or phi_z<0).",
                    node=node.id,
                )
            )


def _rule_r13(market: Node, pf_node: Node, issues: list[ValidationIssue]) -> None:
    if pf_node.block != "forward_transmission":
        return
    lam = pf_node.params.get("forward_transmission_lambda")
    if lam is None:
        issues.append(
            ValidationIssue("error", "R13", f"forward_transmission '{pf_node.id}' requires forward_transmission_lambda in [0,1].", node=pf_node.id)
        )
    elif not 0.0 <= float(lam) <= 1.0:
        issues.append(
            ValidationIssue("error", "R13", f"forward_transmission '{pf_node.id}' lambda {lam} out of [0,1].", node=pf_node.id)
        )


def _rule_r14(market: Node, pf_block: str, years_grid: list[dict[str, Any]], issues: list[ValidationIssue]) -> None:
    if pf_block != "hotelling":
        return
    budget_sum = sum(float(y.get("carbon_budget", 0.0) or 0.0) for y in years_grid)
    cap_sum = sum(float(y.get("total_cap", 0.0) or 0.0) for y in years_grid)
    if budget_sum <= 0 and cap_sum <= 0:
        issues.append(
            ValidationIssue("error", "R14", f"Market '{market.id}': hotelling requires sum(carbon_budget) > 0 or sum(total_cap) > 0.", node=market.id)
        )
    elif budget_sum <= 0:
        issues.append(
            ValidationIssue(
                "warning", "R14",
                f"Market '{market.id}': hotelling has no carbon_budget; falling back to sum(total_cap).",
                node=market.id,
            )
        )


def _rule_r15_r16(
    graph: Graph,
    market: Node,
    pf_node: Node,
    pf_block: str,
    participant_nodes: list[Node],
    msr_nodes: list[Node],
    issues: list[ValidationIssue],
) -> None:
    if pf_block != "nash_cournot":
        return
    strategic_edges = [e for e in graph.edges if e.target == pf_node.id and e.target_port == "strategic"]
    if strategic_edges:
        participant_names = {n.params.get("name", "") for n in participant_nodes}
        strategic_names = []
        for e in strategic_edges:
            n = graph.node(e.source)
            if n is not None:
                strategic_names.append(str(n.params.get("name", "")))
        unknown = [name for name in strategic_names if name not in participant_names]
        if unknown:
            issues.append(
                ValidationIssue(
                    "error", "R15",
                    f"nash_cournot '{pf_node.id}': strategic participants {unknown} are not a subset of market participants.",
                    node=pf_node.id,
                )
            )
    for node in msr_nodes:
        if float(node.params.get("msr_start_year", 0.0) or 0.0) != 0.0:
            issues.append(
                ValidationIssue("warning", "R16", f"MSR '{node.id}' msr_start_year is ignored on the Nash path.", node=node.id)
            )


def _rule_r17_r18(
    market: Node, pf_node: Node, pf_block: str, years_grid: list[dict[str, Any]], issues: list[ValidationIssue]
) -> None:
    if pf_block != "rubin_schennach_banking":
        return
    if any(bool(y.get("banking_allowed")) for y in years_grid):
        issues.append(
            ValidationIssue(
                "warning", "R17",
                f"Market '{market.id}': banking approach with year-level banking_allowed=true "
                "risks a second, uncoordinated participant-level bank (F5).",
                node=market.id,
            )
        )
    if any(bool(y.get("borrowing_allowed")) for y in years_grid):
        issues.append(
            ValidationIssue("error", "R18", f"Market '{market.id}': banking approach forbids borrowing_allowed=true.", node=market.id)
        )


def _rule_r19_r20(
    market: Node,
    by_block: dict[str, list[Node]],
    pf_node: Node,
    pf_block: str,
    year_labels: list[str],
    issues: list[ValidationIssue],
) -> None:
    for node in by_block.get("hoarding", []):
        raw = node.params.get("hoarding_inflow", 0.0)
        active = _is_positive_any_year(raw, year_labels)
        if not active:
            continue
        if pf_block != "rubin_schennach_banking":
            issues.append(
                ValidationIssue("error", "R19", f"hoarding '{node.id}' requires the rubin_schennach_banking block.", node=node.id)
            )
        elif bool(pf_node.params.get("banking_strict_no_arbitrage", True)):
            issues.append(
                ValidationIssue(
                    "warning", "R20",
                    f"hoarding '{node.id}' under banking_strict_no_arbitrage=true likely falls back to the static case.",
                    node=node.id,
                )
            )


def _rule_r21_r22(
    market: Node, by_block: dict[str, list[Node]], pf_block: str, year_labels: list[str], issues: list[ValidationIssue]
) -> None:
    if pf_block == "rubin_schennach_banking":
        for node in by_block.get("price_ceiling", []):
            issues.append(
                ValidationIssue("warning", "R21", f"price_ceiling '{node.id}' is advisory-only in-window under banking.", node=node.id)
            )
    if pf_block in ("rubin_schennach_banking", "hotelling", "forward_transmission"):
        for node in by_block.get("auction_reserve", []):
            raw = node.params.get("unsold_treatment", "reserve")
            for year in year_labels:
                if resolve_year_value(raw, year, "reserve") == "carry_forward":
                    issues.append(
                        ValidationIssue(
                            "warning", "R22",
                            f"auction_reserve '{node.id}': unsold_treatment=carry_forward is not "
                            f"implemented under {pf_block}.",
                            node=node.id,
                        )
                    )
                    break


def _rule_r23(market: Node, pf_node: Node, pf_block: str, issues: list[ValidationIssue]) -> None:
    if pf_block != "rubin_schennach_banking":
        return
    discount = float(pf_node.params.get("discount_rate", 0.04) or 0.0)
    premium = float(pf_node.params.get("risk_premium", 0.0) or 0.0)
    if discount + premium < 0:
        issues.append(
            ValidationIssue("error", "R23", f"Market '{market.id}': discount_rate + risk_premium < 0 under banking.", node=market.id)
        )


def _rule_r24_r25(
    market: Node,
    by_block: dict[str, list[Node]],
    participant_nodes: list[Node],
    years_grid: list[dict[str, Any]],
    year_labels: list[str],
    issues: list[ValidationIssue],
) -> None:
    ceiling_nodes = by_block.get("price_ceiling", [])
    reserve_nodes = by_block.get("auction_reserve", [])
    for year in year_labels:
        ceiling = 100.0
        for node in ceiling_nodes:
            ceiling = resolve_year_value(node.params.get("price_upper_bound", 100.0), year, 100.0)
        for node in reserve_nodes:
            reserve_price = resolve_year_value(node.params.get("auction_reserve_price", 0.0), year, 0.0)
            if float(reserve_price or 0.0) > float(ceiling or 0.0):
                issues.append(
                    ValidationIssue(
                        "error", "R24",
                        f"auction_reserve '{node.id}' year '{year}': auction_reserve_price "
                        f"({reserve_price}) exceeds price_upper_bound ({ceiling}).",
                        node=node.id,
                    )
                )
    if not ceiling_nodes:
        max_penalty = max(
            (float(n.params.get("penalty_price", 0.0) or 0.0) for n in participant_nodes), default=0.0
        )
        any_auction = any(float(y.get("auction_offered", 0.0) or 0.0) > 0 for y in years_grid)
        if max_penalty == 0.0 and any_auction:
            issues.append(
                ValidationIssue(
                    "error", "R25",
                    f"Market '{market.id}': no price_ceiling block and every participant's "
                    "penalty_price is 0 in a year with auction_offered > 0 (unbounded bracket).",
                    node=market.id,
                )
            )


def _rule_r26(
    market: Node,
    participant_nodes: list[Node],
    by_block: dict[str, list[Node]],
    years_grid: list[dict[str, Any]],
    year_labels: list[str],
    issues: list[ValidationIssue],
) -> None:
    cancellation_nodes = by_block.get("cancellation", [])
    for year_entry in years_grid:
        year = str(year_entry.get("year"))
        free_alloc = 0.0
        for n in participant_nodes:
            ratio = resolve_year_value(n.params.get("free_allocation_ratio", 0.0), year, 0.0)
            emissions = resolve_year_value(n.params.get("initial_emissions", 0.0), year, 0.0)
            free_alloc += float(ratio or 0.0) * float(emissions or 0.0)
        auction = float(year_entry.get("auction_offered", 0.0) or 0.0)
        reserved = float(year_entry.get("reserved_allowances", 0.0) or 0.0)
        cancelled = 0.0
        for node in cancellation_nodes:
            cancelled += float(resolve_year_value(node.params.get("cancelled_allowances", 0.0), year, 0.0) or 0.0)
        total_cap = float(year_entry.get("total_cap", 0.0) or 0.0)
        if total_cap > 0 and (free_alloc + auction + reserved + cancelled) - total_cap > 1e-6:
            issues.append(
                ValidationIssue(
                    "error", "R26",
                    f"Market '{market.id}' year '{year}': allowance supply exceeds total_cap.",
                    node=market.id,
                )
            )
    shares: dict[str, float] = {}
    for n in participant_nodes:
        group = str(n.params.get("sector_group", "") or "")
        if not group:
            continue
        shares[group] = shares.get(group, 0.0) + float(n.params.get("sector_allocation_share", 0.0) or 0.0)
    for group, total in shares.items():
        if total - 1.0 > 1e-9:
            issues.append(
                ValidationIssue(
                    "error", "R26",
                    f"Market '{market.id}': sector '{group}' sector_allocation_share sums to {total} (> 1).",
                    node=market.id,
                )
            )


def _rule_r27(market: Node, by_block: dict[str, list[Node]], year_labels: list[str], issues: list[ValidationIssue]) -> None:
    has_floor = bool(by_block.get("price_floor"))
    for node in by_block.get("auction_reserve", []):
        raw = node.params.get("unsold_treatment", "reserve")
        for year in year_labels:
            if resolve_year_value(raw, year, "reserve") == "cancel" and not has_floor:
                issues.append(
                    ValidationIssue(
                        "warning", "R27",
                        f"auction_reserve '{node.id}': unsold_treatment=cancel with no price_floor block; confirm intent.",
                        node=node.id,
                    )
                )
                break


def _rule_r28_r29(
    market: Node,
    exp_node: Node | None,
    pf_block: str,
    msr_nodes: list[Node],
    ccr_nodes: list[Node],
    issues: list[ValidationIssue],
) -> None:
    if exp_node is None:
        return
    if pf_block in ("rubin_schennach_banking", "hotelling", "forward_transmission"):
        issues.append(
            ValidationIssue(
                "warning", "R28",
                f"expectations '{exp_node.id}' is attached under {pf_block}, which does not consume it.",
                node=exp_node.id,
            )
        )
    rule = exp_node.params.get("expectation_rule", "next_year_baseline")
    if rule == "perfect_foresight" and (msr_nodes or ccr_nodes):
        issues.append(
            ValidationIssue(
                "warning", "R29",
                f"expectations '{exp_node.id}': perfect_foresight excludes MSR/CCR from its fixed point.",
                node=exp_node.id,
            )
        )


def _rule_r30(market: Node, policy_nodes: list[Node], year_labels: list[str], issues: list[ValidationIssue]) -> None:
    first_year = year_labels[0] if year_labels else None
    for node in policy_nodes:
        announced = node.params.get("announced")
        if not announced:
            continue
        announced = str(announced)
        if announced not in year_labels:
            issues.append(
                ValidationIssue(
                    "error", "R30",
                    f"'{node.id}': announced year '{announced}' is not one of the market's years.",
                    node=node.id,
                )
            )
        elif node.block == "msr_bank_threshold" and announced != first_year:
            issues.append(
                ValidationIssue(
                    "warning", "R30",
                    f"msr_bank_threshold '{node.id}': a policy-event splice at '{announced}' resets the bank_threshold pool.",
                    node=node.id,
                )
            )


def _rule_r31(market: Node, by_block: dict[str, list[Node]], issues: list[ValidationIssue]) -> None:
    for node in by_block.get("cbam", []):
        eua_price = node.params.get("eua_price", 0.0) or 0.0
        eua_prices = node.params.get("eua_prices") or {}
        eua_price_ensemble = node.params.get("eua_price_ensemble") or {}
        flat_zero = not is_per_year_truthy(eua_price) and not eua_prices and not eua_price_ensemble
        if flat_zero:
            issues.append(
                ValidationIssue("warning", "R31", f"cbam '{node.id}': all reference prices are 0.", node=node.id)
            )


def is_per_year_truthy(raw: Any) -> bool:
    from .compile import is_per_year_value

    if is_per_year_value(raw):
        return any(float(v or 0.0) != 0.0 for v in raw["__per_year__"].values())
    try:
        return float(raw or 0.0) != 0.0
    except (TypeError, ValueError):
        return bool(raw)


def _rule_r32(market: Node, participant_nodes: list[Node], issues: list[ValidationIssue]) -> None:
    for n in participant_nodes:
        po = float(n.params.get("production_output", 0.0) or 0.0)
        bei = float(n.params.get("benchmark_emission_intensity", 0.0) or 0.0)
        if (po > 0) != (bei > 0):
            issues.append(
                ValidationIssue(
                    "warning", "R32",
                    f"participant '{n.id}': OBA fields half-set (production_output={po}, "
                    f"benchmark_emission_intensity={bei}); the override never fires.",
                    node=n.id,
                )
            )


def _rule_r33(
    market: Node, by_block: dict[str, list[Node]], pf_block: str, issues: list[ValidationIssue]
) -> None:
    for node in by_block.get("endogenous_investment", []):
        if pf_block not in ("competitive_clearing", "rubin_schennach_banking"):
            issues.append(
                ValidationIssue(
                    "error", "R33",
                    f"endogenous_investment '{node.id}' requires competitive_clearing or "
                    f"rubin_schennach_banking price formation (got '{pf_block}'). v1 approach "
                    "coverage is competitive + banking only; other approaches raise a loud "
                    "ValueError at normalize (docs/invest-feedback-spec.md D1.3; "
                    "docs/invest-feedback-plan.md 'v1 approach coverage').",
                    node=node.id,
                )
            )
