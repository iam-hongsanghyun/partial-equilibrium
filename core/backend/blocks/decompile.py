"""``graph_from_config``: scenario-config dict -> :class:`Graph`.

The inverse of :func:`ets.blocks.compile.compile_graph`. Every
``examples/*.json`` scenario-config document loads onto a canvas through this
function (``tests/test_blocks_decompile.py``).

Design: the config is normalised first (``config_io.normalize_config``), so
every field this module reads is already canonical (defaults filled, types
coerced). For every declared :class:`~ets.blocks.registry.ParamSpec`, the
value is read from every market year and *collapsed*: if it is identical
across years it becomes a plain scalar param; if it varies it becomes a
per-year override map (:func:`ets.blocks.compile.per_year_value`) — the same
generic mechanism ``compile_graph`` already understands, applied uniformly to
any field rather than only the ones the plan calls out by name.

Structural (non-config-owning) blocks are only instantiated when their
underlying mechanism is actually active (``msr_enabled``, a non-empty
trajectory, a non-default per-year value, ...), so a decompiled graph reads
like what a human would actually have drawn rather than every optional block
wired in at its default.

Scope reduction (documented, not silent): ``sector`` and ``technology_option``
*nodes* are not synthesised — ``sectors``/``technology_options`` round-trip as
opaque list-valued params on the ``carbon_market``/``participant`` node
respectively (``compile_graph`` accepts both representations). The
``oba``/``compare_all`` blocks are never synthesised either: ``oba`` owns no
config keys (see ``catalogue.py``) and ``compare_all`` is not a drawable
block.

GRAPH DISENTANGLEMENT (D1-4, ``docs/platform-plan-d0-d1.md`` D1 "GRAPH
DISENTANGLEMENT"): a ``markets``-shaped (linked, multi-market) scenario
decompiles via :func:`_decompile_linked_scenario` — one ``carbon_market``
node per ``markets[i]`` entry (its ``market_id`` -> the node's ``name``
param) plus one ``market_link`` node per ``links[i]`` entry, wired
``signal -> from`` / ``link -> links``. A single-market scenario (no
``markets`` key) still decompiles via :func:`_decompile_scenario` — the
pre-D1-4 interim loud guard (D1-1: "markets-shaped scenarios are schema-
only") is retired now that both directions are wired; the two paths share
:func:`_decompile_market_body`, the one place that knows how to walk a
market body regardless of which shape it arrived in.

D2-4 (``docs/joint-equilibrium-plan.md`` §4): the ``markets``/``links`` edges
may form a CYCLE, and a cyclic scenario may carry an optional ``joint_solver``
block — :func:`_decompile_joint_solver` restores it as one ``joint_solver``
node wired into the first market (the component-level analogue of the wrapping
``scenario_name``). Absent block ⇒ no node, so an acyclic scenario round-trips
unchanged.

Dependency law: this module imports only ``ets.blocks`` siblings,
``ets.config_io``, and stdlib.
"""

from __future__ import annotations

from typing import Any

from ..config_io import normalize_config
from .catalogue import BLOCK_CATALOGUE
from .compile import (
    KNOWN_PARTICIPANT_KEYS,
    KNOWN_SCENARIO_KEYS,
    KNOWN_YEAR_KEYS,
    per_year_value,
)
from .graph import Edge, Graph, Node

_PF_BLOCK_FOR_APPROACH = {
    "competitive": "competitive_clearing",
    "banking": "rubin_schennach_banking",
    "hotelling": "hotelling",
    "nash_cournot": "nash_cournot",
}

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


def _equals_default(value: Any, default: Any) -> bool:
    if isinstance(default, (list, tuple)) and isinstance(value, (list, tuple)):
        return bool(list(value) == list(default))
    return bool(value == default)


def _collapse(values_by_year: dict[str, Any]) -> Any:
    values = list(values_by_year.values())
    first = values[0]
    if all(_equals_default(v, first) for v in values):
        return first
    return per_year_value(values_by_year)


