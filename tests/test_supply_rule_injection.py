r"""Regression tests for supply-rule injection in the banking fixed point (O6).

Reference
---------
``docs/feature-modules-plan.md`` — work order O6 (v1 §4, PLAN v2 §2 protocol
family) and the economist's binding lifecycle doctrine
(``ets.core.protocols``): supply rules are stateful across YEARS within one
schedule evaluation, PURE across solver invocations and across fixed-point
iterations — hosts construct fresh instances per evaluation via factories.
Moving rule evaluation outside the fixed point computes a DIFFERENT
equilibrium (F4, ``docs/blocks-composition-rules.md``); only behavioural
gates like these (and the golden gate) can catch that, never import
isolation.

The injected rules (``DecreeSupplyRule``, ``ThresholdMSRSupplyRule``) are
lifted verbatim from ``solvers/banking.py:_supply_schedule``, so every
number here is also a regression anchor for the pre-injection behaviour.

Test design (hand-solvable linear-MAC economy, as ``tests/test_banking.py``):
one participant with BAU emissions E = 100 Mt and linear MAC p = c·a
(c = 100), so residual emissions are e(p) = E − p/c and a binding banking
window [0, n−1] with carry rate r = 0.05 gives the closed form

    P_0 = c · (nE − ΣS_eff − B_in) / Σ_k (1+r)^k .

Decree anchor (``surplus_rule``): supplies (95, 85, 75), reserve 30 Mt,
surplus band [1e-9, 1e-6] — any positive surplus ratio triggers the 20 Mt/yr
intake from 2031 on (2030 is signal-neutral: no previous year). The fixed
point needs TWO schedule evaluations (base schedule → intake schedule →
unchanged), S_eff = (95, 65, 55) and

    P_2030 = 100·(300 − 215)/3.1525 = 2696.27…, pools (30, 50, 70).

Threshold anchor (``bank_threshold``): supplies (60, 60, 60), initial bank
60 Mt, upper threshold 10 Mt — the beginning-of-year bank stays far above
the threshold in every year and iteration, so the rule withholds
0.12·60 = 7.2 Mt every year; pools cumulate (7.2, 14.4, 21.6) and no
initial reserve ever funds the pool (R7).

Legacy anchors below were captured on the PINNED environment at the pre-O6
tree (2026-07-10) and are asserted at rtol=0, atol=0 — the refactor must be
bit-exact.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ets.config_io import build_markets_from_config
from ets.core.defaults import MSR_DEFAULTS
from ets.core.protocols import Observables, SupplyRule
from ets.solvers import solve_banking_path
from ets.solvers.banking import _default_supply_rule_factories
from ets.solvers.msr import DecreeSupplyRule, ThresholdMSRSupplyRule

E = 100.0  # BAU emissions per year [Mt]
C = 100.0  # linear MAC slope [KRW per t per Mt]
R = 0.05  # carry rate [1/yr]


def _years(supplies: list[float]) -> list[dict]:
    years = []
    for index, supply in enumerate(supplies):
        years.append(
            {
                "year": str(2030 + index),
                "total_cap": supply,
                "auction_mode": "derive_from_cap",
                "banking_allowed": False,
                "borrowing_allowed": False,
                "expectation_rule": "next_year_baseline",
                "price_lower_bound": 0.0,
                "price_upper_bound": 100000.0,
                "participants": [
                    {
                        "name": "Industry",
                        "initial_emissions": E,
                        "free_allocation_ratio": 0.0,
                        "penalty_price": 0.0,
                        "abatement_type": "linear",
                        "max_abatement": E,
                        "cost_slope": C,
                    }
                ],
            }
        )
    return years


def _decree_config() -> dict:
    return {
        "scenarios": [
            {
                "name": "decree-anchor",
                "model_approach": "banking",
                "discount_rate": R,
                "banking_initial_bank": 0.0,
                "msr_enabled": True,
                "msr_mode": "surplus_rule",
                "msr_initial_reserve_mt": 30.0,
                "msr_surplus_upper_ratio": 1e-6,
                "msr_surplus_lower_ratio": 1e-9,
                "msr_max_intake_mt": 20.0,
                "msr_max_release_mt": 20.0,
                "years": _years([95.0, 85.0, 75.0]),
            }
        ]
    }


def _threshold_config() -> dict:
    return {
        "scenarios": [
            {
                "name": "threshold-anchor",
                "model_approach": "banking",
                "discount_rate": R,
                "banking_initial_bank": 60.0,
                "msr_enabled": True,
                "msr_mode": "bank_threshold",
                "msr_upper_threshold": 10.0,
                "msr_lower_threshold": 0.0,
                "msr_withhold_rate": 0.12,
                "msr_release_rate": 50.0,
                "years": _years([60.0, 60.0, 60.0]),
            }
        ]
    }


# Captured 2026-07-10 on the pinned environment (uv.lock) at the PRE-refactor
# tree (before the O6 injection), via solve_banking_path on the two configs
# above. Tuples are (price, msr_withheld, msr_released, msr_pool,
# banking_aggregate_bank) per year. Bar: rtol=0, atol=0 (bit-exact).
_PRE_REFACTOR_ANCHORS: dict[str, dict[str, tuple[float, ...]]] = {
    "decree": {
        "2030": (2696.2727993656113, 0.0, 0.0, 30.0, 21.962727993656102),
        "2031": (2831.086439333892, 20.0, 0.0, 50.0, 15.273592386995048),
        "2032": (2972.6407613005863, 20.0, 0.0, 70.0, 8.952838470577262e-13),
    },
    "threshold": {
        "2030": (2588.4218873909913, 7.199999999999999, 0.0, 7.199999999999999, 38.68421887390987),
        "2031": (2717.842981760541, 7.199999999999999, 0.0, 14.399999999999999, 18.6626486915153),
        "2032": (
            2853.735130848568,
            7.199999999999999,
            0.0,
            21.599999999999998,
            9.947598300641403e-13,
        ),
    },
}


def _assert_matches_anchor(path: list[dict], anchor: dict[str, tuple[float, ...]]) -> None:
    assert len(path) == len(anchor)
    for item in path:
        year = str(item["market"].year)
        price, withheld, released, pool, bank = anchor[year]
        np.testing.assert_allclose(float(item["equilibrium"]["price"]), price, rtol=0, atol=0)
        np.testing.assert_allclose(float(item["msr_withheld"]), withheld, rtol=0, atol=0)
        np.testing.assert_allclose(float(item["msr_released"]), released, rtol=0, atol=0)
        np.testing.assert_allclose(float(item["msr_pool"]), pool, rtol=0, atol=0)
        np.testing.assert_allclose(float(item["banking_aggregate_bank"]), bank, rtol=0, atol=0)
        assert item["banking_regime"] == "hotelling"
        assert (item["banking_window_start"], item["banking_window_end"]) == (0, 2)


# ── Protocol conformance and factory wiring ──────────────────────────────────


def test_supply_rules_satisfy_the_protocol():
    """Both implementations structurally satisfy core.protocols.SupplyRule."""
    assert isinstance(DecreeSupplyRule(mode="hybrid"), SupplyRule)
    assert isinstance(ThresholdMSRSupplyRule(), SupplyRule)


def test_threshold_rule_never_takes_an_initial_reserve():
    """R7: msr_initial_reserve_mt funds ONLY the decree rule — the threshold
    rule's constructor must not even accept a reserve, and its pool starts
    empty on every construction."""
    params = set(inspect.signature(ThresholdMSRSupplyRule.__init__).parameters)
    assert params == {"self", "start_year"}
    assert ThresholdMSRSupplyRule().msr_state.reserve_pool == 0.0


def test_default_factories_mode_dispatch_and_freshness():
    """The transitional wiring: decree XOR threshold, never both; factories
    construct INDEPENDENT instances (no shared reserve state)."""
    m_decree = SimpleNamespace(
        msr_enabled=True,
        msr_mode="hybrid",
        msr_start_year=0.0,
        msr_initial_reserve_mt=85.277328,
    )
    factories = _default_supply_rule_factories(m_decree)
    assert len(factories) == 1
    rule_a, rule_b = factories[0](), factories[0]()
    assert isinstance(rule_a, DecreeSupplyRule)
    assert rule_a is not rule_b
    rule_a.reserve -= 30.0  # mutate one instance...
    np.testing.assert_allclose(rule_b.reserve, 85.277328, rtol=0, atol=0)  # ...other unaffected

    m_threshold = SimpleNamespace(
        msr_enabled=True,
        msr_mode="bank_threshold",
        msr_start_year=0.0,
        msr_initial_reserve_mt=50.0,  # present but must NOT fund the pool (R7)
    )
    [factory] = _default_supply_rule_factories(m_threshold)
    rule = factory()
    assert isinstance(rule, ThresholdMSRSupplyRule)
    assert rule.msr_state.reserve_pool == 0.0

    assert _default_supply_rule_factories(SimpleNamespace(msr_enabled=False)) == []


# ── Closed form: the decree action in its new home ───────────────────────────


def _decree_market(year: str = "2031") -> SimpleNamespace:
    return SimpleNamespace(
        year=year,
        participants=[SimpleNamespace(free_allocation=10.0)],
        auction_offered=80.0,
        msr_price_band_high=25000.0,
        msr_price_band_low=15000.0,
        msr_surplus_upper_ratio=0.18,
        msr_surplus_lower_ratio=0.05,
        msr_max_intake_mt=20.0,
        msr_max_release_mt=20.0,
    )


def test_decree_release_is_capped_by_the_reserve():
    """price_band, prev price >= high: release min(max_release, reserve)."""
    rule = DecreeSupplyRule(mode="price_band", initial_reserve_mt=12.0)
    obs = Observables(begin_bank=0.0, prev_price=30000.0, prev_surplus_ratio=0.1)
    supply, diags = rule.apply(_decree_market(), obs)
    np.testing.assert_allclose(supply, 10.0 + 80.0 + 12.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_released"], 12.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_pool"], 0.0, rtol=0, atol=1e-12)


def test_decree_intake_reduces_supply_and_grows_the_reserve():
    """price_band, prev price <= low: intake max_intake into the reserve."""
    rule = DecreeSupplyRule(mode="price_band", initial_reserve_mt=5.0)
    obs = Observables(begin_bank=0.0, prev_price=10000.0, prev_surplus_ratio=0.1)
    supply, diags = rule.apply(_decree_market(), obs)
    np.testing.assert_allclose(supply, 10.0 + 80.0 - 20.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_withheld"], 20.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_pool"], 25.0, rtol=0, atol=1e-12)


def test_decree_first_year_is_neutral_and_shows_the_standing_reserve():
    """No previous year -> neutral action; the pool diagnostic reports the
    standing (pre-funded) reserve, as in the pre-refactor driver block."""
    rule = DecreeSupplyRule(mode="hybrid", initial_reserve_mt=50.0)
    obs = Observables(begin_bank=0.0, prev_price=None, prev_surplus_ratio=None)
    supply, diags = rule.apply(_decree_market("2030"), obs)
    np.testing.assert_allclose(supply, 90.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_withheld"], 0.0, rtol=0, atol=0)
    np.testing.assert_allclose(diags["msr_pool"], 50.0, rtol=0, atol=0)


def test_decree_hybrid_tie_is_neutral():
    """Hybrid: price says release (+1), surplus says intake (-1) -> neutral."""
    rule = DecreeSupplyRule(mode="hybrid", initial_reserve_mt=30.0)
    obs = Observables(begin_bank=0.0, prev_price=30000.0, prev_surplus_ratio=0.5)
    supply, diags = rule.apply(_decree_market(), obs)
    np.testing.assert_allclose(supply, 90.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(diags["msr_withheld"], 0.0, rtol=0, atol=0)
    np.testing.assert_allclose(diags["msr_released"], 0.0, rtol=0, atol=0)
    np.testing.assert_allclose(diags["msr_pool"], 30.0, rtol=0, atol=0)


def test_decree_start_year_gate_returns_unadjusted_supply_and_zero_diags():
    """Gated-off year: unadjusted supply, ALL-zero diagnostics (the standing
    reserve is not reported — pre-refactor branch-skip behaviour)."""
    rule = DecreeSupplyRule(mode="price_band", initial_reserve_mt=30.0, start_year=2032.0)
    obs = Observables(begin_bank=0.0, prev_price=10000.0, prev_surplus_ratio=0.1)
    supply, diags = rule.apply(_decree_market("2031"), obs)
    np.testing.assert_allclose(supply, 90.0, rtol=0, atol=1e-12)
    assert diags == {"msr_withheld": 0.0, "msr_released": 0.0, "msr_pool": 0.0}
    np.testing.assert_allclose(rule.reserve, 30.0, rtol=0, atol=0)  # untouched


def test_threshold_fallbacks_come_from_msr_defaults():
    """A market carrying NO msr_* threshold fields uses core.defaults
    byte-identically (the O1 single-source fix): bank above the default
    upper threshold withholds rate*auction; a later low-bank year releases
    from the pool the rule itself accumulated."""
    market = SimpleNamespace(
        year="2030",
        participants=[SimpleNamespace(free_allocation=10.0)],
        auction_offered=80.0,
    )
    rule = ThresholdMSRSupplyRule()

    # Bank above the default upper threshold (200) -> withhold.
    high_bank = MSR_DEFAULTS["msr_upper_threshold"] + 50.0
    supply, diags = rule.apply(market, Observables(begin_bank=high_bank))
    expected_withheld = MSR_DEFAULTS["msr_withhold_rate"] * 80.0
    np.testing.assert_allclose(diags["msr_withheld"], expected_withheld, rtol=0, atol=0)
    np.testing.assert_allclose(supply, 10.0 + (80.0 - expected_withheld), rtol=0, atol=1e-12)

    # Bank below the default lower threshold (50) -> release capped by pool.
    low_bank = MSR_DEFAULTS["msr_lower_threshold"] - 10.0
    supply, diags = rule.apply(market, Observables(begin_bank=low_bank))
    expected_released = min(MSR_DEFAULTS["msr_release_rate"], expected_withheld)
    np.testing.assert_allclose(diags["msr_released"], expected_released, rtol=0, atol=0)
    np.testing.assert_allclose(diags["msr_pool"], 0.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(supply, 10.0 + 80.0 + expected_released, rtol=0, atol=1e-12)


# ── (a) Purity across solver invocations ─────────────────────────────────────


def test_repeated_solves_are_bit_identical():
    """Two solves on the SAME inputs must match bit-for-bit: a shared rule
    instance (rather than a per-evaluation factory construction) would leak
    decree reserve state from the first run into the second."""
    markets = build_markets_from_config(_decree_config())
    first = solve_banking_path(markets, discount_rate=R)
    second = solve_banking_path(markets, discount_rate=R)
    assert len(first) == len(second) == 3
    for a, b in zip(first, second, strict=True):
        for key in a["equilibrium"]:
            np.testing.assert_allclose(
                float(a["equilibrium"][key]), float(b["equilibrium"][key]), rtol=0, atol=0
            )
        for key in (
            "msr_withheld",
            "msr_released",
            "msr_pool",
            "banking_aggregate_bank",
            "banking_floor_cancelled",
            "expected_future_price",
        ):
            np.testing.assert_allclose(float(a[key]), float(b[key]), rtol=0, atol=0)
        pd.testing.assert_frame_equal(a["participant_df"], b["participant_df"], check_exact=True)


# ── (b) Purity across fixed-point iterations ─────────────────────────────────


def test_fixed_point_iteration_count_does_not_change_the_reserve_trajectory(caplog):
    """Forcing extra schedule evaluations (negative tolerance -> the loop
    runs to max_iters past convergence) must not move the solution: each
    evaluation constructs FRESH rules, so a converged schedule is a true
    fixed point. A rule instance shared across iterations would keep
    mutating its reserve on every extra evaluation and the pool trajectory
    would diverge from the plain solve."""
    with caplog.at_level(logging.DEBUG, logger="ets.solvers.banking"):
        base = solve_banking_path(build_markets_from_config(_decree_config()), discount_rate=R)
    iteration_logs = [
        rec.message for rec in caplog.records if "supply-rule iteration" in rec.message
    ]
    # The scenario genuinely composes to a fixed point: > 1 schedule iteration.
    assert any("iteration 1" in message for message in iteration_logs)

    forced_config = _decree_config()
    forced_config["scenarios"][0]["banking_supply_rule_tolerance"] = -1.0
    forced_config["scenarios"][0]["banking_supply_rule_max_iters"] = 12
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="ets.solvers.banking"):
        forced = solve_banking_path(build_markets_from_config(forced_config), discount_rate=R)
    # The forced run really did exhaust its iteration budget (loud fallback).
    assert any("did not converge" in rec.message for rec in caplog.records)

    for a, b in zip(base, forced, strict=True):
        np.testing.assert_allclose(
            float(a["equilibrium"]["price"]), float(b["equilibrium"]["price"]), rtol=0, atol=0
        )
        for key in ("msr_withheld", "msr_released", "msr_pool", "banking_aggregate_bank"):
            np.testing.assert_allclose(float(a[key]), float(b[key]), rtol=0, atol=0)


# ── (c) Legacy equivalence against the pre-refactor anchors ──────────────────


@pytest.mark.parametrize("name", ["decree", "threshold"])
def test_default_factories_reproduce_the_pre_refactor_numbers(name):
    """The default (None -> _default_supply_rule_factories) wiring must
    reproduce the pre-injection solver bit-for-bit (rtol=0, atol=0)."""
    config = _decree_config() if name == "decree" else _threshold_config()
    path = solve_banking_path(build_markets_from_config(config), discount_rate=R)
    _assert_matches_anchor(path, _PRE_REFACTOR_ANCHORS[name])


def test_explicitly_injected_factories_match_the_default_wiring():
    """Injecting the decree factory by hand (what engine/wiring.py will do)
    is the same equilibrium as the flag-derived default wiring."""
    path = solve_banking_path(
        build_markets_from_config(_decree_config()),
        discount_rate=R,
        supply_rule_factories=[
            lambda: DecreeSupplyRule(mode="surplus_rule", initial_reserve_mt=30.0, start_year=0.0)
        ],
    )
    _assert_matches_anchor(path, _PRE_REFACTOR_ANCHORS["decree"])


def test_empty_factory_override_disables_the_msr():
    """An explicit empty sequence bypasses the flag-derived wiring: the path
    is the rule-free window equilibrium P_0 = c(3E - ΣS)/Σ(1+r)^k with a
    zero pool everywhere."""
    path = solve_banking_path(
        build_markets_from_config(_decree_config()),
        discount_rate=R,
        supply_rule_factories=(),
    )
    growth = 1.0 + (1.0 + R) + (1.0 + R) ** 2
    p0_expected = C * (3 * E - (95.0 + 85.0 + 75.0)) / growth
    for t, item in enumerate(path):
        np.testing.assert_allclose(
            float(item["equilibrium"]["price"]),
            p0_expected * (1.0 + R) ** t,
            rtol=1e-5,
        )
        np.testing.assert_allclose(float(item["msr_pool"]), 0.0, rtol=0, atol=0)
        np.testing.assert_allclose(float(item["msr_withheld"]), 0.0, rtol=0, atol=0)
