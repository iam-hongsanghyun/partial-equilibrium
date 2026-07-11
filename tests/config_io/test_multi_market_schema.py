"""D1-1/D1-4 gate: multi-market schema layer (docs/platform-plan-d0-d1.md D1).

Covers ``docs/platform-spec-d0-d1.md`` §2 (PriceLink semantics), §6
(parameters, all defaults inert) and the plan's D1 COMPAT RULE:

* (a) [REMOVED with the example library] The single-market byte-identical
  captured-baseline regression replayed several deleted ``examples/*.json``
  files against ``tests/config_io/snapshots/*.normalized.json``; its source
  configs are gone, so the replay was dropped. The degenerate-case machinery
  in (b) preserves the refactor guard on a recovered fixture.
* (b) ``config_io.iter_market_bodies`` returns ``[(None, scenario)]`` for a
  flat scenario and ``[(market_id, body), ...]`` for a hand-built
  multi-market config, in declaration order.
* (c) Link field validation: missing channel/phi/phi_unit, the
  implicit-"all" target rejection, the mac_cost/cost_slope dimensional
  exclusion (spec §2b), and the price_unit-touching requirement (spec
  §2e/§6).
* (d) D1-4: the D1-1 interim safety rail is RETIRED — ``markets``-shaped
  scenarios normalize successfully on every entry point, including the
  blocks decompile path (``docs/platform-plan-d0-d1.md`` D1 "GRAPH
  DISENTANGLEMENT"; graph-side coverage lives in
  ``tests/workflows/blocks/test_market_links_graph.py``).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pe.blocks import graph_from_config
from pe.config_io import (
    iter_market_bodies,
    normalize_config,
    normalize_joint_solver,
    normalize_scenario,
)

# TEST INFRA (not the example library): the canonical minimal competitive
# scenario recovered under tests/fixtures/ as a generic valid config. The
# byte-identical single-market baseline replay that used to live here was
# dropped with the example library it replayed (its source examples are gone);
# only the degenerate-case machinery below is preserved, re-pointed at the
# fixture.
MINIMAL_SCENARIO = (
    next(p for p in Path(__file__).resolve().parents if p.name == "tests")
    / "fixtures"
    / "minimal_scenario.json"
)


# ── (b) iter_market_bodies: degenerate vs multi-market ──────────────────────


def test_iter_market_bodies_degenerate_case_yields_none_keyed_scenario() -> None:
    raw = json.loads(MINIMAL_SCENARIO.read_text())
    scenario = raw["scenarios"][0]

    result = iter_market_bodies(scenario)

    assert [market_id for market_id, _ in result] == [None]
    assert result[0][1] == normalize_scenario(scenario)


def _market_body(
    participants: list[dict[str, Any]], *, price_unit: str | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "years": [
            {
                "year": "2030",
                "total_cap": 100.0,
                "auction_mode": "explicit",
                "auction_offered": 50.0,
                "price_lower_bound": 0.0,
                "price_upper_bound": 200.0,
                "participants": participants,
            }
        ],
    }
    if price_unit is not None:
        body["price_unit"] = price_unit
    return body


def _two_market_scenario(
    *,
    to_market_abatement_type: str = "threshold",
    from_price_unit: str | None = "USD/kgH2",
    to_price_unit: str | None = "USD/tCO2",
    link_overrides: dict[str, Any] | None = None,
    omit_link_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    """A 2-market ``{hydrogen -> steel}`` mac_cost link scenario (spec A4-style).

    ``hydrogen`` is the source market (``from_market``); ``steel`` is the
    target (``to_market``), carrying one participant ("SteelCo") with one
    flagged technology option ("H2-DRI") whose ``abatement_type`` is
    configurable — ``"threshold"`` (a valid mac_cost target, the threshold
    MAC level) by default, or ``"linear"`` to exercise the cost_slope
    dimensional exclusion (spec §2b).
    """
    hydrogen_market = _market_body(
        [{"name": "H2Producer", "initial_emissions": 50.0, "penalty_price": 100.0}],
        price_unit=from_price_unit,
    )
    hydrogen_market["market_id"] = "hydrogen"

    steel_participant = {
        "name": "SteelCo",
        "initial_emissions": 80.0,
        "penalty_price": 200.0,
        "technology_options": [
            {
                "name": "H2-DRI",
                "abatement_type": to_market_abatement_type,
                "threshold_cost": 40.0,
            }
        ],
    }
    steel_market = _market_body([steel_participant], price_unit=to_price_unit)
    steel_market["market_id"] = "steel"

    link: dict[str, Any] = {
        "from_market": "hydrogen",
        "to_market": "steel",
        "channel": "mac_cost",
        "phi": 30.0,
        "phi_unit": "kgH2/tCO2",
        "target_participants": ["SteelCo"],
        "target_technologies": ["H2-DRI"],
    }
    for key in omit_link_keys:
        link.pop(key, None)
    if link_overrides:
        link.update(link_overrides)

    return {
        "name": "Two-Market",
        "markets": [hydrogen_market, steel_market],
        "links": [link],
    }


def test_iter_market_bodies_multi_market_case_yields_ordered_ids_and_bodies() -> None:
    scenario = _two_market_scenario()

    result = iter_market_bodies(scenario)

    assert [market_id for market_id, _ in result] == ["hydrogen", "steel"]
    bodies = dict(result)
    assert bodies["hydrogen"]["years"][0]["participants"][0]["name"] == "H2Producer"
    assert bodies["hydrogen"]["price_unit"] == "USD/kgH2"
    assert bodies["steel"]["years"][0]["participants"][0]["name"] == "SteelCo"
    assert bodies["steel"]["price_unit"] == "USD/tCO2"
    # Market bodies never carry "name"/"policy_events" (scenario-only fields)
    # nor the accessor's own "market_id" bookkeeping key.
    assert "name" not in bodies["hydrogen"]
    assert "policy_events" not in bodies["hydrogen"]
    assert "market_id" not in bodies["hydrogen"]


def test_iter_market_bodies_market_body_matches_shared_single_market_internals() -> None:
    """A market body normalizes identically whether it arrives flat (today's
    single-market path) or inside 'markets' — the D1 COMPAT RULE's "reuse,
    don't duplicate" half."""
    participants = [{"name": "H2Producer", "initial_emissions": 50.0, "penalty_price": 100.0}]
    flat_scenario = {"name": "Flat", **_market_body(participants)}
    flat_body = normalize_scenario(flat_scenario)
    del flat_body["name"]
    del flat_body["policy_events"]

    multi_market_scenario = {
        "name": "Multi",
        "markets": [{"market_id": "only", **_market_body(participants)}],
    }
    multi_body = dict(iter_market_bodies(multi_market_scenario))["only"]

    assert multi_body == flat_body


