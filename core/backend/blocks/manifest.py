"""``derive_manifest``: which feature modules a config/model uses.

Powers a model-scoped UI (``GET``/``POST /api/model-manifest``, see
``ets/web/api.py``): given a scenario-config dict, report the block/feature
vocabulary it exercises so the frontend can show only the panels relevant to
that model instead of every block the catalogue knows about.

Design: the manifest is derived from the *compiled block graph*
(:func:`ets.blocks.decompile.graph_from_config`), not from the raw config
directly — every node the decompiler synthesises maps onto exactly one
:class:`~ets.blocks.registry.BlockSpec`, and every ``BlockSpec`` declares
exactly one ``feature``, so ``{node.block for node in graph.nodes}`` mapped
through the catalogue is the whole of the graph-derived signal. This mirrors
``decompile.py``'s documented scope reduction: blocks it never synthesises a
node for (``sector``, ``technology_option``, ``oba`` — round-tripped as
opaque pass-through data rather than drawn nodes, see ``decompile.py``'s
module docstring) are therefore also invisible to graph-derived feature
detection. That gap is covered by direct detectors, not by the graph: see
:func:`_direct_detectors` below for ``oba``, ``sectors``, and
``policy_events`` — the config-shape signals that have no node
representation today.

D1-4 multi-market signal (``docs/platform-plan-d0-d1.md`` D1 "GRAPH
DISENTANGLEMENT"): a linked scenario's ``market_link`` nodes DO decompile to
real graph nodes (feature ``"market_links"``), so that feature already
surfaces through the ordinary graph-derived path above with no extra code —
it "appears when links present" for free. What needs help is the SHAPE
mismatch: a linked scenario's participants/sectors/investment flags live
inside ``markets[i]`` rather than at the scenario's own top level, so
:func:`_market_bodies` is the one place that flattens "the scenario itself
for a flat scenario, or each of its ``markets[i]`` entries for a linked
one" — every body-level direct detector (and :func:`_year_participants`)
reads through it, and each scenario's manifest entry gains a ``"markets"``
sub-key (:func:`_scenario_market_ids`; ``[]`` for a flat scenario).

Dependency law: this module imports only ``ets.blocks`` siblings
(``catalogue``, ``decompile``) and ``ets.config_io`` — never
``ets.engine``/``ets.solvers``. ``blocks/`` stays engine-blind so the
Vercel graph/manifest path never imports a solver (plan §1 clause (g)).
"""

from __future__ import annotations

from typing import Any

from ..config_io import normalize_config
from .catalogue import BLOCK_CATALOGUE
from .decompile import graph_from_config
from .graph import Node

# "all" is a comparison-run shorthand (plan §1 "compare_all"), not a solver
# of its own — it means "solve every deterministic price-formation approach
# for this scenario", which is exactly these three (banking is excluded: it
# requires banking_allowed/borrowing state the other three don't share, and
# is never implied by "all" in config_io/builder.py).
_ALL_APPROACH_EXPANSION: tuple[str, ...] = ("competitive", "hotelling", "nash_cournot")


def _expand_approach(approach: str) -> list[str]:
    """Expand a single ``model_approach`` value into its constituent solver ids."""
    if approach == "all":
        return list(_ALL_APPROACH_EXPANSION)
    return [approach]


def _scenario_approach(scenario: dict[str, Any]) -> list[str]:
    """Expand one scenario's ``model_approach``(es) into its constituent solver ids.

    D1-4: a linked (``markets``-shaped) scenario carries ``model_approach``
    per market rather than at its own top level (docs/platform-plan-d0-d1.md
    D1 "GRAPH DISENTANGLEMENT") — the engine forbids ``"all"`` inside a
    linked scenario (``engine/dispatch.py``), but this function only REPORTS
    what a config declares, so it still expands it defensively per market.

    Args:
        scenario: A normalised scenario dict (``config_io.normalize_scenario``
            output) — either flat (``model_approach`` at the top level) or
            ``markets``-shaped (one ``model_approach`` per ``markets[i]``).

    Returns:
        Flat case: ``["competitive", "hotelling", "nash_cournot"]`` if the
        scenario's ``model_approach`` is ``"all"``; otherwise a
        single-element list holding that approach verbatim. Linked case:
        the sorted, de-duplicated union of every market's (expanded)
        approach.
    """
    markets = scenario.get("markets")
    if markets:
        approaches: set[str] = set()
        for market in markets:
            approaches.update(_expand_approach(str(market.get("model_approach", "competitive"))))
        return sorted(approaches)
    return _expand_approach(str(scenario.get("model_approach", "competitive")))


