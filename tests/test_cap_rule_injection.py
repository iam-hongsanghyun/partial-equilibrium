r"""Regression tests for cap-rule injection on the competitive pipeline (O5).

Reference
---------
``docs/feature-modules-plan.md`` — work order O5 (v1 §4, PLAN v2 §2 protocol
family) and the economist's binding conditions: split gating for the CCR
(record has NO start-year gate — economics), a rule-free expectations inner
loop (R29, ``docs/blocks-composition-rules.md``), and a pinned λ+MSR anchor
(the combination has no golden coverage) required before later orders touch
the transmission wiring.

The injected rules (``MSRCapRule``, ``CCRCapRule``) are lifted verbatim from
``solvers/simulation.py``'s per-year blocks, so every number here is also a
regression anchor for the pre-injection behaviour.

Test design (end-to-end scenarios, hand-solvable):
    A single Buyer with a linear unit-slope MAC (cost = 0.5 a², MAC = a) and
    no free allocation demands D(p) = 100 - p, so clearing satisfies
    p_t = 100 - Q_t and the realised aggregates are e_t = 100 - p_t,
    z_t = 0.5 p_t².

    CCR start-year scenario (ccr_start_year = 2032 > first year 2030):
      2030: Q = 80 -> p = 20, e = 80, z = 200   (pre-start: recorded, no ΔQ)
      2031: Q = 90 -> p = 10, e = 90, z = 50    (pre-start: recorded, no ΔQ)
      2032: first ACTIVE year prices the LAST pre-start year's outcomes
            (e_31, z_31) = (90, 50), NOT (e_30, z_30) and NOT "no history":
            ΔQ = -50·(90-100)/100 + 40·(50-400)/400 = +5 - 35 = -30
            -> Q = 50, p = 50.
      A (wrong) start-year gate on record() would give ΔQ = 0, p = 20; a
      (wrong) 2030 signal would give ΔQ = -10, p = 30 — both far outside
      the asserted tolerance.

    R29 scenario (perfect_foresight + MSR): banking disabled, so expected
    prices are decorative for behaviour and purely measure expectation
    formation. msr_upper_threshold = -5 makes the zero bank trigger a 25 %
    withhold every year:
      rule-free prices: (20, 30);  MSR-adjusted prices: (40, 47.5).
    Perfect foresight must price the RULE-FREE path: expected[2030] = 30,
    not 47.5 (``simulation.py`` inner loop passes an empty rule list).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ets.config_io import build_markets_from_config
from ets.core.protocols import CapRule
from ets.solvers import run_simulation_from_config, solve_scenario_path
from ets.solvers.ccr import CCRCapRule, CCRState
from ets.solvers.msr import MSRCapRule, MSRState
from ets.core.ledger import simulate_path_details as _simulate_path_details

# Participant abatement optima come from bounded scalar minimisation
# (xatol ~1e-5), so hand values are matched to ~1e-4; atol=1e-3 is safely
# above solver noise and far below every discriminating gap below (>= 10).
ATOL = 1e-3


# ── Closed form: gating and additive-delta arithmetic of the rules ───────────


def _msr_market(year: str, *, enabled: bool = True, start_year: float = 0.0):
    return SimpleNamespace(
        year=year,
        msr_enabled=enabled,
        msr_start_year=start_year,
        auction_offered=80.0,
        msr_upper_threshold=20.0,
        msr_lower_threshold=10.0,
        msr_withhold_rate=0.25,
        msr_release_rate=15.0,
        msr_cancel_excess=False,
        msr_cancel_threshold=400.0,
    )


def _ccr_market(year: str, *, enabled: bool = True, start_year: float = 0.0):
    return SimpleNamespace(
        year=year,
        ccr_enabled=enabled,
        ccr_start_year=start_year,
        ccr_phi_emissions=-50.0,
        ccr_phi_abatement_cost=40.0,
        ccr_reference_emissions=100.0,
        ccr_reference_abatement_cost=400.0,
    )


def test_cap_rules_satisfy_the_protocol():
    """Both implementations structurally satisfy core.protocols.CapRule."""
    assert isinstance(MSRCapRule(), CapRule)
    assert isinstance(CCRCapRule(), CapRule)


def test_msr_pre_clear_is_gated_by_flag_and_start_year():
    """pre_clear: enabled flag AND year >= msr_start_year, else ΔQ = 0."""
    rule = MSRCapRule(MSRState())
    bank = {"Buyer": 25.0}  # above the 20 Mt upper threshold

    # Pre-start year: no adjustment, no pool movement.
    delta, diags = rule.pre_clear(_msr_market("2031", start_year=2032.0), bank)
    assert (delta, diags["msr_withheld"], diags["msr_pool"]) == (0.0, 0.0, 0.0)
    assert rule.msr_state.reserve_pool == 0.0

    # Disabled flag: no adjustment even past the start year.
    delta, _ = rule.pre_clear(_msr_market("2032", enabled=False), bank)
    assert delta == 0.0

    # Active year: withhold 0.25 * 80 = 20 Mt, ΔQ = released - withheld = -20.
    delta, diags = rule.pre_clear(_msr_market("2032", start_year=2032.0), bank)
    np.testing.assert_allclose(delta, -20.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_withheld"], 20.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_pool"], 20.0, rtol=0, atol=1e-12)


def test_msr_pre_clear_release_is_a_positive_delta():
    """ΔQ = released - withheld: a funded release adds supply."""
    rule = MSRCapRule(MSRState(initial_reserve=30.0))
    delta, diags = rule.pre_clear(_msr_market("2030"), {"Buyer": 5.0})
    np.testing.assert_allclose(delta, 15.0, rtol=0, atol=1e-12)  # min(15, 30)
    np.testing.assert_allclose(diags["msr_released"], 15.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_pool"], 15.0, rtol=0, atol=1e-12)


def test_ccr_record_has_no_start_year_gate_and_prices_the_lagged_signal():
    """Split gating, closed form: pre-start years record; the first active
    year prices the LAST pre-start year's (e, z)."""
    rule = CCRCapRule(CCRState())

    # 2030, pre-start (start 2032): no adjustment...
    delta, diags = rule.pre_clear(_ccr_market("2030", start_year=2032.0), {})
    assert delta == 0.0
    assert diags == {
        "ccr_adjustment": 0.0,
        "ccr_emissions_deviation": 0.0,
        "ccr_cost_deviation": 0.0,
    }
    # ...but post_clear records (flag-only gate).
    rule.post_clear(
        _ccr_market("2030", start_year=2032.0),
        pd.DataFrame({"Residual Emissions": [80.0], "Abatement Cost": [200.0]}),
    )
    # 2031, still pre-start: records again, overwriting the lagged signal.
    delta, _ = rule.pre_clear(_ccr_market("2031", start_year=2032.0), {})
    assert delta == 0.0
    rule.post_clear(
        _ccr_market("2031", start_year=2032.0),
        pd.DataFrame({"Residual Emissions": [90.0], "Abatement Cost": [50.0]}),
    )

    # 2032, first active year: ΔQ from (e_31, z_31) = (90, 50):
    #   -50*(90-100)/100 + 40*(50-400)/400 = +5 - 35 = -30.
    delta, diags = rule.pre_clear(_ccr_market("2032", start_year=2032.0), {})
    np.testing.assert_allclose(delta, -30.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["ccr_emissions_deviation"], -0.10, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["ccr_cost_deviation"], -0.875, rtol=0, atol=1e-12)
    # Had record() been (wrongly) start-year gated there would be no history
    # (ΔQ = 0); had the signal come from 2030, ΔQ = -50*(-0.2) + 40*(-0.5) = -10.
    assert abs(delta - 0.0) > 10.0
    assert abs(delta - (-10.0)) > 10.0


