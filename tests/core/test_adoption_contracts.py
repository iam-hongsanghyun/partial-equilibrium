"""Kernel adoption contracts (EI-3): spec bounds, canonical state, protocol.

Covers what ``docs/invest-feedback-plan.md`` "Kernel contracts" and the
binding spec (``docs/invest-feedback-spec.md`` D2/D6) require of
``ets.core.protocols``:

(a) ``AdoptionSpec`` validates every bound loudly — one ``ValueError`` per
    field, naming the field and the rule (spec D6 ranges);
(b) ``make_adoption_state`` rejects duplicate (participant, technology)
    pairs (irreversibility: at most one adoption per pair, spec D2.4) and
    sorts deterministically — value equality of the sorted tuple is the
    outer loop's convergence test;
(c) ``serialize_adoption_state``/``parse_adoption_state`` round-trip
    exactly, including the already-parsed list form (the splice carrier and
    the ``investment_initial_adoptions`` config field both land there);
(d) ``PathFeedback`` is ``runtime_checkable`` and a toy implementation
    conforms structurally;
(e) ``MarketParticipant`` old-style constructions are unaffected — the new
    ``adoption_specs`` field defaults to ``()`` both at direct construction
    and through ``build_markets_from_config`` (the banking-fixture path).
"""

from __future__ import annotations

import dataclasses
import json
import math
from typing import Any

import pytest

from ets.core.participant.models import MarketParticipant
from ets.core.protocols import (
    AdoptionEvent,
    AdoptionSpec,
    PathFeedback,
    make_adoption_state,
    parse_adoption_state,
    serialize_adoption_state,
)

# ── (a) AdoptionSpec validation bounds ───────────────────────────────────────


def _spec(**overrides: Any) -> AdoptionSpec:
    """Construct a valid spec (required fields only), then apply overrides."""
    kwargs: dict[str, Any] = {
        "participant_name": "Steel",
        "technology_name": "H2-DRI",
        "break_even": 80.0,
        "payout_yield": 0.03,
    }
    kwargs.update(overrides)
    return AdoptionSpec(**kwargs)


def test_spec_defaults_are_the_spec_d6_neutral_values() -> None:
    """Defaults match spec D6: sigma 0, q 0, r None, D-P mode, no lag."""
    spec = _spec()
    assert spec.sigma == 0.0
    assert spec.credibility == 0.0
    assert spec.discount_rate is None
    assert spec.trigger_mode == "dixit_pindyck"
    assert spec.trigger_multiple_override is None
    assert spec.build_lag_years == 0


def test_spec_is_frozen_and_keyword_only() -> None:
    """The contract object is immutable and never positionally constructed."""
    with pytest.raises(TypeError):
        AdoptionSpec("Steel", "H2-DRI", 80.0, 0.03)  # type: ignore[misc, call-arg]
    spec = _spec()
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.sigma = 0.2  # type: ignore[misc]


def test_spec_break_even_mapping_form_is_accepted() -> None:
    """Year-label thresholds (input-price-endogenous θ_t) validate."""
    spec = _spec(break_even={"2030": 100.0, "2031": 90.0})
    assert spec.break_even == {"2030": 100.0, "2031": 90.0}


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"participant_name": ""}, "participant_name"),
        ({"technology_name": ""}, "technology_name"),
        ({"break_even": 0.0}, "break_even"),
        ({"break_even": -5.0}, "break_even"),
        ({"break_even": math.nan}, "break_even"),
        ({"break_even": math.inf}, "break_even"),
        ({"break_even": {}}, "break_even"),
        ({"break_even": {"2030": 0.0}}, "break_even"),
        ({"break_even": {"": 80.0}}, "break_even"),
        ({"payout_yield": 0.0}, "payout_yield"),
        ({"payout_yield": -0.03}, "payout_yield"),
        ({"payout_yield": math.nan}, "payout_yield"),
        ({"sigma": -0.1}, "sigma"),
        ({"sigma": math.nan}, "sigma"),
        ({"credibility": -0.01}, "credibility"),
        ({"credibility": 1.01}, "credibility"),
        ({"credibility": math.nan}, "credibility"),
        ({"discount_rate": 0.0}, "discount_rate"),
        ({"discount_rate": -0.05}, "discount_rate"),
        ({"discount_rate": math.nan}, "discount_rate"),
        ({"trigger_mode": "npv"}, "trigger_mode"),
        ({"trigger_multiple_override": 0.99}, "trigger_multiple_override"),
        ({"trigger_multiple_override": math.nan}, "trigger_multiple_override"),
        ({"build_lag_years": -1}, "build_lag_years"),
        ({"build_lag_years": 1.5}, "build_lag_years"),
        ({"build_lag_years": True}, "build_lag_years"),
    ],
)
def test_spec_bound_violations_raise_naming_the_field(
    overrides: dict[str, Any], match: str
) -> None:
    """Every out-of-range field raises ValueError naming that field."""
    with pytest.raises(ValueError, match=match):
        _spec(**overrides)