def _market_bodies(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every market body across the given scenarios.

    The scenario itself for a flat (single-market) scenario, or each of its
    ``markets[i]`` entries for a linked (multi-market) one (D1-4) — the one
    place :func:`_year_participants` and every body-level direct detector
    (``sectors``, ``endogenous_investment``) reads through, so they see a
    linked scenario's markets without a per-detector shape branch.
    """
    bodies: list[dict[str, Any]] = []
    for scenario in scenarios:
        bodies.extend(scenario.get("markets") or [scenario])
    return bodies


def _year_participants(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every participant dict across every year of every given scenario (or market body)."""
    return [
        participant
        for body in _market_bodies(scenarios)
        for year in body.get("years", [])
        for participant in year.get("participants", [])
    ]


def _direct_detectors(scenarios: list[dict[str, Any]]) -> set[str]:
    """Config-shape feature signals the compiled block graph cannot see.

    THE place to add future non-graph detectors: one clause per detector,
    each keyed off a config-shape predicate that has no node representation
    in :func:`ets.blocks.decompile.graph_from_config` (today: ``oba``,
    ``sectors``, and the ``policy_events`` timeline — splicing is engine
    composition, not a drawable block, per ``docs/feature-modules-plan.md``
    §1 "policy_events → engine module"; ``sector``/``technology_option``/
    ``oba`` nodes are never synthesised either, per ``decompile.py``'s module
    docstring). Do not special-case a detector's result inline in
    :func:`derive_manifest`; add a clause here instead so every non-graph
    signal lives in one auditable place.

    Args:
        scenarios: Normalised scenario dicts to scan (typically either every
            scenario in a config, for the top-level manifest, or a single
            scenario, for its per-scenario breakdown).

    Returns:
        The set of feature names any clause matched.
    """
    detected: set[str] = set()
    if any(scenario.get("policy_events") for scenario in scenarios):
        detected.add("policy_events")

    # Output-Based Allocation: mirrors config_io/builder.py's
    # build_market_from_year OBA-override predicate exactly (the block that
    # overrides free_allocation_ratio with benchmark_emission_intensity *
    # production_output) — production_output, benchmark_emission_intensity,
    # AND initial_emissions must all be positive for OBA to actually engage.
    if any(
        float(participant.get("production_output") or 0.0) > 0
        and float(participant.get("benchmark_emission_intensity") or 0.0) > 0
        and float(participant.get("initial_emissions") or 0.0) > 0
        for participant in _year_participants(scenarios)
    ):
        detected.add("oba")

    # Sectors: mirrors both branches config_io/builder.py keys off —
    # (1) a non-empty market-body-level sectors[] table (build_market_from_year's
    # sector-pool derivation only runs `if sectors:`; D1-4: this is per-market
    # for a linked scenario, via _market_bodies), and (2) a participant
    # sector_group tag, which is meaningful even without a sectors[] table
    # (validate.py's R26 sums sector_allocation_share by sector_group
    # regardless of whether sectors[] is defined for the scenario).
    if any(body.get("sectors") for body in _market_bodies(scenarios)) or any(
        participant.get("sector_group") for participant in _year_participants(scenarios)
    ):
        detected.add("sectors")

    # Endogenous investment (docs/invest-feedback-plan.md D4; spec D6): the
    # per-market-body master flag (D1-4: via _market_bodies) OR any technology
    # option carrying a non-empty investment_trigger sub-dict.
    # ``technology_option`` nodes are never synthesised by decompile.py
    # (documented scope reduction — options round-trip as an opaque
    # list-valued param on the participant node), so a flagged option with
    # the master gate off (a config the BUILDER rejects loudly, spec D3.2)
    # would otherwise be invisible to the graph; this direct detector
    # reports it regardless of graph coverage, same as the ``oba``/
    # ``sectors`` clauses above.
    if any(body.get("investment_feedback_enabled") for body in _market_bodies(scenarios)) or any(
        option.get("investment_trigger")
        for participant in _year_participants(scenarios)
        for option in participant.get("technology_options") or []
    ):
        detected.add("endogenous_investment")

    return detected


def _scenario_market_ids(scenario: dict[str, Any]) -> list[str]:
    """This scenario's market ids (the manifest's D1-4 "markets" sub-key).

    Args:
        scenario: A normalised scenario dict.

    Returns:
        ``[]`` for a flat (single-market) scenario; the declared
        ``market_id`` order for a linked (multi-market) one
        (docs/platform-plan-d0-d1.md D1 "GRAPH DISENTANGLEMENT").
    """
    markets = scenario.get("markets")
    if not markets:
        return []
    return [str(market["market_id"]) for market in markets]


def _market_node_ids(nodes: list[Node], market_id: str) -> set[str]:
    """Node ids belonging to one market (``decompile.py``'s ``market{i}`` id
    plus every node id it prefixes, e.g. ``market0_pf``, ``market0_p0``)."""
    prefix = f"{market_id}_"
    return {n.id for n in nodes if n.id == market_id or n.id.startswith(prefix)}


def _features_for_blocks(block_ids: set[str]) -> set[str]:
    return {BLOCK_CATALOGUE.get(block_id).feature for block_id in block_ids}


def derive_manifest(config: dict[str, Any]) -> dict[str, Any]:
    """Derive the block/feature-module manifest of a scenario-config dict.

    Args:
        config: A ``{"scenarios": [...]}`` document (or anything
            ``config_io.normalize_config`` accepts — the same input
            ``ets.blocks.graph_from_config`` takes).

    Returns:
        A dict with:

        * ``features``: sorted list of every feature name in play across
          the whole config, always including ``"core"``.
        * ``blocks``: sorted list of every distinct block id the compiled
          graph uses.
        * ``approach``: sorted list of every price-formation approach any
          scenario resolves to (``"all"`` expanded per
          :func:`_scenario_approach`).
        * ``categories``: ``{category: [block_id, ...]}`` (each block-id
          list sorted), grouping ``blocks`` by
          :attr:`~ets.blocks.registry.BlockSpec.category`.
        * ``scenarios``: ``{scenario_name: {"features": [...],
          "approach": [...], "markets": [...]}}`` — scoped to one
          scenario's own nodes; ``"markets"`` is ``[]`` for a flat
          (single-market) scenario and the declared ``market_id`` order for
          a linked (multi-market) one (D1-4, :func:`_scenario_market_ids`;
          the ``market_links`` feature appears in ``"features"`` whenever a
          scenario carries at least one link, via the ordinary graph-derived
          path — no separate signal needed for that half).
    """
    normalized = normalize_config(config)
    graph = graph_from_config(normalized)
    blocks = sorted({node.block for node in graph.nodes})

    features = (
        {"core"}
        | _features_for_blocks(set(blocks))
        | _direct_detectors(normalized["scenarios"])
    )

    approach: set[str] = set()
    for scenario in normalized["scenarios"]:
        approach.update(_scenario_approach(scenario))

    categories: dict[str, list[str]] = {}
    for block_id in blocks:
        categories.setdefault(BLOCK_CATALOGUE.get(block_id).category, []).append(block_id)

    scenarios: dict[str, dict[str, Any]] = {}
    for index, scenario in enumerate(normalized["scenarios"]):
        market_node_ids = _market_node_ids(graph.nodes, f"market{index}")
        scenario_block_ids = {n.block for n in graph.nodes if n.id in market_node_ids}
        scenario_features = (
            {"core"}
            | _features_for_blocks(scenario_block_ids)
            | _direct_detectors([scenario])
        )
        scenarios[str(scenario["name"])] = {
            "features": sorted(scenario_features),
            "approach": _scenario_approach(scenario),
            "markets": _scenario_market_ids(scenario),
        }

    return {
        "features": sorted(features),
        "blocks": blocks,
        "approach": sorted(approach),
        "categories": categories,
        "scenarios": scenarios,
    }
