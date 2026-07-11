"""Deterministic graph -> scenario-config dict compiler.

Implements the compile step of ``docs/blocks-graph-plan.md`` §2:

1. Each ``carbon_market`` node becomes one entry in ``{"scenarios": [...]}``,
   sorted by ``params["order"]`` then node id — see the GRAPH
   DISENTANGLEMENT note below for what "one entry" means once ``market_link``
   edges are drawn.
2. The market's ``price_formation`` edge (cardinality exactly 1) merges its
   scenario-level keys.
3. Each attached policy/expectations block merges its keys.
4. Participants attach via ``compliance`` edges into ``years[].participants``,
   ordered by ``params["order"]`` then node id; ``technology_option`` edges
   append ``technology_options``; ``strategic`` edges populate
   ``nash_strategic_participants`` (sorted by participant name).
5. The assembled dict passes through ``config_io.normalize_config`` — the
   single value validator — before being returned.

Ambiguity resolution (plan §2): edge array order carries no meaning; all
ordering comes from explicit ``order`` params with node-id tiebreak. Two
blocks writing the same config key on one market is a compile error, never
last-write-wins.

Per-year values: any ``ParamSpec`` (year-scope, or participant-scope inside
a market with varying yearly data) may be given either a plain value
(broadcast to every year of the market) or a per-year override map
``{"__per_year__": {year_label: value}}`` — see :func:`per_year_value` /
:func:`resolve_year_value`. This is the one generic mechanism the compiler
uses everywhere a field can vary by year; it applies uniformly to any
config_key, not just the ones the plan calls out by name.

Deliberate scope reduction: policy blocks carry an optional ``announced``
param (plan §1 "Policy timing") for validation (``validate.py`` R30), but
this compiler does not yet synthesise ``policy_events[]`` from it — that is
plan §2 step 3's generative direction and is deferred. ``policy_events`` is
instead round-tripped verbatim as an opaque pass-through param on the
``carbon_market`` node (see ``decompile.py``), which is sufficient for every
current example.

GRAPH DISENTANGLEMENT (D1-4, ``docs/platform-plan-d0-d1.md`` D1 "GRAPH
DISENTANGLEMENT"; binding spec ``docs/platform-spec-d0-d1.md`` §3): a
scenario is a CONNECTED COMPONENT of ``carbon_market`` nodes under
``market_link`` edges (:func:`_connected_components`), computed on the
UNDIRECTED graph the link edges induce. A component of size ONE — a
linkless market — is today's semantics EXACTLY: :func:`_compile_market`
runs VERBATIM, unchanged since before D1-4 (every existing example graph
compiles bit-identically; no migration). A component of size >1 compiles
via :func:`_compile_linked_scenario` into one scenario dict shaped
``{"name": ..., "markets": [...], "links": [...]}`` — a market node's OWN
``name`` param becomes its ``market_id`` inside the component (the same
param that means "scenario name" for a size-1 component); the wrapping
scenario's display name comes from the optional ``scenario_name`` param
(must agree across the component when set on more than one node; defaults
to the order-first market's own ``name``).

D2-4 CYCLES-LEGAL (``docs/joint-equilibrium-plan.md`` §4): the ``market_link``
edges of a component may now form a CYCLE (A↔B). The undirected
:func:`_connected_components` grouping already puts a back-edge's endpoints in
one component, so a cyclic component compiles to the SAME ``markets``+``links``
shape as an acyclic one — the cyclic ``links`` array is emitted VERBATIM (the
old "cycle → CompileError" is gone; D2-3's ``dispatch.solve_multi_market_scenario``
routes the cyclic SCC to ``engine.joint.solve_joint_scc``). A ``joint_solver``
node attached to any one market of the component adds the scenario's optional
``joint_solver`` block (:func:`_compile_joint_solver`); absent ⇒ no key, so a
graph without one stays byte-identical.

Dependency law: this module imports only ``ets.blocks`` siblings,
``ets.config_io``, and stdlib.
"""

