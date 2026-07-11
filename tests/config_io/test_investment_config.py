"""EI-6 gate: the endogenous-investment feature is CONFIG-DRIVEN end to end.

Covers ``docs/invest-feedback-plan.md`` EI-6 / ``docs/invest-feedback-spec.md``
D6:

* ``normalize_technology_option`` delegates ``investment_trigger`` content
  validation to ``features.endogenous_investment.plugin
  .normalize_investment_trigger`` (config_io -> plugin door), tolerates
  absence (default ``{}``), and surfaces validation errors with the
  participant/technology names.
* ``normalize_scenario`` gains the four scenario-level fields, all inert by
  default, with the documented bound checks.
* The builder's loud guards fire in BOTH directions (spec D3.2 arbitration:
  ``ValueError``, never a warning), plus the v1 approach-coverage guard
  (competitive/banking only).
* Specs are attached with the scenario ``invest_credibility`` override
  applied, and the three ``investment_*`` fields are stamped onto every
  market (``m0`` is what the dispatch guard reads).
* END-TO-END: a tiny competitive scenario built ENTIRELY FROM A CONFIG DICT
  (flag + one flagged option, theta between the year-1/year-2 analytic
  prices) drives real adoption through ``run_simulation_from_config`` — the
  first config-driven activation, proving EI-5 (engine host) and EI-6
  (config door) compose.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from ets import run_simulation_from_config
from ets.config_io import (
    blank_scenario,
    blank_technology_option,
    build_markets_from_config,
    normalize_scenario,
    normalize_technology_option,
)
from ets.core.protocols import AdoptionEvent, make_adoption_state, serialize_adoption_state

R = 0.055  # scenario discount rate r [1/yr]
Y = 0.03  # payout yield y [1/yr]

_INVESTMENT_COLUMNS = [
    "Investment Adoptions",
    "Investment Newly Effective",
    "Investment Feedback Iterations",
    "Investment Converged",
]


# ── normalize_technology_option: investment_trigger content validation ──────


def test_normalize_technology_option_tolerates_absence() -> None:
    """No ``investment_trigger`` key anywhere: the returned dict still always
    carries the key (default ``{}``) — the catalogue's config_key-existence
    drift guard (tests/workflows/blocks/test_blocks_catalogue.py) depends on
    this — while the *template* stays untouched (config-driven display
    principle: blank stays blank)."""
    assert "investment_trigger" not in blank_technology_option()
    option = normalize_technology_option(blank_technology_option(), "Steel")
    assert option["investment_trigger"] == {}


def test_normalize_technology_option_validates_and_preserves_wire_format() -> None:
    """A valid sub-dict round-trips UNCHANGED (the wire-format keys, never
    the internal AdoptionSpec kwargs shape — compile.py/decompile.py pass it
    through opaquely)."""
    raw = blank_technology_option()
    raw["name"] = "H2-DRI"
    raw["investment_trigger"] = {"break_even_price": 80.0, "payout_yield": 0.03}
    option = normalize_technology_option(raw, "Steel")
    assert option["investment_trigger"] == {"break_even_price": 80.0, "payout_yield": 0.03}


@pytest.mark.parametrize(
    ("trigger", "match"),
    [
        # Structural violations: the plugin door's own label names both.
        ({"payout_yield": 0.03}, "Steel/H2-DRI investment_trigger.*exactly ONE"),
        ({"break_even_price": 80.0}, "Steel/H2-DRI investment_trigger.*payout_yield"),
        # Bound violation: AdoptionSpec's own __post_init__ label names both
        # (a different message shape, but still names the offending pair).
        (
            {"break_even_price": 80.0, "payout_yield": 0.03, "credibility": 5.0},
            r"AdoptionSpec\('Steel', 'H2-DRI'\).*credibility",
        ),
    ],
)
def test_normalize_technology_option_surfaces_participant_and_technology_names(
    trigger: dict[str, Any], match: str
) -> None:
    raw = blank_technology_option()
    raw["name"] = "H2-DRI"
    raw["investment_trigger"] = trigger
    with pytest.raises(ValueError, match=match):
        normalize_technology_option(raw, "Steel")


# ── normalize_scenario: the four scenario-level fields ──────────────────────


def _scenario(**overrides: Any) -> dict[str, Any]:
    scenario = blank_scenario()
    scenario["name"] = "S"
    scenario.update(overrides)
    return scenario


def test_normalize_scenario_investment_defaults_are_inert() -> None:
    scenario = normalize_scenario(_scenario())
    assert scenario["investment_feedback_enabled"] is False
    assert scenario["investment_max_iterations"] is None
    assert scenario["investment_initial_adoptions"] == []
    assert scenario["invest_credibility"] is None


def test_normalize_scenario_investment_round_trip() -> None:
    adoptions = [{"participant": "Steel", "technology": "H2-DRI", "adoption_year": "2030"}]
    scenario = normalize_scenario(
        _scenario(
            investment_feedback_enabled=True,
            investment_max_iterations=4,
            investment_initial_adoptions=adoptions,
            invest_credibility=0.3,
        )
    )
    assert scenario["investment_feedback_enabled"] is True
    assert scenario["investment_max_iterations"] == 4
    assert scenario["investment_initial_adoptions"] == adoptions
    assert scenario["invest_credibility"] == 0.3


@pytest.mark.parametrize("bad_value", [0, -1])
def test_normalize_scenario_investment_max_iterations_must_be_positive(bad_value: int) -> None:
    with pytest.raises(ValueError, match="investment_max_iterations"):
        normalize_scenario(_scenario(investment_max_iterations=bad_value))


@pytest.mark.parametrize("bad_value", [-0.1, 1.5])
def test_normalize_scenario_invest_credibility_bounds(bad_value: float) -> None:
    with pytest.raises(ValueError, match="invest_credibility"):
        normalize_scenario(_scenario(invest_credibility=bad_value))


# ── Builder loud guards + spec attachment + m0 stamping ──────────────────────


def _plain_config(name: str, **scenario_overrides: Any) -> dict[str, Any]:
    scenario: dict[str, Any] = {
        "name": name,
        "model_approach": "competitive",
        "years": [
            {
                "year": "2030",
                "total_cap": 100.0,
                "auction_mode": "explicit",
                "auction_offered": 50.0,
                "participants": [
                    {
                        "name": "Steel",
                        "initial_emissions": 100.0,
                        "penalty_price": 1000.0,
                        "abatement_type": "linear",
                        "max_abatement": 20.0,
                        "cost_slope": 2.0,
                    }
                ],
            }
        ],
    }
    scenario.update(scenario_overrides)
    return {"scenarios": [scenario]}


def _flagged_technology_option(theta: float = 80.0) -> dict[str, Any]:
    return {
        "name": "H2-DRI",
        "initial_emissions": 40.0,
        "abatement_type": "linear",
        "max_abatement": 40.0,
        "cost_slope": 2.0,
        "max_activity_share": 0.5,
        "investment_trigger": {
            "break_even_price": theta,
            "payout_yield": Y,
            "trigger_mode": "break_even",
        },
    }


def test_builder_guard_flag_true_zero_flagged_options_raises() -> None:
    config = _plain_config("flag-only", investment_feedback_enabled=True)
    with pytest.raises(ValueError, match="no technology option"):
        build_markets_from_config(config)


def test_builder_guard_flagged_option_flag_false_raises() -> None:
    config = _plain_config("option-only")
    config["scenarios"][0]["years"][0]["participants"][0]["technology_options"] = [
        _flagged_technology_option()
    ]
    with pytest.raises(ValueError, match="investment_feedback_enabled is false"):
        build_markets_from_config(config)


def test_builder_guard_v1_approach_coverage_rejects_hotelling() -> None:
    config = _plain_config(
        "wrong-approach", model_approach="hotelling", investment_feedback_enabled=True
    )
    config["scenarios"][0]["years"][0]["participants"][0]["technology_options"] = [
        _flagged_technology_option()
    ]
    with pytest.raises(ValueError, match="v1 approach coverage"):
        build_markets_from_config(config)


def test_builder_attaches_specs_with_scenario_credibility_override() -> None:
    config = _plain_config("credibility-override", investment_feedback_enabled=True, invest_credibility=0.7)
    config["scenarios"][0]["years"][0]["participants"][0]["technology_options"] = [
        _flagged_technology_option()
    ]
    markets = build_markets_from_config(config)
    m0 = sorted(markets, key=lambda m: float(str(m.year)))[0]
    specs = m0.participants[0].adoption_specs
    assert len(specs) == 1
    assert specs[0].credibility == 0.7


def test_builder_specs_default_credibility_without_override() -> None:
    config = _plain_config("no-credibility-override", investment_feedback_enabled=True)
    config["scenarios"][0]["years"][0]["participants"][0]["technology_options"] = [
        _flagged_technology_option()
    ]
    markets = build_markets_from_config(config)
    m0 = sorted(markets, key=lambda m: float(str(m.year)))[0]
    assert m0.participants[0].adoption_specs[0].credibility == 0.0


def test_builder_stamps_m0_investment_fields() -> None:
    config = _plain_config(
        "m0-stamping", investment_feedback_enabled=True, investment_max_iterations=5
    )
    config["scenarios"][0]["years"][0]["participants"][0]["technology_options"] = [
        _flagged_technology_option()
    ]
    markets = build_markets_from_config(config)
    m0 = sorted(markets, key=lambda m: float(str(m.year)))[0]
    assert m0.investment_feedback_enabled is True
    assert m0.investment_max_iterations == 5
    assert m0.investment_initial_adoptions == []


def test_unflagged_scenario_stays_off_by_default() -> None:
    """No flag anywhere: the master gate stamps False and no specs attach —
    the off-by-default proof chain's config_io half."""
    config = _plain_config("neutral")
    markets = build_markets_from_config(config)
    for market in markets:
        assert market.investment_feedback_enabled is False
        assert market.participants[0].adoption_specs == ()