def test_iter_market_bodies_rejects_duplicate_market_id() -> None:
    scenario = _two_market_scenario()
    scenario["markets"][1]["market_id"] = "hydrogen"
    with pytest.raises(ValueError, match="duplicate market_id"):
        iter_market_bodies(scenario)


def test_iter_market_bodies_rejects_empty_markets_list() -> None:
    with pytest.raises(ValueError, match="non-empty list"):
        iter_market_bodies({"name": "Empty", "markets": []})


# ── (c) link field validation ────────────────────────────────────────────────


def test_link_missing_channel_raises() -> None:
    scenario = _two_market_scenario(omit_link_keys=("channel",))
    with pytest.raises(ValueError, match="channel"):
        iter_market_bodies(scenario)


def test_link_missing_phi_raises() -> None:
    scenario = _two_market_scenario(omit_link_keys=("phi",))
    with pytest.raises(ValueError, match="phi"):
        iter_market_bodies(scenario)


def test_link_missing_phi_unit_raises() -> None:
    scenario = _two_market_scenario(omit_link_keys=("phi_unit",))
    with pytest.raises(ValueError, match="phi_unit"):
        iter_market_bodies(scenario)


def test_link_invalid_channel_raises() -> None:
    scenario = _two_market_scenario(link_overrides={"channel": "capped_pass_through"})
    with pytest.raises(ValueError, match="channel must be one of"):
        iter_market_bodies(scenario)


def test_link_implicit_all_target_participants_rejected() -> None:
    scenario = _two_market_scenario(link_overrides={"target_participants": []})
    with pytest.raises(ValueError, match="implicit 'all'"):
        iter_market_bodies(scenario)


def test_link_mac_cost_requires_target_technologies() -> None:
    scenario = _two_market_scenario(omit_link_keys=("target_technologies",))
    with pytest.raises(ValueError, match="target_technologies is REQUIRED"):
        iter_market_bodies(scenario)


def test_link_mac_cost_rejects_linear_cost_slope_target() -> None:
    """spec §2b: cost_slope [currency/t per Mt] is a SLOPE, dimensionally
    excluded from mac_cost's additive price-LEVEL shift."""
    scenario = _two_market_scenario(to_market_abatement_type="linear")
    with pytest.raises(ValueError, match="cost_slope"):
        iter_market_bodies(scenario)


def test_link_missing_price_unit_on_linked_market_raises() -> None:
    scenario = _two_market_scenario(to_price_unit=None)
    with pytest.raises(ValueError, match="price_unit"):
        iter_market_bodies(scenario)


def test_link_unknown_endpoint_market_raises() -> None:
    scenario = _two_market_scenario(link_overrides={"to_market": "no-such-market"})
    with pytest.raises(ValueError, match="unknown market"):
        iter_market_bodies(scenario)


def test_link_self_link_rejected() -> None:
    scenario = _two_market_scenario(link_overrides={"to_market": "hydrogen"})
    with pytest.raises(ValueError, match="self-links are forbidden"):
        iter_market_bodies(scenario)


def test_valid_two_market_link_normalizes_cleanly() -> None:
    """The base fixture itself must be valid — every negative test above
    mutates exactly one field away from this baseline."""
    result = iter_market_bodies(_two_market_scenario())
    assert [market_id for market_id, _ in result] == ["hydrogen", "steel"]


