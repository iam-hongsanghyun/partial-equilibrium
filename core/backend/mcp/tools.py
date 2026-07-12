"""Stateless tool implementations behind the MCP composer server.

Design principle: **tools are stateless; the graph document is the
conversation state.** Every mutating function here takes a graph JSON dict
(the wire schema of ``docs/blocks-graph-plan.md`` §2 —
:class:`~pe.blocks.graph.Graph`) and returns the updated graph plus fresh
validation issues; nothing is held server-side between calls. The calling AI
assistant holds the graph dict across turns, passes it back into the next
tool call, and narrates what changed — exactly the same shape
``pe.web.api``'s ``/api/graph/*`` endpoints already use, so a graph built
through this server round-trips through the web composer (and vice versa)
with no translation.

These functions are plain, synchronous, and side-effect-free except for
``save_model`` (registry file I/O, via ``pe.model_store``) — they are
imported directly by ``pe.mcp.server`` (wrapped as MCP tools) and by
``tests/apps/mcp/test_mcp_composer.py`` (exercised directly, no MCP
transport involved).

Dependency law: same as any T5 app — this module may import
``pe.blocks``, ``pe.model_store``, ``pe.engine``, and stdlib.
"""

from __future__ import annotations

from typing import Any

from .. import model_store
from ..blocks import BLOCK_CATALOGUE, Edge, Graph, Node, validate_graph
from ..blocks.serialize import serialize_block, serialize_catalogue
from ..engine import run_simulation_from_config
from .compact import compact_run_summary, describe_model_entry
from .suggestions import next_steps_for

# ── new_graph()'s blank skeleton ─────────────────────────────────────────
# Minimum-viable graph per docs/blocks-composition-rules.md §3: >=1
# participant -> >=1 market year -> exactly one price-formation block.
# Every numeric default below is chosen to satisfy the composition rules
# out of the box (total_cap == free + auction via auction_mode
# "derive_from_cap"; penalty_price > price_lower_bound for R25; see that
# doc's "Defaults and minimum viable graph" section for the full rationale)
# rather than being an arbitrary placeholder.
_SKELETON_YEAR = "2026"
_SKELETON_TOTAL_CAP_MT = 100.0
_SKELETON_INITIAL_EMISSIONS_MT = 100.0
_SKELETON_FREE_ALLOCATION_RATIO = 0.5
_SKELETON_PENALTY_PRICE = 150.0
_SKELETON_MAX_ABATEMENT_MT = 40.0
_SKELETON_COST_SLOPE = 2.0


def _minimal_skeleton() -> Graph:
    """A fresh, validation-clean minimum-viable graph (see module comment)."""
    nodes = [
        Node(
            "market",
            "carbon_market",
            {
                "name": "New Model",
                "years": [
                    {
                        "year": _SKELETON_YEAR,
                        "total_cap": _SKELETON_TOTAL_CAP_MT,
                        "auction_mode": "derive_from_cap",
                        "banking_allowed": False,
                    }
                ],
            },
        ),
        Node("pf", "competitive_clearing", {}),
        Node(
            "p1",
            "participant",
            {
                "name": "Participant 1",
                "order": 0,
                "initial_emissions": _SKELETON_INITIAL_EMISSIONS_MT,
                "free_allocation_ratio": _SKELETON_FREE_ALLOCATION_RATIO,
                "penalty_price": _SKELETON_PENALTY_PRICE,
                "abatement_type": "linear",
                "max_abatement": _SKELETON_MAX_ABATEMENT_MT,
                "cost_slope": _SKELETON_COST_SLOPE,
            },
        ),
    ]
    edges = [
        Edge("pf", "price_formation", "market", "price_formation"),
        Edge("p1", "compliance", "market", "participants"),
    ]
    return Graph(nodes=nodes, edges=edges, meta={"canvas": {}})


# ── 1. list_models ───────────────────────────────────────────────────────
#
# Shared with the governor server: ``pe.mcp.models_tools`` registers this
# same function as its own ``list_models`` tool (see that module's docstring)
# rather than re-implementing it — both servers list the identical registry.