def test_spec_boundary_values_are_accepted() -> None:
    """Closed-interval endpoints validate: q ∈ {0, 1}, M_override = 1, L = 0."""
    _spec(credibility=0.0)
    _spec(credibility=1.0)
    _spec(trigger_multiple_override=1.0)
    _spec(build_lag_years=0)
    _spec(trigger_mode="break_even")


# ── (b) Canonical state: sorting determinism + duplicate rejection ──────────


def _events() -> list[AdoptionEvent]:
    return [
        AdoptionEvent(participant_name="Steel", technology_name="H2-DRI", adoption_year="2033"),
        AdoptionEvent(participant_name="Cement", technology_name="CCS", adoption_year="2031"),
        AdoptionEvent(participant_name="Steel", technology_name="CCS", adoption_year="2035"),
    ]


def test_state_sorts_by_participant_then_technology() -> None:
    """Canonical order is (participant_name, technology_name)."""
    state = make_adoption_state(_events())
    assert [(e.participant_name, e.technology_name) for e in state] == [
        ("Cement", "CCS"),
        ("Steel", "CCS"),
        ("Steel", "H2-DRI"),
    ]


def test_state_construction_is_order_insensitive() -> None:
    """Any input order yields the SAME tuple — the convergence-test equality."""
    events = _events()
    state = make_adoption_state(events)
    assert make_adoption_state(reversed(events)) == state
    assert make_adoption_state([events[1], events[2], events[0]]) == state


def test_duplicate_pair_rejected_even_with_distinct_years() -> None:
    """At most one adoption per (participant, technology) — spec D2.4."""
    dupe = AdoptionEvent(participant_name="Steel", technology_name="CCS", adoption_year="2040")
    with pytest.raises(ValueError, match="duplicate adoption"):
        make_adoption_state([*_events(), dupe])


def test_exact_duplicate_event_also_rejected() -> None:
    """An identical repeated event is still a duplicate pair."""
    events = _events()
    with pytest.raises(ValueError, match="duplicate adoption"):
        make_adoption_state([*events, events[0]])


def test_empty_state_is_the_empty_tuple() -> None:
    state = make_adoption_state([])
    assert state == ()


def test_event_fields_must_be_non_empty_strings() -> None:
    """Year LABELS (market.year string semantics), never empty/numeric."""
    with pytest.raises(ValueError, match="adoption_year"):
        AdoptionEvent(participant_name="Steel", technology_name="CCS", adoption_year="")


# ── (c) Serialize / parse round-trip ─────────────────────────────────────────


def test_serialize_is_deterministic_across_input_orders() -> None:
    """Equal states serialize byte-identically regardless of event order."""
    events = _events()
    text_a = serialize_adoption_state(make_adoption_state(events))
    text_b = serialize_adoption_state(tuple(reversed(make_adoption_state(events))))
    assert text_a == text_b


def test_round_trip_through_json_string() -> None:
    state = make_adoption_state(_events())
    text = serialize_adoption_state(state)
    assert parse_adoption_state(text) == state
    # Idempotent: re-serializing the parse reproduces the exact string.
    assert serialize_adoption_state(parse_adoption_state(text)) == text


def test_round_trip_through_parsed_list_form() -> None:
    """The config field lands an already-parsed list of dicts — same result."""
    state = make_adoption_state(_events())
    as_list = json.loads(serialize_adoption_state(state))
    assert isinstance(as_list, list)
    assert parse_adoption_state(as_list) == state