from __future__ import annotations

from typing import Any

from ..config_io import normalize_config
from .catalogue import BLOCK_CATALOGUE
from .graph import Graph, Node
from .registry import BlockSpec

PER_YEAR_KEY = "__per_year__"

_MARKET_YEAR_GRID_KEYS = (
    "year",
    "total_cap",
    "auction_mode",
    "auction_offered",
    "reserved_allowances",
    "carbon_budget",
    "banking_allowed",
    "borrowing_allowed",
    "borrowing_limit",
)

# Every config_key the catalogue declares for each scope, plus the market's
# own structural grid keys. Anything a normalised config carries OUTSIDE
# these sets is a key no block owns — config_io tolerates unknown keys
# (normalize_* does ``blank.update(raw)``) for forward-compatible fields
# such as the documented-inert ``international_offset_*`` triad or a stray
# ``_comment``. Rather than silently dropping them (breaking round-trip) or
# hand-listing every such key, decompile.py stores them verbatim as opaque
# "_extra" params and compile.py replays them verbatim — a single generic
# mechanism, not a per-field special case.
KNOWN_SCENARIO_KEYS = frozenset(
    {p.config_key for block in BLOCK_CATALOGUE for p in block.params if p.scope == "scenario"}
)
KNOWN_YEAR_KEYS = frozenset(
    set(_MARKET_YEAR_GRID_KEYS)
    | {"participants"}
    | {p.config_key for block in BLOCK_CATALOGUE for p in block.params if p.scope == "year"}
)
KNOWN_PARTICIPANT_KEYS = frozenset(
    {p.config_key for block in BLOCK_CATALOGUE for p in block.params if p.scope == "participant"}
)


class CompileError(ValueError):
    """Raised when a graph cannot be compiled to a scenario-config dict."""


def per_year_value(values: dict[str, Any]) -> dict[str, Any]:
    """Wrap a ``{year_label: value}`` map as a per-year override."""
    return {PER_YEAR_KEY: dict(values)}


def is_per_year_value(raw: Any) -> bool:
    return isinstance(raw, dict) and set(raw.keys()) == {PER_YEAR_KEY}


def _coerce_json_shape(value: Any) -> Any:
    """Tuples are a convenient immutable ParamSpec default but config_io's
    normalisers require actual ``list`` instances (``isinstance(x, list)``
    checks) — coerce here, once, at the point every resolved value exits the
    compiler."""
    if isinstance(value, tuple):
        return list(value)
    return value


def resolve_year_value(raw: Any, year_label: str, default: Any) -> Any:
    """Resolve a param's raw value for one market year.

    ``raw`` is either a plain value (broadcast to every year) or a per-year
    override map produced by :func:`per_year_value`.
    """
    if raw is None:
        return _coerce_json_shape(default)
    if is_per_year_value(raw):
        table = raw[PER_YEAR_KEY]
        value = table[year_label] if year_label in table else default
        return _coerce_json_shape(value)
    return _coerce_json_shape(raw)


def _order_key(node: Node) -> tuple[float, str]:
    raw_order = node.params.get("order", 0)
    try:
        order = float(raw_order or 0)
    except (TypeError, ValueError):
        order = 0.0
    return (order, node.id)


def _require_node(graph: Graph, node_id: str, context: str) -> Node:
    node = graph.node(node_id)
    if node is None:
        raise CompileError(f"{context}: dangling reference to unknown node '{node_id}'.")
    return node


def _require_spec(node: Node) -> BlockSpec:
    if node.block not in BLOCK_CATALOGUE:
        raise CompileError(f"Node '{node.id}': unknown block id '{node.block}'.")
    return BLOCK_CATALOGUE.get(node.block)