def test_ccr_post_clear_flag_gate_blocks_recording():
    """post_clear with ccr_enabled=False must not touch the lagged state."""
    rule = CCRCapRule(CCRState())
    rule.post_clear(
        _ccr_market("2030", enabled=False),
        pd.DataFrame({"Residual Emissions": [80.0], "Abatement Cost": [200.0]}),
    )
    assert rule.ccr_state.prev_emissions is None
    assert rule.ccr_state.prev_abatement_cost is None


# ── The engine's default cap-rule wiring on simulate_path_details ────────────
# (The legacy msr_state=/ccr_state= kwargs and their translation retired at
# the hotelling/nash feature move, v1 O11 / v2 O15; these tests now pin the
# wiring-default ≡ hand-injected equivalence and the kwargs' retirement.)


def _buyer(max_abatement: float = 100.0) -> dict:
    return {
        "name": "Buyer",
        "initial_emissions": 100.0,
        "free_allocation_ratio": 0.0,
        "penalty_price": 1000.0,
        "abatement_type": "linear",
        "max_abatement": max_abatement,
        "cost_slope": 1.0,
    }


def _banker() -> dict:
    return {
        "name": "Banker",
        "initial_emissions": 50.0,
        "free_allocation_ratio": 1.0,
        "penalty_price": 1000.0,
        "abatement_type": "linear",
        "max_abatement": 60.0,
        "cost_slope": 1.0,
    }