def test_empty_state_round_trips() -> None:
    assert serialize_adoption_state(()) == "[]"
    assert parse_adoption_state("[]") == ()
    assert parse_adoption_state([]) == ()


def test_serialized_form_is_the_documented_key_set() -> None:
    """Spec D3.4: {"participant", "technology", "adoption_year"} objects."""
    state = make_adoption_state(_events()[:1])
    payload = json.loads(serialize_adoption_state(state))
    assert payload == [{"adoption_year": "2033", "participant": "Steel", "technology": "H2-DRI"}]


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ("not json", "not valid JSON"),
        ('{"participant": "Steel"}', "expected a JSON array"),
        ([{"participant": "Steel", "technology": "CCS"}], "missing key"),
        (["Steel"], "must be a mapping"),
    ],
)
def test_parse_rejects_malformed_payloads(payload: Any, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_adoption_state(payload)


def test_parse_rejects_duplicate_pairs() -> None:
    """Duplicate rejection applies to parsed payloads too (carrier safety)."""
    rows = [
        {"participant": "Steel", "technology": "CCS", "adoption_year": "2031"},
        {"participant": "Steel", "technology": "CCS", "adoption_year": "2032"},
    ]
    with pytest.raises(ValueError, match="duplicate adoption"):
        parse_adoption_state(rows)


# ── (d) PathFeedback runtime_checkable conformance ───────────────────────────


class _ToyFeedback:
    """Structural toy: proposes no new adoptions, applies the identity."""

    def propose(
        self,
        price_path: dict[str, float],
        state: tuple[AdoptionEvent, ...],
        markets: list[Any],
    ) -> tuple[tuple[AdoptionEvent, ...], dict[str, float]]:
        return state, {"toy_crossings": 0.0}

    def apply(self, ordered_markets: list[Any], state: tuple[AdoptionEvent, ...]) -> list[Any]:
        return ordered_markets


class _NotFeedback:
    """Missing ``apply`` — must NOT satisfy the protocol."""

    def propose(self) -> None:  # pragma: no cover - structure only
        return None


def test_toy_implementation_satisfies_the_protocol() -> None:
    toy = _ToyFeedback()
    assert isinstance(toy, PathFeedback)
    state = make_adoption_state(_events())
    proposal, metrics = toy.propose({"2030": 10.0}, state, [])
    assert proposal == state
    assert metrics == {"toy_crossings": 0.0}
    markets: list[Any] = []
    assert toy.apply(markets, state) is markets


def test_incomplete_implementation_fails_isinstance() -> None:
    assert not isinstance(_NotFeedback(), PathFeedback)


# ── (e) MarketParticipant: old-style constructions unaffected ────────────────


def test_direct_construction_defaults_adoption_specs_to_empty() -> None:
    """Bare kwargs construction (the reporting-columns fixture style)."""
    participant = MarketParticipant(
        name="P1",
        initial_emissions=100.0,
        marginal_abatement_cost=10.0,
        free_allocation_ratio=0.5,
        penalty_price=100.0,
    )
    assert participant.adoption_specs == ()


def test_config_built_participants_default_adoption_specs_to_empty() -> None:
    """The banking-fixture path (build_markets_from_config) is untouched."""
    from ets.config_io import build_markets_from_config

    config = {
        "scenarios": [
            {
                "name": "adoption-contract-neutrality",
                "model_approach": "banking",
                "discount_rate": 0.05,
                "banking_initial_bank": 0.0,
                "years": [
                    {
                        "year": "2030",
                        "total_cap": 95.0,
                        "auction_mode": "derive_from_cap",
                        "banking_allowed": False,
                        "borrowing_allowed": False,
                        "expectation_rule": "next_year_baseline",
                        "price_lower_bound": 0.0,
                        "price_upper_bound": 100000.0,
                        "participants": [
                            {
                                "name": "Industry",
                                "initial_emissions": 100.0,
                                "free_allocation_ratio": 0.0,
                                "penalty_price": 0.0,
                                "abatement_type": "linear",
                                "max_abatement": 100.0,
                                "cost_slope": 100.0,
                            }
                        ],
                    }
                ],
            }
        ]
    }
    markets = build_markets_from_config(config)
    assert markets, "config build produced no markets"
    for market in markets:
        for participant in market.participants:
            assert participant.adoption_specs == ()