# ── (d) D1-4: the interim safety rail is retired — markets are wired ───────
# (docs/platform-plan-d0-d1.md D1 "GRAPH DISENTANGLEMENT"). A `markets`-shaped
# scenario now normalizes successfully everywhere `normalize_scenario` is
# reachable, instead of raising the D1-1 interim guard.


def test_normalize_scenario_normalizes_markets_key() -> None:
    scenario = _two_market_scenario()
    normalized = normalize_scenario(scenario)
    assert set(normalized) == {"name", "markets", "links"}
    assert [m["market_id"] for m in normalized["markets"]] == ["hydrogen", "steel"]
    assert len(normalized["links"]) == 1
    assert normalized["links"][0]["from_market"] == "hydrogen"


def test_normalize_config_normalizes_markets_key() -> None:
    config = {"scenarios": [_two_market_scenario()]}
    normalized = normalize_config(config)
    assert "markets" in normalized["scenarios"][0]


def test_decompile_path_handles_markets_key() -> None:
    """blocks.decompile.graph_from_config normalizes first — a markets-shaped
    scenario now decompiles into carbon_market + market_link nodes rather
    than raising the retired D1-1 guard."""
    config = {"scenarios": [_two_market_scenario()]}
    graph = graph_from_config(config)
    market_ids = {n.params.get("name") for n in graph.nodes if n.block == "carbon_market"}
    assert market_ids == {"hydrogen", "steel"}
    assert any(n.block == "market_link" for n in graph.nodes)


def test_normalize_scenario_markets_key_does_not_mutate_input() -> None:
    scenario = _two_market_scenario()
    before = copy.deepcopy(scenario)
    normalize_scenario(scenario)
    assert scenario == before


def test_normalize_scenario_markets_key_still_raises_on_invalid_links() -> None:
    """The retired guard's REMOVAL doesn't relax link validation — an invalid
    link on a markets-shaped scenario still raises (via validate_links)."""
    scenario = _two_market_scenario(omit_link_keys=("channel",))
    with pytest.raises(ValueError, match="channel"):
        normalize_scenario(scenario)


# ── (e) D2-3: the optional scenario `joint_solver` block (plan §4) ──────────
# The ONLY D2 schema addition. Absent => NO key emitted (byte-identical to a
# D1 config); present => normalizes with all keys defaulted and round-trips.


def test_joint_solver_absent_emits_no_key() -> None:
    """INERTNESS: a multi-market scenario without joint_solver never gains the key
    (the D1 COMPAT RULE — absent means 'no joint solver declared', not a default)."""
    normalized = normalize_scenario(_two_market_scenario())
    assert "joint_solver" not in normalized
    assert set(normalized) == {"name", "markets", "links"}


def test_joint_solver_absent_on_flat_single_market_emits_no_key() -> None:
    """A flat single-market scenario likewise never emits a joint_solver key."""
    flat = {
        "name": "Flat",
        **_market_body([{"name": "P", "initial_emissions": 50.0, "penalty_price": 100.0}]),
    }
    normalized = normalize_scenario(flat)
    assert "joint_solver" not in normalized


def test_joint_solver_present_normalizes_and_round_trips() -> None:
    """PRESENT (even empty {}) => a fully-defaulted settings dict, round-trippable."""
    scenario = _two_market_scenario()
    scenario["joint_solver"] = {}
    normalized = normalize_scenario(scenario)
    assert normalized["joint_solver"] == {
        "relaxation": 0.5,
        "tolerance": 1e-4,
        "max_iterations": 50,
        "sweep": "gauss_seidel",
        "initial_guess": "one_way_seed",
    }
    # Round-trips through JSON unchanged.
    assert json.loads(json.dumps(normalized))["joint_solver"] == normalized["joint_solver"]


def test_joint_solver_explicit_values_preserved() -> None:
    scenario = _two_market_scenario()
    scenario["joint_solver"] = {"relaxation": 0.3, "max_iterations": 80, "atol": 1e-6}
    js = normalize_scenario(scenario)["joint_solver"]
    assert js["relaxation"] == 0.3
    assert js["max_iterations"] == 80
    assert js["tolerance"] == 1e-6  # `atol` accepted as an alias for `tolerance`


def test_joint_solver_tolerance_takes_precedence_over_atol() -> None:
    assert normalize_joint_solver({"tolerance": 1e-5, "atol": 1e-3}, label="S")["tolerance"] == 1e-5


def test_joint_solver_none_returns_none() -> None:
    assert normalize_joint_solver(None, label="S") is None


@pytest.mark.parametrize(
    "block, match",
    [
        ({"relaxation": 0.0}, "relaxation must be in"),
        ({"relaxation": 1.5}, "relaxation must be in"),
        ({"tolerance": 0.0}, "must be > 0"),
        ({"max_iterations": 0}, "positive integer"),
        ({"sweep": "jacobi"}, "sweep must be one of"),
        ({"initial_guess": "warm"}, "initial_guess must be one of"),
    ],
)
def test_joint_solver_bounds_validated(block: dict[str, Any], match: str) -> None:
    """Every joint_solver setting is validated loudly — never a silent clamp."""
    with pytest.raises(ValueError, match=match):
        normalize_joint_solver(block, label="Scenario 'S'")