class _FieldOwners:
    """Tracks which node "wrote" a scenario/year config key, for collision detection."""

    def __init__(self, market_id: str) -> None:
        self._market_id = market_id
        self._scenario: dict[str, str] = {}
        self._year: dict[tuple[str, str], str] = {}

    def set_scenario(self, fields: dict[str, Any], key: str, value: Any, owner: str) -> None:
        if key in self._scenario and self._scenario[key] != owner:
            raise CompileError(
                f"Market '{self._market_id}': both '{self._scenario[key]}' and "
                f"'{owner}' set scenario field '{key}'."
            )
        fields[key] = value
        self._scenario[key] = owner

    def set_year(
        self, year_entries: dict[str, dict[str, Any]], year_label: str, key: str, value: Any, owner: str
    ) -> None:
        marker = (year_label, key)
        if marker in self._year and self._year[marker] != owner:
            raise CompileError(
                f"Market '{self._market_id}' year '{year_label}': both "
                f"'{self._year[marker]}' and '{owner}' set '{key}'."
            )
        year_entries[year_label][key] = value
        self._year[marker] = owner


def compile_graph(graph: Graph) -> dict[str, Any]:
    """Compile a :class:`Graph` into a normalised scenario-config dict.

    GRAPH DISENTANGLEMENT (module docstring): ``carbon_market`` nodes are
    grouped into connected components under ``market_link`` edges
    (:func:`_connected_components`); each component compiles to ONE
    ``{"scenarios": [...]}`` entry — :func:`_compile_market` (VERBATIM,
    byte-identical to pre-D1-4) for a size-one component,
    :func:`_compile_linked_scenario` for a component of size >1.

    Args:
        graph: The drawn block graph.

    Returns:
        ``{"scenarios": [...]}`` after passing through
        ``config_io.normalize_config``.

    Raises:
        CompileError: On structural problems the compiler cannot route
            around (dangling edges, wrong price-formation cardinality, a
            key written by two different blocks, an unknown block id, a
            malformed/dangling ``market_link``, a disagreeing
            ``scenario_name``, or a ``"::"`` in a linked market id/scenario
            name — the engine's composite-key separator).
        ValueError: Propagated from ``config_io`` value validation.
    """
    market_nodes = [n for n in graph.nodes if n.block == "carbon_market"]
    if not market_nodes:
        raise CompileError("Graph has no 'carbon_market' node.")
    market_nodes.sort(key=_order_key)
    components = _connected_components(graph, market_nodes)
    scenarios = [
        _compile_market(graph, component[0])
        if len(component) == 1
        else _compile_linked_scenario(graph, component)
        for component in components
    ]
    return normalize_config({"scenarios": scenarios})


def _link_endpoints(graph: Graph, link_node: Node) -> tuple[str, str]:
    """Resolve a ``market_link`` node's ``(from_node_id, to_node_id)``.

    Args:
        graph: The drawn block graph.
        link_node: A ``market_link`` node.

    Returns:
        The node id feeding the link's ``from`` port (source market) and the
        node id its ``link`` port feeds into (target market).

    Raises:
        CompileError: The node does not have exactly one inbound ``from``
            edge and exactly one outbound ``link`` edge, or either resolved
            id is not a real node (dangling).
    """
    from_edges = graph.edges_into(link_node.id, "from")
    link_edges = [e for e in graph.edges if e.source == link_node.id and e.source_port == "link"]
    if len(from_edges) != 1 or len(link_edges) != 1:
        raise CompileError(
            f"market_link '{link_node.id}' must have exactly one inbound 'from' edge "
            f"and exactly one outbound 'link' edge (found {len(from_edges)} in, "
            f"{len(link_edges)} out)."
        )
    source = _require_node(graph, from_edges[0].source, f"market_link '{link_node.id}' from edge")
    target = _require_node(graph, link_edges[0].target, f"market_link '{link_node.id}' link edge")
    return source.id, target.id


