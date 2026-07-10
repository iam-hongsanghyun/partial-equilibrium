"""Tests for the policy-event timeline (announcement vs execution timing).

Anchored on the hand-solvable linear-MAC economy of test_banking: one
participant, BAU E, MAC p = c·a, banking window price
P_a = c·(ΣE − ΣS − B_in)/Σ(1+r)^k.
"""

from __future__ import annotations

import numpy as np
import pytest

from ets.solvers import run_simulation_from_config
from ets.solvers.events import validate_policy_events

E = 100.0
C = 100.0
R = 0.05


def _config(
    approach: str,
    events: list[dict] | None = None,
    cancel_2031: float = 0.0,
) -> dict:
    years = []
    for year, supply in [("2030", 95.0), ("2031", 85.0), ("2032", 75.0)]:
        years.append(
            {
                "year": year,
                "total_cap": supply,
                "cancelled_allowances": cancel_2031 if year == "2031" else 0.0,
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
    scenario = {
        "name": "event-test",
        "model_approach": approach,
        "discount_rate": R,
        "years": years,
    }
    if events is not None:
        scenario["policy_events"] = events
    return {"scenarios": [scenario]}


CANCEL_EVENT = [
    {"announced": "2031", "year_overrides": {"2031": {"cancelled_allowances": 10.0}}}
]


def _prices(summary) -> dict[str, float]:
    return dict(zip(summary["Year"], summary["Equilibrium Carbon Price"]))


def test_banking_announcement_timing_changes_the_path():
    """λ→1: a cancellation announced in 2031 leaves 2030 on the no-event path
    (surprise), while the same cancellation announced up front moves 2030."""
    no_event = _prices(run_simulation_from_config(_config("banking"))[0])
    surprise = _prices(run_simulation_from_config(_config("banking", CANCEL_EVENT))[0])
    upfront = _prices(
        run_simulation_from_config(_config("banking", cancel_2031=10.0))[0]
    )

    # Closed forms: window budget over the full horizon.
    growth = 1.0 + (1.0 + R) + (1.0 + R) ** 2
    p_no_event = C * (3 * E - 255.0) / growth
    p_upfront = C * (3 * E - 245.0) / growth
    np.testing.assert_allclose(no_event["2030"], p_no_event, rtol=1e-5)
    np.testing.assert_allclose(upfront["2030"], p_upfront, rtol=1e-5)

    # Surprise: 2030 is priced WITHOUT the event (information timing) …
    np.testing.assert_allclose(surprise["2030"], p_no_event, rtol=1e-5)
    # … and 2031–32 re-solve with the cancellation and the inherited bank.
    bank_2030 = 95.0 - (E - p_no_event / C)
    p_resolve = C * (2 * E - 150.0 - bank_2030) / (1.0 + (1.0 + R))
    np.testing.assert_allclose(surprise["2031"], p_resolve, rtol=1e-5)
    np.testing.assert_allclose(surprise["2032"], p_resolve * (1 + R), rtol=1e-5)
    # The announcement event is visible: 2031 jumps off the smooth path.
    assert surprise["2031"] > no_event["2031"]
    assert upfront["2030"] > surprise["2030"]


def test_competitive_announcement_timing_is_irrelevant():
    """λ≈0: with year-by-year clearing, announcing early or late is identical —
    only execution moves the price (the paper's weak-transmission result)."""
    surprise = _prices(
        run_simulation_from_config(_config("competitive", CANCEL_EVENT))[0]
    )
    upfront = _prices(
        run_simulation_from_config(_config("competitive", cancel_2031=10.0))[0]
    )
    for year in ("2030", "2031", "2032"):
        np.testing.assert_allclose(surprise[year], upfront[year], rtol=1e-9)
    # And the execution year is where the price moves.
    np.testing.assert_allclose(surprise["2030"], C * (E - 95.0), rtol=1e-6)
    np.testing.assert_allclose(surprise["2031"], C * (E - 75.0), rtol=1e-6)


def test_event_validation():
    with pytest.raises(ValueError):
        run_simulation_from_config(
            _config("banking", [{"announced": "2050", "changes": {}}])
        )
    with pytest.raises(ValueError):
        validate_policy_events(
            {"name": "x", "years": [{"year": "2030"}], "policy_events": [{"changes": {}}]}
        )
    with pytest.raises(ValueError):
        validate_policy_events(
            {
                "name": "x",
                "years": [{"year": "2030"}],
                "policy_events": [
                    {"announced": "2030", "year_overrides": {"2099": {}}}
                ],
            }
        )


def test_late_announced_decree_keeps_its_prefunded_reserve():
    """A decree announced mid-horizon with msr_initial_reserve_mt must keep
    that funding — the splice must not overwrite it with the (rule-less)
    previous segment's zero pool. Bands set so every signal is neutral."""
    cfg = _config(
        "banking",
        [
            {
                "announced": "2031",
                "changes": {
                    "msr_enabled": True,
                    "msr_mode": "hybrid",
                    "msr_initial_reserve_mt": 50.0,
                    "msr_price_band_low": 1.0,
                    "msr_price_band_high": 1e9,
                    "msr_surplus_lower_ratio": 1e-9,
                    "msr_surplus_upper_ratio": 0.99,
                },
            }
        ],
    )
    summary, _ = run_simulation_from_config(cfg)
    pool = dict(zip(summary["Year"], summary["MSR Reserve Pool"]))
    np.testing.assert_allclose(pool["2031"], 50.0, atol=1e-9)
    np.testing.assert_allclose(pool["2032"], 50.0, atol=1e-9)


# ── Splice state-carry pins (feature-modules plan, O6 economist item 5c) ─────
# Requirement (b) — the pre-funded-decree ordering (msr_ran_last_segment is
# evaluated from the PRE-announcement segment before pending events apply, so
# a decree announced with its own msr_initial_reserve_mt keeps that funding,
# commit d2386b4) — is pinned by
# test_late_announced_decree_keeps_its_prefunded_reserve above.

NOOP_EVENT_2032 = [{"announced": "2032", "changes": {}}]


def test_splice_carries_bank_and_decree_reserve_across_segments():
    """Requirement (a): the banking path publishes "Banking Aggregate Bank"
    and "MSR Reserve Pool" — the EXACT summary columns events.py reads at
    the splice (events.py:191-196) — and a decree reserve accumulated in
    segment 1 funds segment 2.

    Decree price band [1e9, 2e9]: every year with history intakes 20 Mt
    (prev price <= low), so segment 1 (2030-31) has pools (0, 20) and the
    full-horizon supply is S_eff = (95, 65, 55). The no-op event announced
    in 2032 forces a splice: segment 2 re-solves 2032 alone with the carried
    bank B_1 and carried pool 20; its first year has no decree history, so
    the action is neutral and 2032 clears the single-year window budget
    B_1 + 75:

        P_2030 = c(3E - 215)/(1 + (1+r) + (1+r)^2),  P_2031 = (1+r)P_2030,
        P_2032 = c(E - 75 - B_1).

    Discriminators: a broken bank carry gives P_2032 = c(E - 75) = 2500;
    a broken pool carry gives pool_2032 = 0.
    """
    cfg = _config("banking", NOOP_EVENT_2032)
    cfg["scenarios"][0].update(
        {
            "msr_enabled": True,
            "msr_mode": "price_band",
            "msr_price_band_low": 1e9,   # prev price always <= low -> intake
            "msr_price_band_high": 2e9,
            "msr_max_intake_mt": 20.0,
            "msr_max_release_mt": 20.0,
        }
    )
    summary, _ = run_simulation_from_config(cfg)
    assert "Banking Aggregate Bank" in summary.columns
    assert "MSR Reserve Pool" in summary.columns

    prices = _prices(summary)
    pool = dict(zip(summary["Year"], summary["MSR Reserve Pool"]))
    withheld = dict(zip(summary["Year"], summary["MSR Withheld"]))

    growth = 1.0 + (1.0 + R) + (1.0 + R) ** 2
    p0 = C * (3 * E - (95.0 + 65.0 + 55.0)) / growth
    b0 = 95.0 - (E - p0 / C)
    b1 = b0 + 65.0 - (E - p0 * (1.0 + R) / C)
    np.testing.assert_allclose(prices["2030"], p0, rtol=1e-5)
    np.testing.assert_allclose(prices["2031"], p0 * (1.0 + R), rtol=1e-5)
    np.testing.assert_allclose(prices["2032"], C * (E - 75.0 - b1), rtol=1e-5)

    np.testing.assert_allclose(
        [pool["2030"], pool["2031"], pool["2032"]], [0.0, 20.0, 20.0], atol=1e-9
    )
    np.testing.assert_allclose(withheld["2031"], 20.0, atol=1e-9)
    np.testing.assert_allclose(withheld["2032"], 0.0, atol=1e-12)  # neutral first year


def test_bank_threshold_pool_resets_per_segment_while_decree_carries():
    """Requirement (c), docs/banking-equilibrium.md:117-120: a bank_threshold
    pool is NOT carried state — the rule reconstructs an empty pool each
    segment (R7: only a decree owns msr_initial_reserve_mt, so the value the
    splice stamps is ignored) — whereas the decree in the test above carries
    its reserve.

    Supplies 60/60/60 with a 60 Mt initial bank keep the beginning-of-year
    bank far above the 10 Mt threshold in every year and iteration, so every
    year withholds 0.12·60 = 7.2 Mt: segment-1 pools cumulate (7.2, 14.4);
    segment 2 restarts at 7.2 instead of continuing to 21.6.
    """
    cfg = _config("banking", NOOP_EVENT_2032)
    for year in cfg["scenarios"][0]["years"]:
        year["total_cap"] = 60.0
    cfg["scenarios"][0].update(
        {
            "banking_initial_bank": 60.0,
            "msr_enabled": True,
            "msr_mode": "bank_threshold",
            "msr_upper_threshold": 10.0,
            "msr_lower_threshold": 0.0,
            "msr_withhold_rate": 0.12,
            "msr_release_rate": 50.0,
        }
    )
    summary, _ = run_simulation_from_config(cfg)
    pool = dict(zip(summary["Year"], summary["MSR Reserve Pool"]))
    w = 0.12 * 60.0  # same float expression the rule evaluates
    np.testing.assert_allclose(pool["2030"], w, rtol=0, atol=0)
    np.testing.assert_allclose(pool["2031"], w + w, rtol=0, atol=0)
    # Segment 2: a FRESH pool withholds once — not the carried 14.4 + 7.2.
    np.testing.assert_allclose(pool["2032"], w, rtol=0, atol=0)
    assert abs(pool["2032"] - (w + w + w)) > 10.0


def test_msr_start_year_gates_the_rule():
    """A decree MSR with msr_start_year beyond the horizon never fires."""
    cfg = _config("banking")
    cfg["scenarios"][0].update(
        {
            "msr_enabled": True,
            "msr_mode": "hybrid",
            "msr_initial_reserve_mt": 50.0,
            "msr_start_year": 2099.0,
        }
    )
    summary, _ = run_simulation_from_config(cfg)
    np.testing.assert_allclose(summary["MSR Withheld"].to_numpy(), 0.0, atol=1e-12)
    np.testing.assert_allclose(summary["MSR Released"].to_numpy(), 0.0, atol=1e-12)