def list_models() -> dict[str, Any]:
    """List every runnable model available to start or resume from.

    Covers the bundled examples under ``examples/`` and every model saved to
    the shared registry under ``user-scenarios/`` (by this server's
    ``save_model``, or by the web composer's "Save model") — the same
    registry directory, so a model saved from either place shows up here.

    Returns:
        ``{"models": [{"id", "name", "source" ("example"|"registry"),
        "features", "approach", "description"}, ...]}``. ``id`` is what
        ``new_graph(template_id=...)`` accepts to load a model onto the
        (conversational) canvas.
    """
    models = [
        describe_model_entry(model_id, "example", config)
        for model_id, config in model_store.iter_examples()
    ]
    models += [
        describe_model_entry(model_id, "registry", config)
        for model_id, config in model_store.iter_registry_models()
    ]
    return {"models": models}


# ── 2. list_blocks / describe_block ──────────────────────────────────────


def list_blocks(category: str | None = None) -> dict[str, Any]:
    """List the block catalogue: every drawable block and its wire metadata.

    Args:
        category: If given, only blocks in this category (``"market"``,
            ``"price_formation"``, ``"policy"``, ``"expectations"``,
            ``"participants"``, or ``"analysis"``); otherwise every block.

    Returns:
        ``{"blocks": [...]}`` — one entry per block:
        ``{"id", "label", "category", "doc", "params", "ports",
        "constraints"}``. Each param carries its type/default/unit/bounds;
        ``constraints`` lists ``requires``/``excludes`` relationships to
        other block ids.
    """
    return {"blocks": serialize_catalogue(BLOCK_CATALOGUE, category=category)}


def describe_block(block_id: str) -> dict[str, Any]:
    """Full metadata for one block: params, ports, requires/excludes, doc.

    Args:
        block_id: A catalogue block id (see ``list_blocks``).

    Returns:
        One block's wire dict (see ``list_blocks``).

    Raises:
        ValueError: ``block_id`` is not in the catalogue.
    """
    if block_id not in BLOCK_CATALOGUE:
        raise ValueError(f"Unknown block id '{block_id}'. Call list_blocks() to see valid ids.")
    return serialize_block(BLOCK_CATALOGUE.get(block_id))


# ── 3. new_graph ──────────────────────────────────────────────────────────


def new_graph(template_id: str | None = None) -> dict[str, Any]:
    """Start a graph: a blank minimum-viable skeleton, or load a model.

    Args:
        template_id: ``None`` for a blank skeleton (one participant, one
            market year, competitive clearing — already ``check()``-clean).
            Otherwise a model id from ``list_models()`` (an example stem or
            a ``"user_<slug>"`` registry id): the model's original composer
            graph is loaded (verbatim for a registry model with a saved
            sidecar, decompiled from its config otherwise).

    Returns:
        ``{"graph": <Graph wire dict>}``.

    Raises:
        ModelStoreError: ``template_id`` matches no known model.
    """
    if template_id is None:
        return {"graph": _minimal_skeleton().to_dict()}
    graph = model_store.resolve_model_graph(template_id)
    return {"graph": graph.to_dict()}


# ── 4. add_block ──────────────────────────────────────────────────────────


def _market_nodes(graph: Graph) -> list[Node]:
    return [n for n in graph.nodes if n.block == "carbon_market"]


def _resolve_target_market(graph: Graph, target_market: str | None) -> Node | None:
    """Disambiguate which ``carbon_market`` node ``add_block`` should wire into.

    Returns ``None`` only when the graph has no market yet at all (a
    recoverable state — the new node is still added, just left unconnected).

    Raises:
        ValueError: ``target_market`` was given but isn't a ``carbon_market``
            node in this graph, or was omitted while the graph has more than
            one market (a genuine ambiguity only the caller can resolve).
    """
    if target_market is not None:
        node = graph.node(target_market)
        if node is None or node.block != "carbon_market":
            raise ValueError(
                f"target_market '{target_market}' is not a carbon_market node in this graph."
            )
        return node
    markets = _market_nodes(graph)
    if len(markets) == 1:
        return markets[0]
    if not markets:
        return None
    ids = ", ".join(n.id for n in markets)
    raise ValueError(
        f"This graph has {len(markets)} carbon_market nodes ({ids}); pass "
        "target_market=<id> to say which one."
    )


def _fresh_node_id(graph: Graph, block_id: str) -> str:
    existing = {n.id for n in graph.nodes}
    if block_id not in existing:
        return block_id
    suffix = 2
    while f"{block_id}_{suffix}" in existing:
        suffix += 1
    return f"{block_id}_{suffix}"