def _connected_components(graph: Graph, market_nodes: list[Node]) -> list[list[Node]]:
    """Group ``carbon_market`` nodes into connected components under link edges.

    Undirected: a ``market_link`` edge A -> B puts A and B in the SAME
    component regardless of the link's direction (spec §3's "a scenario is
    a connected component of carbon_market nodes under link edges") — only
    :func:`topological_market_order` (the engine, D1-3) cares about
    directionality. A market_link node whose endpoints are not both
    ``carbon_market`` nodes in ``market_nodes`` is skipped here (a
    port-kind mismatch or dangling edge the generic structural checks
    already attribute; :func:`_link_endpoints` still raises for a malformed
    ``market_link`` node itself).

    Args:
        graph: The drawn block graph.
        market_nodes: Every ``carbon_market`` node, in declared
            (``_order_key``) order.

    Returns:
        One list of nodes per component, each internally sorted by
        ``_order_key``, and the list of components itself ordered by its
        first (minimum ``_order_key``) node — deterministic, declaration-
        order-derived (spec §3's "deterministic order via node order").
    """
    market_ids = {n.id for n in market_nodes}
    adjacency: dict[str, set[str]] = {n.id: set() for n in market_nodes}
    for node in graph.nodes:
        if node.block != "market_link":
            continue
        source_id, target_id = _link_endpoints(graph, node)
        if source_id not in market_ids or target_id not in market_ids:
            continue
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)

    by_id = {n.id: n for n in market_nodes}
    seen: set[str] = set()
    components: list[list[Node]] = []
    for node in market_nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        stack = [node.id]
        component_ids: list[str] = []
        while stack:
            current = stack.pop()
            component_ids.append(current)
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(sorted((by_id[cid] for cid in component_ids), key=_order_key))
    components.sort(key=lambda component: _order_key(component[0]))
    return components


def _compile_market_fields(
    graph: Graph,
    market_node: Node,
    *,
    identity_key: str,
    identity_value: Any,
    allow_policy_events: bool,
) -> dict[str, Any]:
    """Assemble one market body's fields — shared by both compile paths.

    Args:
        graph: The drawn block graph.
        market_node: The ``carbon_market`` node being compiled.
        identity_key: ``"name"`` (single-market: the scenario's own name) or
            ``"market_id"`` (multi-market: this market's id within its
            linked component) — the ONE field that differs in meaning
            between the two callers; everything else about a market body is
            identical (D1 COMPAT RULE: "a market body = today's scenario
            body minus name/policy_events").
        identity_value: The value for ``identity_key``.
        allow_policy_events: ``False`` inside a linked (multi-market)
            component — E7 defers events x multi-market to D2; ``True`` for
            the single-market path (unchanged behaviour).

    Returns:
        The assembled market body dict (``identity_key`` + every merged
        scenario/year field + ``"years"``).

    Raises:
        CompileError: No years in the market's grid; a config key written
            by two different blocks; ``allow_policy_events`` is ``False``
            and the node carries a non-empty ``policy_events`` param (E7).
    """
    owners = _FieldOwners(market_node.id)
    scenario_fields: dict[str, Any] = {}
    year_entries: dict[str, dict[str, Any]] = {}

    years_raw = market_node.params.get("years") or []
    for raw_year in years_raw:
        label = str(raw_year.get("year"))
        entry = {k: v for k, v in raw_year.items() if k in _MARKET_YEAR_GRID_KEYS}
        entry["year"] = label
        year_entries[label] = entry
    if not year_entries:
        raise CompileError(f"Market '{market_node.id}' has no years in its 'years' grid.")

    owners.set_scenario(scenario_fields, identity_key, identity_value, f"node:{market_node.id}")
    for passthrough_key in ("sectors", "policy_events", "price_unit", "flow_label", "flow_unit"):
        raw = market_node.params.get(passthrough_key)
        if not raw:
            continue
        if passthrough_key == "policy_events" and not allow_policy_events:
            raise CompileError(
                f"Market '{market_node.id}': policy_events is not permitted inside a "
                "linked (multi-market) scenario — events x multi-market is deferred "
                "to D2 (docs/platform-spec-d0-d1.md §7 E7)."
            )
        owners.set_scenario(scenario_fields, passthrough_key, raw, f"node:{market_node.id}")

    # Opaque unknown-key passthrough (see KNOWN_*_KEYS docstring above).
    scenario_extra = market_node.params.get("_scenario_extra")
    if scenario_extra:
        for key, value in scenario_extra.items():
            owners.set_scenario(scenario_fields, key, value, f"node:{market_node.id}:_scenario_extra")
    year_extra_raw = market_node.params.get("_year_extra")
    if year_extra_raw:
        for year_label in year_entries:
            extra = resolve_year_value(year_extra_raw, year_label, {})
            for key, value in (extra or {}).items():
                owners.set_year(year_entries, year_label, key, value, f"node:{market_node.id}:_year_extra")

    _compile_price_formation(graph, market_node, owners, scenario_fields)
    _compile_policies(graph, market_node, owners, scenario_fields, year_entries)
    _compile_expectations(graph, market_node, owners, year_entries)
    _compile_baseline(graph, market_node, owners, scenario_fields)
    _compile_sectors(graph, market_node, owners, scenario_fields)
    _compile_participants(graph, market_node, year_entries)
    _compile_strategic(graph, market_node, owners, scenario_fields)

    return {**scenario_fields, "years": list(year_entries.values())}