def _year_field(years: list[dict[str, Any]], config_key: str, default: Any) -> tuple[Any, bool]:
    """Collapse ``config_key`` across ``years``; returns (value, any_deviates)."""
    values_by_year = {str(y["year"]): y.get(config_key, default) for y in years}
    deviates = any(not _equals_default(v, default) for v in values_by_year.values())
    return _collapse(values_by_year), deviates


def graph_from_config(config: dict[str, Any]) -> Graph:
    """Build a :class:`Graph` from a scenario-config dict.

    Args:
        config: A ``{"scenarios": [...]}`` document (or anything
            ``config_io.normalize_config`` accepts).

    Returns:
        A :class:`Graph` whose ``meta`` is empty (scenario configs carry no
        canvas metadata) and which recompiles to an equivalent config via
        :func:`ets.blocks.compile.compile_graph`.
    """
    normalized = normalize_config(config)
    nodes: list[Node] = []
    edges: list[Edge] = []
    for scenario_index, scenario in enumerate(normalized["scenarios"]):
        if "markets" in scenario:
            _decompile_linked_scenario(scenario, scenario_index, nodes, edges)
        else:
            _decompile_scenario(scenario, scenario_index, nodes, edges)
    return Graph(nodes=nodes, edges=edges, meta={})


def _decompile_scenario(
    scenario: dict[str, Any], scenario_index: int, nodes: list[Node], edges: list[Edge]
) -> None:
    market_id = f"market{scenario_index}"
    _decompile_market_body(scenario, market_id, scenario["name"], {"order": scenario_index}, nodes, edges)


def _decompile_linked_scenario(
    scenario: dict[str, Any], scenario_index: int, nodes: list[Node], edges: list[Edge]
) -> None:
    """Decompile a ``markets``-shaped (multi-market, linked) scenario (D1-4).

    Inverse of ``compile.py``'s :func:`~ets.blocks.compile._compile_linked_scenario`:
    every ``markets[i]`` entry becomes one ``carbon_market`` node (its
    ``market_id`` -> the node's ``name`` param — the same field a size-one
    component uses for the scenario name) plus its own sub-nodes, and every
    ``links[i]`` entry becomes one ``market_link`` node wired ``signal`` ->
    ``from`` -> ``link`` -> ``links``. The wrapping scenario's ``name`` is
    restated as the FIRST market's ``scenario_name`` param only when it
    differs from that market's own ``market_id`` (compile's default-
    resolution already reconstructs it otherwise — decompile.py's usual
    "reads like what a human would actually have drawn" discipline).

    Node ids nest under the SAME ``market{scenario_index}_`` prefix the
    flat path uses for one market's sub-nodes (``manifest.py``'s
    ``_market_node_ids`` prefix-match already generalizes to N such
    sub-prefixes per scenario without changes).

    Args:
        scenario: A normalized ``markets``/``links``-shaped scenario dict.
        scenario_index: This scenario's index in the config's top-level list.
        nodes: Accumulating node list (mutated in place).
        edges: Accumulating edge list (mutated in place).
    """
    markets: list[dict[str, Any]] = scenario["markets"]
    links: list[dict[str, Any]] = scenario.get("links") or []
    scenario_name = scenario["name"]

    node_id_by_market_id: dict[str, str] = {}
    for index, market in enumerate(markets):
        market_id = market["market_id"]
        node_id = f"market{scenario_index}_{index}"
        node_id_by_market_id[market_id] = node_id
        extra_params: dict[str, Any] = {"order": index}
        if index == 0 and scenario_name != market_id:
            extra_params["scenario_name"] = scenario_name
        body = {k: v for k, v in market.items() if k != "market_id"}
        _decompile_market_body(body, node_id, market_id, extra_params, nodes, edges)

    for link_index, link in enumerate(links):
        link_node_id = f"market{scenario_index}_link{link_index}"
        params: dict[str, Any] = {
            "channel": link["channel"],
            "phi": link["phi"],
            "phi_unit": link["phi_unit"],
            "target_participants": link["target_participants"],
        }
        if link.get("target_technologies"):
            params["target_technologies"] = link["target_technologies"]
        if link.get("back_demand_estimate") is not None:
            params["back_demand_estimate"] = link["back_demand_estimate"]
        nodes.append(Node(link_node_id, "market_link", params))
        edges.append(Edge(node_id_by_market_id[link["from_market"]], "signal", link_node_id, "from"))
        edges.append(Edge(link_node_id, "link", node_id_by_market_id[link["to_market"]], "links"))

    _decompile_joint_solver(
        scenario, scenario_index, f"market{scenario_index}_0", nodes, edges
    )