# ── END-TO-END: config-driven activation through run_simulation_from_config ─


def _investment_config(
    theta: float, *, max_iterations: int | None = None, credibility: float | None = None
) -> dict[str, Any]:
    """3-year, 1-participant linear-MAC economy, ENTIRELY as a config dict.

    Analytic OFF anchor (same economy as tests/engine/test_investment_feedback
    .py's own ``_linear_config``): competitive clearing on E - P/2 = S_t gives
    P_t = 2(E - S_t) -> 80 / 100 / 120 for S = 60 / 50 / 40 [Mt]. One flagged
    technology option (H2-DRI) with break-even dating at ``theta``, between
    the year-1 (80) and year-2 (100) analytic prices -> adoption year 2032.
    """
    technology_options = [_flagged_technology_option(theta)]
    years = []
    for year, supply in (("2031", 60.0), ("2032", 50.0), ("2033", 40.0)):
        years.append(
            {
                "year": year,
                "total_cap": supply,
                "auction_mode": "derive_from_cap",
                "price_lower_bound": 0.0,
                "price_upper_bound": 100000.0,
                "participants": [
                    {
                        "name": "Steel",
                        "initial_emissions": 100.0,
                        "penalty_price": 1000.0,
                        "abatement_type": "linear",
                        "max_abatement": 100.0,
                        "cost_slope": 2.0,
                        "technology_options": technology_options,
                    }
                ],
            }
        )
    scenario: dict[str, Any] = {
        "name": "config-driven-e2e",
        "model_approach": "competitive",
        "discount_rate": R,
        "investment_feedback_enabled": True,
        "years": years,
    }
    if max_iterations is not None:
        scenario["investment_max_iterations"] = max_iterations
    if credibility is not None:
        scenario["invest_credibility"] = credibility
    return {"scenarios": [scenario]}