def _compile_market(graph: Graph, market_node: Node) -> dict[str, Any]:
    """Compile a size-one component: today's single-market scenario, VERBATIM."""
    return _compile_market_fields(
        graph,
        market_node,
        identity_key="name",
        identity_value=market_node.params.get("name", "New Scenario"),
        allow_policy_events=True,
    )


def _compile_links(
    graph: Graph, market_nodes: list[Node], market_ids_in_component: set[str]
) -> list[dict[str, Any]]:
    """Compile every ``market_link`` node whose endpoints are both in this component.

    Args:
        graph: The drawn block graph.
        market_nodes: This component's ``carbon_market`` nodes.
        market_ids_in_component: ``{node.id for node in market_nodes}``.

    Returns:
        Raw link records (``from_market``/``to_market``/``channel``/``phi``/
        ``phi_unit``/``target_participants`` + optionally
        ``target_technologies``/``back_demand_estimate``) in market_link
        node declaration order — ``config_io.normalize_scenario`` (via
        ``validate_links``) is the value validator; this function only
        derives the raw shape from the graph.
    """
    node_id_to_market_id = {n.id: str(n.params.get("name", "New Scenario")) for n in market_nodes}
    links: list[dict[str, Any]] = []
    for link_node in graph.nodes:
        if link_node.block != "market_link":
            continue
        source_id, target_id = _link_endpoints(graph, link_node)
        if source_id not in market_ids_in_component or target_id not in market_ids_in_component:
            continue  # belongs to a different component
        link: dict[str, Any] = {
            "from_market": node_id_to_market_id[source_id],
            "to_market": node_id_to_market_id[target_id],
            "channel": link_node.params.get("channel"),
            "phi": link_node.params.get("phi"),
            "phi_unit": link_node.params.get("phi_unit"),
            "target_participants": list(link_node.params.get("target_participants") or []),
        }
        target_technologies = link_node.params.get("target_technologies")
        if target_technologies:
            link["target_technologies"] = list(target_technologies)
        back_demand_estimate = link_node.params.get("back_demand_estimate")
        if back_demand_estimate is not None:
            link["back_demand_estimate"] = back_demand_estimate
        links.append(link)
    return links