def _year(
    label: str,
    auction: float,
    *,
    banking: bool,
    expectation_rule: str = "manual",
    manual_expected_price: float = 0.0,
    participants: list[dict] | None = None,
) -> dict:
    return {
        "year": label,
        "total_cap": 130.0,
        "auction_mode": "explicit",
        "auction_offered": auction,
        "price_lower_bound": 0.0,
        "price_upper_bound": 300.0,
        "banking_allowed": banking,
        "expectation_rule": expectation_rule,
        "manual_expected_price": manual_expected_price,
        "participants": participants if participants is not None else [_buyer()],
    }


def _both_rules_scenario() -> dict:
    """The test_msr_ccr_composition 'Both' scenario (known hand solution)."""
    years = [
        _year(
            "2030",
            80.0,
            banking=True,
            manual_expected_price=25.0,
            participants=[_buyer(), _banker()],
        ),
        _year(
            "2031",
            80.0,
            banking=True,
            manual_expected_price=45.0,
            participants=[_buyer(), _banker()],
        ),
    ]
    return {
        "name": "Both",
        "model_approach": "competitive",
        "msr_enabled": True,
        "msr_upper_threshold": 20.0,
        "msr_lower_threshold": 0.0,
        "msr_withhold_rate": 0.25,
        "msr_release_rate": 0.0,
        "ccr_enabled": True,
        "ccr_phi_emissions": -50.0,
        "ccr_phi_abatement_cost": 40.0,
        "ccr_reference_emissions": 100.0,
        "ccr_reference_abatement_cost": 500.0,
        "years": years,
    }


def test_default_wiring_matches_explicitly_injected_rules():
    """default_cap_rules(m0, "competitive") and cap_rules=[CCR, MSR] solve
    identical paths (formerly the legacy-kwarg translation test; the
    expected numbers are unchanged)."""
    from ets.engine import default_cap_rules

    expected = {"2030": 25.0, "2031": 45.0}

    wired_markets = build_markets_from_config({"scenarios": [_both_rules_scenario()]})
    legacy = _simulate_path_details(
        wired_markets,
        expected,
        cap_rules=default_cap_rules(wired_markets[0], "competitive"),
    )
    injected = _simulate_path_details(
        build_markets_from_config({"scenarios": [_both_rules_scenario()]}),
        expected,
        cap_rules=[CCRCapRule(CCRState()), MSRCapRule(MSRState())],
    )

    assert len(legacy) == len(injected) == 2
    for a, b in zip(legacy, injected):
        np.testing.assert_allclose(
            float(a["equilibrium"]["price"]),
            float(b["equilibrium"]["price"]),
            rtol=0,
            atol=1e-12,
        )
        for key in (
            "msr_withheld",
            "msr_released",
            "msr_pool",
            "ccr_adjustment",
            "ccr_emissions_deviation",
            "ccr_cost_deviation",
        ):
            np.testing.assert_allclose(float(a[key]), float(b[key]), rtol=0, atol=1e-12)
    # The composed year (both rules active) still matches the hand solution:
    # Q_2 = 80 - 1.5 - 20 = 58.5 -> p_2 = 41.5 (F1 additive composition).
    np.testing.assert_allclose(float(injected[1]["equilibrium"]["price"]), 41.5, rtol=0, atol=ATOL)


def test_legacy_state_kwargs_are_retired():
    """The legacy msr_state=/ccr_state= kwargs must stay retired (v1 O11 /
    v2 O15): passing them fails loudly rather than silently solving a
    rule-translated path."""
    markets = build_markets_from_config({"scenarios": [_both_rules_scenario()]})
    with pytest.raises(TypeError):
        _simulate_path_details(
            markets,
            {"2030": 25.0, "2031": 45.0},
            msr_state=MSRState(),
        )


# ── 1. End to end: ccr_start_year > first year (split gating, economics) ─────


@pytest.fixture(scope="module")
def ccr_start_year_summary() -> pd.DataFrame:
    scenario = {
        "name": "CCR late start",
        "model_approach": "competitive",
        "ccr_enabled": True,
        "ccr_start_year": 2032.0,
        "ccr_phi_emissions": -50.0,
        "ccr_phi_abatement_cost": 40.0,
        "ccr_reference_emissions": 100.0,
        "ccr_reference_abatement_cost": 400.0,
        "years": [
            _year("2030", 80.0, banking=False),
            _year("2031", 90.0, banking=False),
            _year("2032", 80.0, banking=False),
        ],
    }
    summary, _ = run_simulation_from_config({"scenarios": [scenario]})
    return summary