def add_block(
    graph: dict[str, Any],
    block_id: str,
    params: dict[str, Any] | None = None,
    target_market: str | None = None,
    *,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Add a block node, and wire its one obvious edge into a market.

    The "obvious edge" is generic, driven by the catalogue's port ``kind``s,
    not hardcoded per block: whichever of the new block's output ports has a
    ``kind`` matching one of ``carbon_market``'s input ports (e.g. a
    ``participant``'s ``compliance`` output -> the market's ``participants``
    input; any policy block's ``policy`` output -> ``policies``; any
    price-formation block's ``price_formation`` output ->
    ``price_formation``). Blocks with no such port (``carbon_market`` itself,
    ``technology_option`` — which attaches to a *participant*, not a market)
    are added unconnected; wire those by editing the returned graph's
    ``edges`` directly.

    Singular ports (cardinality ``"1"``/``"0..1"``, e.g. ``price_formation``,
    ``expectations``): if the port already has an edge, the new one is wired
    ANYWAY by default (not replacing it) — this deliberately creates a
    structural conflict that ``check()`` surfaces (e.g. R1, "more than one
    price-formation block"), so the AI can ask the user which one should
    stay rather than silently guessing. Pass ``replace_existing=True`` to
    instead remove the old edge before wiring the new one.

    Args:
        graph: Current graph document (``Graph.to_dict()`` shape).
        block_id: A catalogue block id (see ``list_blocks``).
        params: Initial param values for the new node (see
            ``describe_block`` for each param's name/type/default).
        target_market: Which ``carbon_market`` node to wire into. Required
            only when the graph has more than one market; inferred
            automatically when there's exactly one.
        replace_existing: If the obvious edge's target port already has an
            edge and is singular-cardinality, remove it before wiring the
            new one instead of wiring both.

    Returns:
        ``{"graph", "node_id", "issues", "notes"}`` — ``node_id`` is the
        added node's id (``block_id``, or ``f"{block_id}_2"`` etc. on
        collision); ``notes`` explains any auto-wiring decision made (or
        skipped) beyond the plain edge-add.

    Raises:
        ValueError: Unknown ``block_id``, or an unresolvable
            ``target_market`` (see ``_resolve_target_market``).
    """
    g = Graph.from_dict(graph)
    if block_id not in BLOCK_CATALOGUE:
        raise ValueError(f"Unknown block id '{block_id}'. Call list_blocks() to see valid ids.")
    spec = BLOCK_CATALOGUE.get(block_id)

    node_id = _fresh_node_id(g, block_id)
    g.nodes.append(Node(node_id, block_id, dict(params or {})))

    notes: list[str] = []
    if block_id != "carbon_market":
        market = _resolve_target_market(g, target_market)
        if market is None:
            notes.append(
                f"No carbon_market node exists yet in this graph — '{node_id}' was added "
                "unconnected. Add a carbon_market block first, then reconnect it."
            )
        else:
            market_spec = BLOCK_CATALOGUE.get("carbon_market")
            candidates = [
                out_port
                for out_port in spec.out_ports()
                if any(out_port.kind == in_port.kind for in_port in market_spec.in_ports())
            ]
            if len(candidates) == 1:
                out_port = candidates[0]
                in_port = next(p for p in market_spec.in_ports() if p.kind == out_port.kind)
                existing = g.edges_into(market.id, in_port.name)
                if existing and in_port.cardinality in ("1", "0..1"):
                    if replace_existing:
                        g.edges = [e for e in g.edges if e not in existing]
                        notes.append(
                            f"Removed the existing '{in_port.name}' connection on "
                            f"'{market.id}' before wiring '{node_id}'."
                        )
                    else:
                        notes.append(
                            f"'{market.id}' already has a '{in_port.name}' block attached; "
                            f"'{node_id}' was wired anyway, which check() will flag as a "
                            "conflict — call add_block(..., replace_existing=True) to swap "
                            "it instead."
                        )
                g.edges.append(Edge(node_id, out_port.name, market.id, in_port.name))
            elif not candidates:
                notes.append(
                    f"'{node_id}' has no port that attaches directly to a market; wire it "
                    "by adding an edge to the graph document."
                )

    issues = validate_graph(g)
    return {
        "graph": g.to_dict(),
        "node_id": node_id,
        "issues": [issue.to_dict() for issue in issues],
        "notes": notes,
    }


# ── 5. set_params / remove_node ──────────────────────────────────────────


def set_params(graph: dict[str, Any], node_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """Merge param values into one node.

    Args:
        graph: Current graph document.
        node_id: The node to update.
        params: Values to merge into the node's params. A ``None`` value
            removes that key (reverting the param to its catalogue default)
            rather than literally setting it to ``None``.

    Returns:
        ``{"graph", "issues"}``.

    Raises:
        ValueError: ``node_id`` is not in this graph.
    """
    g = Graph.from_dict(graph)
    node = g.node(node_id)
    if node is None:
        raise ValueError(f"Unknown node id '{node_id}'.")
    for key, value in params.items():
        if value is None:
            node.params.pop(key, None)
        else:
            node.params[key] = value
    issues = validate_graph(g)
    return {"graph": g.to_dict(), "issues": [issue.to_dict() for issue in issues]}


def remove_node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    """Remove one node and every edge touching it.

    Args:
        graph: Current graph document.
        node_id: The node to remove.

    Returns:
        ``{"graph", "issues"}``.

    Raises:
        ValueError: ``node_id`` is not in this graph.
    """
    g = Graph.from_dict(graph)
    if g.node(node_id) is None:
        raise ValueError(f"Unknown node id '{node_id}'.")
    g.nodes = [n for n in g.nodes if n.id != node_id]
    g.edges = [e for e in g.edges if e.source != node_id and e.target != node_id]
    issues = validate_graph(g)
    return {"graph": g.to_dict(), "issues": [issue.to_dict() for issue in issues]}


# ── 6. check ──────────────────────────────────────────────────────────────


def check(graph: dict[str, Any]) -> dict[str, Any]:
    """Validate a graph and translate every ERROR into an actionable question.

    Args:
        graph: Current graph document.

    Returns:
        ``{"ok": bool, "issues": [...], "next_steps": [...]}``. ``issues``
        is the raw ``validate_graph`` output (rule id, level, message, node/
        edge attribution). ``next_steps`` is derived from it: one
        ``{"rule", "node", "message", "suggestion"}`` per ERROR-level issue
        whose rule has a mapped suggestion (``pe.mcp.suggestions``) — a
        plain-language, typically yes/no-phrased fix the AI should ask the
        user about before applying, never apply silently.
    """
    g = Graph.from_dict(graph)
    issues = validate_graph(g)
    return {
        "ok": not any(issue.level == "error" for issue in issues),
        "issues": [issue.to_dict() for issue in issues],
        "next_steps": next_steps_for(issues),
    }


# ── 7. run_model ──────────────────────────────────────────────────────────


def run_model(graph: dict[str, Any], scenario: str | None = None) -> dict[str, Any]:
    """Compile and run a graph, returning a compact per-year result summary.

    Args:
        graph: Current graph document. Must be ``check()``-clean (no
            ERROR-level issues) — this calls the same validate-then-compile
            step as ``check()``/``save_model``.
        scenario: If given, only that scenario's results are returned.

    Returns:
        ``{"ok": True, "scenarios": {name: {"years": [...], "total_years",
        "truncated"}}}`` (plus a top-level ``"flow"`` key when non-default,
        D0-R2) — see ``pe.mcp.compact.compact_run_summary`` for exactly
        which columns each year row carries. Never a raw DataFrame, and
        never more than 12 years per scenario (older years are dropped,
        with ``"truncated": true`` marking it).

    Raises:
        ModelStoreError: The graph has ERROR-level validation issues (call
            ``check()`` first and resolve them).
        ValueError: ``scenario`` doesn't match any scenario the run produced.
    """
    g = Graph.from_dict(graph)
    config = model_store.compile_graph_or_raise(g)
    summary_df, _participant_df = run_simulation_from_config(config)
    return {"ok": True, **compact_run_summary(summary_df, scenario=scenario, config=config)}


# ── 8. save_model ─────────────────────────────────────────────────────────


def save_model(graph: dict[str, Any], name: str) -> dict[str, Any]:
    """Save a graph to the shared model registry.

    Args:
        graph: Current graph document. Must be ``check()``-clean.
        name: Display name for the saved model.

    Returns:
        ``{"id", "name", "note"}`` — ``id`` is ``"user_<slug>"``, the same
        id ``list_models()``/``new_graph(template_id=...)`` accept.

    Raises:
        ModelStoreError: Empty ``name``, or the graph has ERROR-level
            validation issues.
    """
    g = Graph.from_dict(graph)
    saved = model_store.save_graph_as_model(g, name)
    return {
        "id": saved.id,
        "name": saved.name,
        "note": (
            f"Saved as '{saved.id}'. It now appears in run.command's template "
            "picker and pe.command's model list."
        ),
    }