def test_end_to_end_config_driven_activation() -> None:
    """First config-driven activation of the investment feedback loop
    (EI-6): a JSON-shaped config dict drives real adoption end to end
    through ``run_simulation_from_config`` — proving EI-5 (engine host) and
    EI-6 (config door) compose."""
    summary, participants = run_simulation_from_config(_investment_config(90.0))

    # Tail placement: the four investment columns are the LAST summary columns.
    assert list(summary.columns[-4:]) == _INVESTMENT_COLUMNS

    rows = {str(row["Year"]): row for _, row in summary.iterrows()}
    event = AdoptionEvent(participant_name="Steel", technology_name="H2-DRI", adoption_year="2032")
    expected_serialized = serialize_adoption_state(make_adoption_state([event]))
    assert rows["2031"]["Investment Adoptions"] == "[]"
    assert rows["2032"]["Investment Adoptions"] == expected_serialized
    assert rows["2033"]["Investment Adoptions"] == expected_serialized
    np.testing.assert_allclose(
        [rows[y]["Investment Newly Effective"] for y in ("2031", "2032", "2033")],
        [0.0, 1.0, 0.0],
        rtol=0,
        atol=0,
    )
    np.testing.assert_allclose(float(rows["2033"]["Investment Converged"]), 1.0, rtol=0, atol=0)

    # Pre-adoption year: bit-identical to the analytic OFF economy (anchor
    # V3 — "feature ON but never triggered" == "option deleted").
    np.testing.assert_allclose(
        float(rows["2031"]["Equilibrium Carbon Price"]), 80.0, rtol=1e-6
    )
    # Post-adoption years: the entrant capacity visibly lowers the price
    # below the un-masked analytic values (100 / 120).
    assert float(rows["2032"]["Equilibrium Carbon Price"]) < 100.0
    assert float(rows["2033"]["Equilibrium Carbon Price"]) < 120.0

    steel = participants[participants["Participant"] == "Steel"]
    mix_by_year = {
        str(row["Year"]): f"{row['Chosen Technology']} | {row['Technology Mix']}"
        for _, row in steel.iterrows()
    }
    assert "H2-DRI" not in mix_by_year["2031"]
    assert "H2-DRI" in mix_by_year["2032"]
    assert "H2-DRI" in mix_by_year["2033"]


def test_end_to_end_config_driven_activation_respects_max_iterations_override() -> None:
    """A scenario-level ``investment_max_iterations`` override reaches the
    engine's safety rail via m0 (no crash; still converges well within a
    generous cap for this one-flagged-pair economy)."""
    summary, _ = run_simulation_from_config(_investment_config(90.0, max_iterations=3))
    rows = {str(row["Year"]): row for _, row in summary.iterrows()}
    np.testing.assert_allclose(float(rows["2033"]["Investment Converged"]), 1.0, rtol=0, atol=0)