def _row(summary: pd.DataFrame, year: str) -> pd.Series:
    rows = summary[summary["Year"] == year]
    assert len(rows) == 1
    return rows.iloc[0]


def test_pre_start_years_carry_no_adjustment(ccr_start_year_summary):
    """Before ccr_start_year the cap is untouched: Q = Qbar, ΔQ = 0."""
    for year, auction, price in (("2030", 80.0, 20.0), ("2031", 90.0, 10.0)):
        row = _row(ccr_start_year_summary, year)
        np.testing.assert_allclose(row["CCR Cap Adjustment"], 0.0, rtol=0, atol=ATOL)
        np.testing.assert_allclose(row["CCR Emissions Deviation"], 0.0, rtol=0, atol=ATOL)
        np.testing.assert_allclose(row["CCR Cost Deviation"], 0.0, rtol=0, atol=ATOL)
        np.testing.assert_allclose(row["Auction Offered"], auction, rtol=0, atol=ATOL)
        np.testing.assert_allclose(row["Equilibrium Carbon Price"], price, rtol=0, atol=ATOL)


def test_first_active_year_prices_the_last_inactive_years_signal(
    ccr_start_year_summary,
):
    """2032 prices (e_31, z_31) = (90, 50): ΔQ = +5 - 35 = -30 -> p = 50.

    Discriminators (see module docstring): a start-year-gated record would
    give ΔQ = 0 (p = 20); a stale 2030 signal would give ΔQ = -10 (p = 30).
    """
    row = _row(ccr_start_year_summary, "2032")
    np.testing.assert_allclose(row["CCR Cap Adjustment"], -30.0, rtol=0, atol=ATOL)
    np.testing.assert_allclose(row["CCR Emissions Deviation"], -0.10, rtol=0, atol=ATOL)
    np.testing.assert_allclose(row["CCR Cost Deviation"], -0.875, rtol=0, atol=ATOL)
    np.testing.assert_allclose(row["Auction Offered"], 50.0, rtol=0, atol=ATOL)
    np.testing.assert_allclose(row["Equilibrium Carbon Price"], 50.0, rtol=0, atol=ATOL)
    # Explicit guards against both wrong behaviours.
    assert abs(float(row["Equilibrium Carbon Price"]) - 20.0) > 10.0
    assert abs(float(row["Equilibrium Carbon Price"]) - 30.0) > 10.0


# ── 2. The expectations inner fixed point is rule-free (R29) ─────────────────


def test_perfect_foresight_expectations_exclude_msr_effects():
    """R29 (docs/blocks-composition-rules.md): perfect_foresight expectations
    are formed on the RULE-FREE path — the inner fixed point of
    ``solve_scenario_path`` receives an empty cap-rule list.

    Banking is disabled, so expected prices are decorative for behaviour and
    the test isolates expectation FORMATION. The negative upper threshold
    makes the zero bank trigger a 25 % withhold in every year:

        rule-free:    p = (100-80, 100-70)          = (20.0, 30.0)
        MSR-adjusted: p = (100-60, 100-52.5)        = (40.0, 47.5)

    Expected[2030] must be the rule-free 30.0, NOT the MSR-adjusted 47.5.
    """
    scenario = {
        "name": "R29",
        "model_approach": "competitive",
        "msr_enabled": True,
        "msr_upper_threshold": -5.0,  # zero bank still exceeds it -> withhold
        "msr_lower_threshold": -10.0,
        "msr_withhold_rate": 0.25,
        "msr_release_rate": 0.0,
        "years": [
            _year("2030", 80.0, banking=False, expectation_rule="perfect_foresight"),
            _year("2031", 70.0, banking=False, expectation_rule="perfect_foresight"),
        ],
    }
    details = solve_scenario_path(build_markets_from_config({"scenarios": [scenario]}))
    assert len(details) == 2

    # Realized prices DO carry the MSR (the outer path applies the rules).
    np.testing.assert_allclose(float(details[0]["equilibrium"]["price"]), 40.0, rtol=0, atol=ATOL)
    np.testing.assert_allclose(float(details[1]["equilibrium"]["price"]), 47.5, rtol=0, atol=ATOL)
    np.testing.assert_allclose(float(details[0]["msr_withheld"]), 20.0, rtol=0, atol=ATOL)
    np.testing.assert_allclose(float(details[1]["msr_withheld"]), 17.5, rtol=0, atol=ATOL)

    # Expectations do NOT: expected[2030] = rule-free realized p_2031 = 30.
    expected_2030 = float(details[0]["expected_future_price"])
    np.testing.assert_allclose(expected_2030, 30.0, rtol=0, atol=ATOL)
    assert abs(expected_2030 - 47.5) > 10.0  # inner loop saw no MSR
    # Last year has no next-year realization to foresee.
    np.testing.assert_allclose(float(details[1]["expected_future_price"]), 0.0, rtol=0, atol=1e-12)