def _compile_linked_scenario(graph: Graph, market_nodes: list[Node]) -> dict[str, Any]:
    """Compile a >1-size component into one ``markets:[...]``+``links:[...]`` scenario.

    Args:
        graph: The drawn block graph.
        market_nodes: This component's ``carbon_market`` nodes, sorted by
            ``_order_key`` (:func:`_connected_components`'s contract).

    Returns:
        ``{"name": scenario_name, "markets": [...], "links": [...]}`` — each
        market node's own ``name`` param becomes its ``market_id``; the
        wrapping ``name`` comes from the (must-agree) ``scenario_name``
        param, defaulting to the order-first market's own ``name``.

    Raises:
        CompileError: A ``scenario_name`` disagreement across the
            component, or a ``"::"`` in a market id or the scenario name
            (the engine's composite grouping-key separator,
            ``"{scenario} :: {market_id}"``).
    """
    market_ids_in_component = {n.id for n in market_nodes}
    markets: list[dict[str, Any]] = []
    declared_scenario_names: dict[str, str] = {}
    for market_node in market_nodes:
        market_id = str(market_node.params.get("name", "New Scenario"))
        markets.append(
            _compile_market_fields(
                graph, market_node,
                identity_key="market_id", identity_value=market_id,
                allow_policy_events=False,
            )
        )
        declared = market_node.params.get("scenario_name")
        if declared:
            declared_scenario_names[market_node.id] = str(declared)

    distinct_names = set(declared_scenario_names.values())
    if len(distinct_names) > 1:
        raise CompileError(
            f"Markets {sorted(declared_scenario_names)} in one linked scenario declare "
            f"disagreeing scenario_name values {sorted(distinct_names)} — scenario_name "
            "must agree across a component (docs/platform-plan-d0-d1.md D1)."
        )
    scenario_name = (
        next(iter(distinct_names)) if distinct_names else str(market_nodes[0].params.get("name", "New Scenario"))
    )

    if "::" in scenario_name:
        raise CompileError(
            f"Linked scenario name {scenario_name!r} contains '::' — reserved as the "
            "engine's composite grouping-key separator ('{scenario} :: {market_id}')."
        )
    for market in markets:
        if "::" in market["market_id"]:
            raise CompileError(
                f"Linked market id {market['market_id']!r} contains '::' — reserved as "
                "the engine's composite grouping-key separator ('{scenario} :: {market_id}')."
            )

    links = _compile_links(graph, market_nodes, market_ids_in_component)
    scenario: dict[str, Any] = {"name": scenario_name, "markets": markets, "links": links}
    joint_solver = _compile_joint_solver(graph, market_nodes)
    if joint_solver is not None:
        scenario["joint_solver"] = joint_solver
    return scenario


def _compile_joint_solver(graph: Graph, market_nodes: list[Node]) -> dict[str, Any] | None:
    """Collect a linked component's ``joint_solver`` node into a scenario block.

    D2-4 (``docs/joint-equilibrium-plan.md`` §4): a ``joint_solver`` node attaches
    to ANY one market of a linked component through that market's ``joint_solver``
    in-port (mirroring how a policy attaches to ``policies``); it configures the
    WHOLE component's cyclic outer loop, so it is read once per component, not per
    market. Its declared params (``config_key`` == the ``normalize_joint_solver``
    key, every default ``None``) become the scenario's optional ``joint_solver``
    block. No node ⇒ ``None`` ⇒ the caller emits NO ``joint_solver`` key, so an
    acyclic / cycle-with-defaults graph without such a node normalizes
    byte-identically to today (the D1 COMPAT RULE, mirroring
    ``config_io.normalize_joint_solver``'s own "absent ⇒ None" inertness).

    A cyclic component whose user dropped a BARE joint_solver node (no params
    set) yields ``{}`` — a present-but-empty block that
    ``normalize_joint_solver`` defaults exactly as the engine would; the KEY's
    presence is the honest "the user configured the joint solver" signal.

    Args:
        graph: The drawn block graph.
        market_nodes: This component's ``carbon_market`` nodes.

    Returns:
        The raw ``joint_solver`` settings dict (only the user-set keys), or
        ``None`` when the component carries no ``joint_solver`` node.

    Raises:
        CompileError: More than one DISTINCT ``joint_solver`` node attaches to
            the component's markets — a component's outer loop takes exactly one
            (attach it to any single market in the cycle).
    """
    joint_nodes: dict[str, Node] = {}
    for market_node in market_nodes:
        for edge in graph.edges_into(market_node.id, "joint_solver"):
            node = _require_node(
                graph, edge.source, f"Market '{market_node.id}' joint_solver edge"
            )
            joint_nodes[node.id] = node
    if not joint_nodes:
        return None
    if len(joint_nodes) > 1:
        raise CompileError(
            f"Linked scenario has {len(joint_nodes)} distinct joint_solver nodes "
            f"{sorted(joint_nodes)} attached to its markets — a component's outer "
            "loop takes exactly one joint_solver node (attach one to any single "
            "market in the cycle)."
        )
    (joint_node,) = joint_nodes.values()
    spec = _require_spec(joint_node)
    settings: dict[str, Any] = {}
    for param in spec.params:
        raw = joint_node.params.get(param.name, param.default)
        if raw is None:
            continue
        settings[param.config_key] = _coerce_json_shape(raw)
    return settings