def _decompile_joint_solver(
    scenario: dict[str, Any],
    scenario_index: int,
    first_market_node_id: str,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Synthesize the ``joint_solver`` node for a cyclic (joint) scenario (D2-4).

    Inverse of ``compile.py``'s :func:`~ets.blocks.compile._compile_joint_solver`:
    a ``markets``-shaped scenario carrying a ``joint_solver`` block (only cyclic
    components ever declare one) becomes one ``joint_solver`` node wired into the
    FIRST market's ``joint_solver`` in-port — the component-level analogue of how
    the wrapping ``scenario_name`` is restated on the first market. Absent block
    ⇒ no node (the "reads like what a human drew" discipline; an acyclic /
    single-market scenario never carries the key, so it never gains the node).

    Every key ``normalize_joint_solver`` filled is restated verbatim on the node
    (the block's ParamSpec defaults are ``None``, so every present key deviates
    and round-trips): compile re-emits them and re-normalizes to the identical
    block.

    Args:
        scenario: A normalized ``markets``-shaped scenario dict.
        scenario_index: This scenario's index in the config's top-level list.
        first_market_node_id: The order-first market's ``carbon_market`` node id
            (``market{scenario_index}_0``), the node the joint_solver attaches to.
        nodes: Accumulating node list (mutated in place).
        edges: Accumulating edge list (mutated in place).
    """
    settings = scenario.get("joint_solver")
    if not settings:
        return
    spec = BLOCK_CATALOGUE.get("joint_solver")
    params: dict[str, Any] = {
        param.name: settings[param.config_key]
        for param in spec.params
        if param.config_key in settings
    }
    node_id = f"market{scenario_index}_joint"
    nodes.append(Node(node_id, "joint_solver", params))
    edges.append(Edge(node_id, "joint_solver", first_market_node_id, "joint_solver"))


def _decompile_market_body(
    body: dict[str, Any],
    market_id: str,
    node_name: str,
    extra_market_params: dict[str, Any],
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Decompile one market body into a ``carbon_market`` node plus its sub-nodes.

    Shared by the flat single-market path (``body`` = a whole normalized
    scenario dict) and the linked multi-market path (``body`` = one
    ``markets[i]`` entry minus ``market_id``) — a market body is "today's
    scenario body minus name/policy_events" (D1 COMPAT RULE), so this is the
    ONE place that knows how to walk one, mirroring
    ``compile.py``'s :func:`~ets.blocks.compile._compile_market_fields`.

    Args:
        body: The market body (flat scenario dict, or one ``markets[i]``
            entry with ``market_id`` stripped).
        market_id: This market's graph node id (the ``carbon_market`` node
            AND every sub-node's id prefix).
        node_name: The node's ``name`` param — the scenario's own name for a
            flat market, or this market's ``market_id`` for a linked one
            (``compile.py``'s ``_compile_market_fields`` reads the SAME
            node param as either "scenario name" or "market_id" depending
            on which path compiles it; the graph-side param name never
            changes).
        extra_market_params: Extra params to seed onto the node
            (``order``, and — linked case only — ``scenario_name`` on the
            first market when it disagrees with its own ``market_id``).
        nodes: Accumulating node list (mutated in place).
        edges: Accumulating edge list (mutated in place).
    """
    years: list[dict[str, Any]] = body["years"]
    year_labels = [str(y["year"]) for y in years]

    market_params: dict[str, Any] = {
        "name": node_name,
        "years": [{k: y[k] for k in _MARKET_YEAR_GRID_KEYS} for y in years],
        **extra_market_params,
    }
    if body.get("sectors"):
        market_params["sectors"] = body["sectors"]
    if body.get("policy_events"):
        market_params["policy_events"] = body["policy_events"]
    if body.get("price_unit"):
        market_params["price_unit"] = body["price_unit"]
    if body.get("flow_label"):
        market_params["flow_label"] = body["flow_label"]
    if body.get("flow_unit"):
        market_params["flow_unit"] = body["flow_unit"]

    scenario_extra = {k: v for k, v in body.items() if k not in KNOWN_SCENARIO_KEYS and k != "years"}
    if scenario_extra:
        market_params["_scenario_extra"] = scenario_extra
    year_extra_by_year = {
        str(y["year"]): {k: v for k, v in y.items() if k not in KNOWN_YEAR_KEYS} for y in years
    }
    if any(year_extra_by_year.values()):
        market_params["_year_extra"] = _collapse(year_extra_by_year)

    nodes.append(Node(market_id, "carbon_market", market_params))

    pf_id = f"{market_id}_pf"
    pf_block = _decompile_price_formation(body, pf_id, nodes)
    edges.append(Edge(pf_id, "price_formation", market_id, "price_formation"))

    participant_ids = _decompile_participants(years, year_labels, market_id, nodes, edges)

    if pf_block == "nash_cournot":
        for name in body.get("nash_strategic_participants") or []:
            for pid in participant_ids:
                pnode = next(n for n in nodes if n.id == pid)
                if pnode.params.get("name") == name:
                    edges.append(Edge(pid, "strategic", pf_id, "strategic"))

    _decompile_msr(body, market_id, nodes, edges)
    _decompile_ccr(body, market_id, nodes, edges)
    _decompile_endogenous_investment(body, market_id, nodes, edges)
    _decompile_year_policy(body, years, market_id, nodes, edges)
    _decompile_scenario_policy(body, market_id, nodes, edges)
    _decompile_expectations(body, years, market_id, nodes, edges)
    _decompile_baseline(body, market_id, nodes, edges)


def _decompile_price_formation(scenario: dict[str, Any], pf_id: str, nodes: list[Node]) -> str:
    approach = scenario.get("model_approach", "competitive")
    pf_block = _PF_BLOCK_FOR_APPROACH.get(approach, "competitive_clearing")
    if approach == "competitive" and scenario.get("forward_transmission_lambda") is not None:
        pf_block = "forward_transmission"
    spec = BLOCK_CATALOGUE.get(pf_block)
    params: dict[str, Any] = {}
    for param in spec.params:
        if param.config_key == "nash_strategic_participants" or param.scope != "scenario":
            continue
        value = scenario.get(param.config_key, param.default)
        if not _equals_default(value, param.default):
            params[param.name] = value
    nodes.append(Node(pf_id, pf_block, params))
    return pf_block


def _decompile_participants(
    years: list[dict[str, Any]],
    year_labels: list[str],
    market_id: str,
    nodes: list[Node],
    edges: list[Edge],
) -> list[str]:
    spec = BLOCK_CATALOGUE.get("participant")
    names: list[str] = [p["name"] for p in years[0]["participants"]] if years else []
    participant_ids: list[str] = []
    for index, name in enumerate(names):
        pid = f"{market_id}_p{index}"
        params: dict[str, Any] = {"order": index}
        for param in spec.params:
            values_by_year: dict[str, Any] = {}
            for year in years:
                match = next((p for p in year["participants"] if p["name"] == name), None)
                if match is None:
                    continue
                values_by_year[str(year["year"])] = match.get(param.config_key, param.default)
            if not values_by_year:
                continue
            collapsed = _collapse(values_by_year)
            if isinstance(collapsed, dict) and "__per_year__" in collapsed:
                params[param.name] = collapsed
            elif not _equals_default(collapsed, param.default):
                params[param.name] = collapsed

        extra_by_year: dict[str, Any] = {}
        for year in years:
            match = next((p for p in year["participants"] if p["name"] == name), None)
            if match is None:
                continue
            extra_by_year[str(year["year"])] = {
                k: v for k, v in match.items() if k not in KNOWN_PARTICIPANT_KEYS
            }
        if any(extra_by_year.values()):
            params["_extra"] = _collapse(extra_by_year)

        nodes.append(Node(pid, "participant", params))
        edges.append(Edge(pid, "compliance", market_id, "participants"))
        participant_ids.append(pid)
    return participant_ids


def _decompile_msr(scenario: dict[str, Any], market_id: str, nodes: list[Node], edges: list[Edge]) -> None:
    if not scenario.get("msr_enabled"):
        return
    mode = scenario.get("msr_mode", "bank_threshold")
    node_id = f"{market_id}_msr"
    keys: tuple[str, ...]
    if mode == "bank_threshold":
        block_id = "msr_bank_threshold"
        keys = (
            "msr_upper_threshold", "msr_lower_threshold", "msr_withhold_rate",
            "msr_release_rate", "msr_cancel_excess", "msr_cancel_threshold",
            "msr_initial_reserve_mt", "msr_start_year",
        )
    else:
        block_id = "kmsr_decree"
        keys = (
            "msr_mode", "msr_price_band_high", "msr_price_band_low",
            "msr_surplus_upper_ratio", "msr_surplus_lower_ratio",
            "msr_max_intake_mt", "msr_max_release_mt",
            "msr_initial_reserve_mt", "msr_start_year",
        )
    spec = BLOCK_CATALOGUE.get(block_id)
    params: dict[str, Any] = {}
    for key in keys:
        param = spec.param(key)
        assert param is not None
        value = scenario.get(key, param.default)
        if not _equals_default(value, param.default):
            params[key] = value
    nodes.append(Node(node_id, block_id, params))
    edges.append(Edge(node_id, "policy", market_id, "policies"))


def _decompile_ccr(scenario: dict[str, Any], market_id: str, nodes: list[Node], edges: list[Edge]) -> None:
    if not scenario.get("ccr_enabled"):
        return
    node_id = f"{market_id}_ccr"
    spec = BLOCK_CATALOGUE.get("ccr")
    params: dict[str, Any] = {}
    for key in (
        "ccr_phi_emissions", "ccr_phi_abatement_cost",
        "ccr_reference_emissions", "ccr_reference_abatement_cost", "ccr_start_year",
    ):
        param = spec.param(key)
        assert param is not None
        value = scenario.get(key, param.default)
        if not _equals_default(value, param.default):
            params[key] = value
    nodes.append(Node(node_id, "ccr", params))
    edges.append(Edge(node_id, "policy", market_id, "policies"))


def _decompile_endogenous_investment(
    scenario: dict[str, Any], market_id: str, nodes: list[Node], edges: list[Edge]
) -> None:
    """Synthesize the ``endogenous_investment`` node (sibling of ``_decompile_ccr``).

    ``investment_feedback_enabled`` itself is never restated in the node's
    params — its ``ParamSpec`` default is ``True`` (the msr_enabled/
    ccr_enabled sibling trick, ``catalogue.py``), so the node's mere
    presence, wired into the market's ``policies`` port, already compiles
    it back to ``True`` (spec D6).
    """
    if not scenario.get("investment_feedback_enabled"):
        return
    node_id = f"{market_id}_investment"
    spec = BLOCK_CATALOGUE.get("endogenous_investment")
    params: dict[str, Any] = {}
    for key in ("investment_max_iterations", "investment_initial_adoptions", "invest_credibility"):
        param = spec.param(key)
        assert param is not None
        value = scenario.get(key, param.default)
        if not _equals_default(value, param.default):
            params[key] = value
    nodes.append(Node(node_id, "endogenous_investment", params))
    edges.append(Edge(node_id, "policy", market_id, "policies"))


def _decompile_year_policy(
    scenario: dict[str, Any], years: list[dict[str, Any]], market_id: str, nodes: list[Node], edges: list[Edge]
) -> None:
    def add(block_id: str, node_suffix: str, keys: tuple[str, ...]) -> None:
        spec = BLOCK_CATALOGUE.get(block_id)
        params: dict[str, Any] = {}
        active = False
        for key in keys:
            param = spec.param(key)
            assert param is not None
            value, deviates = _year_field(years, key, param.default)
            if deviates:
                active = True
                params[key] = value
        if active:
            node_id = f"{market_id}_{node_suffix}"
            nodes.append(Node(node_id, block_id, params))
            edges.append(Edge(node_id, "policy", market_id, "policies"))

    add("price_floor", "floor", ("price_lower_bound",))
    add("price_ceiling", "ceiling", ("price_upper_bound",))
    add("auction_reserve", "reserve", ("auction_reserve_price", "minimum_bid_coverage", "unsold_treatment"))
    add("cancellation", "cancel", ("cancelled_allowances",))
    add("cbam", "cbam", ("eua_price", "eua_prices", "eua_price_ensemble"))
    add("hoarding", "hoard", ("hoarding_inflow",))

    # price_floor_trajectory / price_ceiling_trajectory are scenario-scope but
    # conceptually belong to the same blocks as their year-scope siblings.
    floor_traj = scenario.get("price_floor_trajectory")
    if floor_traj:
        node_id = f"{market_id}_floor"
        existing = next((n for n in nodes if n.id == node_id), None)
        if existing is None:
            existing = Node(node_id, "price_floor", {})
            nodes.append(existing)
            edges.append(Edge(node_id, "policy", market_id, "policies"))
        existing.params["price_floor_trajectory"] = floor_traj
    ceiling_traj = scenario.get("price_ceiling_trajectory")
    if ceiling_traj:
        node_id = f"{market_id}_ceiling"
        existing = next((n for n in nodes if n.id == node_id), None)
        if existing is None:
            existing = Node(node_id, "price_ceiling", {})
            nodes.append(existing)
            edges.append(Edge(node_id, "policy", market_id, "policies"))
        existing.params["price_ceiling_trajectory"] = ceiling_traj


def _decompile_scenario_policy(scenario: dict[str, Any], market_id: str, nodes: list[Node], edges: list[Edge]) -> None:
    cap_traj = scenario.get("cap_trajectory")
    if cap_traj:
        node_id = f"{market_id}_cap"
        nodes.append(Node(node_id, "cap_path", {"cap_trajectory": cap_traj}))
        edges.append(Edge(node_id, "policy", market_id, "policies"))

    falloc = scenario.get("free_allocation_trajectories")
    if falloc:
        node_id = f"{market_id}_falloc"
        nodes.append(Node(node_id, "free_allocation_phaseout", {"free_allocation_trajectories": falloc}))
        edges.append(Edge(node_id, "policy", market_id, "policies"))


def _decompile_expectations(
    scenario: dict[str, Any], years: list[dict[str, Any]], market_id: str, nodes: list[Node], edges: list[Edge]
) -> None:
    spec = BLOCK_CATALOGUE.get("expectations")
    params: dict[str, Any] = {}
    active = False
    for key in ("expectation_rule", "manual_expected_price"):
        param = spec.param(key)
        assert param is not None
        value, deviates = _year_field(years, key, param.default)
        if deviates:
            active = True
            params[key] = value
    if active:
        node_id = f"{market_id}_exp"
        nodes.append(Node(node_id, "expectations", params))
        edges.append(Edge(node_id, "expectations", market_id, "expectations"))


def _decompile_baseline(scenario: dict[str, Any], market_id: str, nodes: list[Node], edges: list[Edge]) -> None:
    reference = scenario.get("reference_carbon_price", 0.0)
    if reference:
        node_id = f"{market_id}_baseline"
        nodes.append(Node(node_id, "price_elastic_baseline", {"reference_carbon_price": reference}))
        edges.append(Edge(node_id, "baseline", market_id, "baseline"))