# ── 3. λ + MSR regression anchor (no golden coverage; pins today's numbers) ──


@pytest.fixture(scope="module")
def lambda_msr_summary() -> pd.DataFrame:
    """λ = 0.55 blend with a bank-threshold MSR inside the competitive component.

    The static component reproduces the test_msr_ccr_composition arithmetic
    extended one year (bank 25 then 70 > threshold 20 -> withhold 20 Mt in
    2031 and 2032): P_comp = (20, 40, 40). The Hotelling component solves the
    Σcap = 390 Mt budget (binding vs 450 Mt BAU) and is NOT MSR-adjusted (F2);
    delivered = 0.45·P_comp + 0.55·P_hot with no floor.
    """
    years = [
        _year(
            "2030",
            80.0,
            banking=True,
            manual_expected_price=25.0,
            participants=[_buyer(), _banker()],
        ),
        _year(
            "2031",
            80.0,
            banking=True,
            manual_expected_price=45.0,
            participants=[_buyer(), _banker()],
        ),
        _year(
            "2032",
            80.0,
            banking=True,
            manual_expected_price=45.0,
            participants=[_buyer(), _banker()],
        ),
    ]
    scenario = {
        "name": "lambda-msr-anchor",
        "model_approach": "competitive",
        "forward_transmission_lambda": 0.55,
        "discount_rate": 0.055,
        "msr_enabled": True,
        "msr_upper_threshold": 20.0,
        "msr_lower_threshold": 0.0,
        "msr_withhold_rate": 0.25,
        "msr_release_rate": 0.0,
        "years": years,
    }
    summary, _ = run_simulation_from_config({"scenarios": [scenario]})
    return summary


# Solved 2026-07-10 on the pinned environment (uv.lock) — the regression
# anchor the economist requires before later orders touch transmission
# wiring. atol=1e-6 sits far above numerical noise (bisection/brentq run to
# <=1e-6) and far below the discriminating gaps (>= 5 currency units).
_ANCHOR = {
    #  year:   (delivered,            static comp,        hotelling comp)
    "2030": (14.07060898437499, 19.99999999999998, 9.219289062500001),
    "2031": (23.349492478515625, 40.0, 9.726349960937501),
    "2032": (23.643714564833985, 40.0, 10.261299208789064),
}
_ANCHOR_ATOL = 1e-6


def test_lambda_msr_anchor_pins_todays_solved_numbers(lambda_msr_summary):
    for year, (delivered, static, hotelling) in _ANCHOR.items():
        row = _row(lambda_msr_summary, year)
        np.testing.assert_allclose(
            row["Equilibrium Carbon Price"], delivered, rtol=0, atol=_ANCHOR_ATOL
        )
        np.testing.assert_allclose(row["Static Component Price"], static, rtol=0, atol=_ANCHOR_ATOL)
        np.testing.assert_allclose(
            row["Hotelling Component Price"], hotelling, rtol=0, atol=_ANCHOR_ATOL
        )
        np.testing.assert_allclose(row["Forward Transmission Lambda"], 0.55, rtol=0, atol=1e-12)
        np.testing.assert_allclose(row["Reserve Floor Price"], 0.0, rtol=0, atol=1e-12)


def test_lambda_msr_anchor_blend_identity(lambda_msr_summary):
    """delivered = (1-λ)·P_comp + λ·P_hot, exactly (no floor to clip)."""
    for year in _ANCHOR:
        row = _row(lambda_msr_summary, year)
        blend = 0.45 * float(row["Static Component Price"]) + 0.55 * float(
            row["Hotelling Component Price"]
        )
        np.testing.assert_allclose(row["Equilibrium Carbon Price"], blend, rtol=0, atol=1e-9)


def test_lambda_msr_anchor_msr_fired_inside_the_static_component(
    lambda_msr_summary,
):
    """The static component carries the MSR: p = 40 in 2031/2032 (withhold 20
    Mt against banks of 25 then 70), not the rule-free 20."""
    for year in ("2031", "2032"):
        row = _row(lambda_msr_summary, year)
        np.testing.assert_allclose(row["Static Component Price"], 40.0, rtol=0, atol=ATOL)
        assert abs(float(row["Static Component Price"]) - 20.0) > 10.0