def _merge_block_params(
    node: Node,
    spec: BlockSpec,
    owners: _FieldOwners,
    scenario_fields: dict[str, Any],
    year_entries: dict[str, dict[str, Any]] | None,
    owner_label: str,
    *,
    skip: frozenset[str] = frozenset(),
) -> None:
    """Merge every scope=="scenario"/"year" ParamSpec on ``node`` into the draft."""
    for param in spec.params:
        if param.config_key in skip:
            continue
        raw = node.params.get(param.name, param.default)
        if raw is None:
            continue
        if param.scope == "scenario":
            owners.set_scenario(scenario_fields, param.config_key, _coerce_json_shape(raw), owner_label)
        elif param.scope == "year" and year_entries is not None:
            for year_label in year_entries:
                value = resolve_year_value(raw, year_label, param.default)
                if value is None:
                    continue
                owners.set_year(year_entries, year_label, param.config_key, value, owner_label)


def _compile_price_formation(
    graph: Graph, market_node: Node, owners: _FieldOwners, scenario_fields: dict[str, Any]
) -> None:
    edges = graph.edges_into(market_node.id, "price_formation")
    if len(edges) != 1:
        raise CompileError(
            f"Market '{market_node.id}' must have exactly one price-formation edge "
            f"(found {len(edges)})."
        )
    pf_node = _require_node(graph, edges[0].source, f"Market '{market_node.id}' price_formation edge")
    pf_spec = _require_spec(pf_node)
    _merge_block_params(
        pf_node, pf_spec, owners, scenario_fields, None, f"node:{pf_node.id}",
        skip=frozenset({"nash_strategic_participants"}),
    )


def _compile_policies(
    graph: Graph,
    market_node: Node,
    owners: _FieldOwners,
    scenario_fields: dict[str, Any],
    year_entries: dict[str, dict[str, Any]],
) -> None:
    for edge in graph.edges_into(market_node.id, "policies"):
        policy_node = _require_node(graph, edge.source, f"Market '{market_node.id}' policy edge")
        policy_spec = _require_spec(policy_node)
        _merge_block_params(
            policy_node, policy_spec, owners, scenario_fields, year_entries,
            f"node:{policy_node.id}", skip=frozenset({"policy_events"}),
        )


def _compile_expectations(
    graph: Graph, market_node: Node, owners: _FieldOwners, year_entries: dict[str, dict[str, Any]]
) -> None:
    edges = graph.edges_into(market_node.id, "expectations")
    if len(edges) > 1:
        raise CompileError(f"Market '{market_node.id}' has more than one expectations edge.")
    if not edges:
        return
    node = _require_node(graph, edges[0].source, f"Market '{market_node.id}' expectations edge")
    spec = _require_spec(node)
    _merge_block_params(node, spec, owners, {}, year_entries, f"node:{node.id}")


def _compile_baseline(
    graph: Graph, market_node: Node, owners: _FieldOwners, scenario_fields: dict[str, Any]
) -> None:
    edges = graph.edges_into(market_node.id, "baseline")
    if len(edges) > 1:
        raise CompileError(f"Market '{market_node.id}' has more than one baseline edge.")
    if not edges:
        return
    node = _require_node(graph, edges[0].source, f"Market '{market_node.id}' baseline edge")
    spec = _require_spec(node)
    _merge_block_params(node, spec, owners, scenario_fields, None, f"node:{node.id}")


def _compile_sectors(
    graph: Graph, market_node: Node, owners: _FieldOwners, scenario_fields: dict[str, Any]
) -> None:
    edges = graph.edges_into(market_node.id, "sectors")
    if not edges:
        return
    node_ids = sorted({e.source for e in edges}, key=lambda nid: _order_key(_require_node(graph, nid, "sector edge")))
    sectors = []
    for node_id in node_ids:
        node = _require_node(graph, node_id, f"Market '{market_node.id}' sector edge")
        sectors.append(
            {
                "name": node.params.get("sector_name", "New Sector"),
                "cap_trajectory": node.params.get("cap_trajectory") or {},
                "auction_share_trajectory": node.params.get("auction_share_trajectory") or {},
                "carbon_budget": node.params.get("carbon_budget", 0.0),
            }
        )
    owners.set_scenario(scenario_fields, "sectors", sectors, "edges:sectors")


def _compile_participant_dict(node: Node, spec: BlockSpec, year_label: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for param in spec.params:
        raw = node.params.get(param.name, param.default)
        value = resolve_year_value(raw, year_label, param.default)
        if value is None:
            continue
        out[param.config_key] = value
    extra_raw = node.params.get("_extra")
    if extra_raw:
        extra = resolve_year_value(extra_raw, year_label, {})
        out.update(extra or {})
    return out


def _compile_participants(graph: Graph, market_node: Node, year_entries: dict[str, dict[str, Any]]) -> None:
    edges = graph.edges_into(market_node.id, "participants")
    if not edges:
        raise CompileError(f"Market '{market_node.id}' has no participants attached.")
    participant_ids = sorted(
        {e.source for e in edges},
        key=lambda nid: _order_key(_require_node(graph, nid, "participant edge")),
    )
    for entry in year_entries.values():
        entry["participants"] = []
    for participant_id in participant_ids:
        pnode = _require_node(graph, participant_id, f"Market '{market_node.id}' participant edge")
        pspec = _require_spec(pnode)
        option_edges = [e for e in graph.edges if e.target == participant_id and e.target_port == "options"]
        if option_edges and pnode.params.get("technology_options"):
            raise CompileError(
                f"Participant '{participant_id}' has both a 'technology_options' param "
                "and 'option' edges from technology_option nodes."
            )
        option_ids = sorted(
            {e.source for e in option_edges},
            key=lambda nid: _order_key(_require_node(graph, nid, "technology_option edge")),
        ) if option_edges else []
        for year_label, entry in year_entries.items():
            pdict = _compile_participant_dict(pnode, pspec, year_label)
            if option_ids:
                options = []
                for option_id in option_ids:
                    onode = _require_node(graph, option_id, f"Participant '{participant_id}' option edge")
                    ospec = _require_spec(onode)
                    options.append(_compile_participant_dict(onode, ospec, year_label))
                pdict["technology_options"] = options
            entry["participants"].append(pdict)


def _compile_strategic(
    graph: Graph, market_node: Node, owners: _FieldOwners, scenario_fields: dict[str, Any]
) -> None:
    edges = graph.edges_into(market_node.id, "price_formation")
    if not edges:
        return
    pf_node_id = edges[0].source
    strategic_edges = [e for e in graph.edges if e.target == pf_node_id and e.target_port == "strategic"]
    if not strategic_edges:
        return
    names = []
    for e in strategic_edges:
        node = _require_node(graph, e.source, f"Nash '{pf_node_id}' strategic edge")
        names.append(str(node.params.get("name", "")))
    owners.set_scenario(scenario_fields, "nash_strategic_participants", sorted(names), "edges:strategic")
