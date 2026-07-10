"""Tests for the Rubin/Schennach banking equilibrium solver.

Anchored on a hand-solvable two-year linear-MAC economy: one participant with
BAU emissions E and linear MAC p = c·a, so abatement at price p is a = p/c.
With a binding banking window [0, 1] and carry rate r, the no-arbitrage path
P1 = P0·(1+r) and the window budget give the closed form

    P0 = c · (2E − S0 − S1 − B_in) / (2 + r)

valid while the interior bank stays non-negative.
"""

from __future__ import annotations

import numpy as np

from ets.config_io import build_markets_from_config
from ets.solvers import run_simulation_from_config, solve_banking_path

E = 100.0     # BAU emissions per year [Mt]
C = 100.0     # linear MAC slope [KRW per t per Mt]
R = 0.05      # carry rate [1/yr]


def _config(
    supplies: list[float],
    initial_bank: float = 0.0,
    approach: str = "banking",
    hoarding: list[float] | None = None,
) -> dict:
    years = []
    for index, supply in enumerate(supplies):
        years.append(
            {
                "year": str(2030 + index),
                "hoarding_inflow": float(hoarding[index]) if hoarding else 0.0,
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
    return {
        "scenarios": [
            {
                "name": "banking-test",
                "model_approach": approach,
                "discount_rate": R,
                "banking_initial_bank": initial_bank,
                "years": years,
            }
        ]
    }


def _prices(path: list[dict]) -> list[float]:
    return [float(item["equilibrium"]["price"]) for item in path]


def test_two_year_window_matches_closed_form():
    """S = [95, 75]: banking binds, P0 = c(2E − ΣS)/(2+r), P1 = P0(1+r)."""
    path = solve_banking_path(
        build_markets_from_config(_config([95.0, 75.0])), discount_rate=R
    )
    p0_expected = C * (2 * E - 95.0 - 75.0) / (2.0 + R)
    prices = _prices(path)
    np.testing.assert_allclose(prices[0], p0_expected, rtol=1e-5)
    np.testing.assert_allclose(prices[1], p0_expected * (1 + R), rtol=1e-5)
    assert path[0]["banking_regime"] == "hotelling"
    # Interior bank: S0 − (E − P0/c) ≥ 0, terminal bank ≈ 0.
    np.testing.assert_allclose(
        path[0]["banking_aggregate_bank"], 95.0 - (E - p0_expected / C), rtol=1e-4
    )
    np.testing.assert_allclose(path[1]["banking_aggregate_bank"], 0.0, atol=1e-3)


def test_reversed_supply_gives_static_prices():
    """S = [75, 95]: static prices fall, banking unprofitable → static path."""
    path = solve_banking_path(
        build_markets_from_config(_config([75.0, 95.0])), discount_rate=R
    )
    prices = _prices(path)
    np.testing.assert_allclose(prices[0], C * (E - 75.0), rtol=1e-6)  # 2500
    np.testing.assert_allclose(prices[1], C * (E - 95.0), rtol=1e-6)  # 500


def test_waterbed_reprofiling_within_window_is_price_neutral():
    """Shifting supply across window years (same total) leaves prices unchanged
    while the bank stays non-negative — the cap-neutrality theorem."""
    base = _prices(
        solve_banking_path(
            build_markets_from_config(_config([95.0, 75.0])), discount_rate=R
        )
    )
    shifted = _prices(
        solve_banking_path(
            build_markets_from_config(_config([90.0, 80.0])), discount_rate=R
        )
    )
    np.testing.assert_allclose(shifted, base, rtol=1e-5)


def test_initial_bank_lowers_the_path():
    """A carried-in bank adds to the window budget: P0 = c(2E − ΣS − B)/(2+r)."""
    path = solve_banking_path(
        build_markets_from_config(_config([95.0, 75.0], initial_bank=10.0)),
        discount_rate=R,
    )
    p0_expected = C * (2 * E - 95.0 - 75.0 - 10.0) / (2.0 + R)
    np.testing.assert_allclose(_prices(path)[0], p0_expected, rtol=1e-5)


def test_deferred_window_when_early_bank_infeasible():
    """S = [70, 95, 80]: the window cannot start in year 0 (interior bank
    would go negative), so the equilibrium is static year 0 + window [1, 2]:
    P1 = c(2E − S1 − S2)/(2 + r)."""
    path = solve_banking_path(
        build_markets_from_config(_config([70.0, 95.0, 80.0])), discount_rate=R
    )
    prices = _prices(path)
    np.testing.assert_allclose(prices[0], C * (E - 70.0), rtol=1e-6)  # 3000
    p1_expected = C * (2 * E - 95.0 - 80.0) / (2.0 + R)
    np.testing.assert_allclose(prices[1], p1_expected, rtol=1e-5)
    np.testing.assert_allclose(prices[2], p1_expected * (1 + R), rtol=1e-5)
    assert path[0]["banking_regime"] == "static"
    assert path[1]["banking_regime"] == "hotelling"


def test_hoarding_raises_static_price_and_feeds_the_window():
    """Hoarding h0 = 5 in the pre-window year clears the static year at
    S0 − h0 (raising its price) and adds 5 Mt to the window budget:
    P1 = c(2E − S1 − S2 − h0)/(2 + r)."""
    path = solve_banking_path(
        build_markets_from_config(
            _config([70.0, 95.0, 80.0], hoarding=[5.0, 0.0, 0.0])
        ),
        discount_rate=R,
    )
    prices = _prices(path)
    np.testing.assert_allclose(prices[0], C * (E - 65.0), rtol=1e-6)  # 3500
    p1_expected = C * (2 * E - 95.0 - 80.0 - 5.0) / (2.0 + R)
    np.testing.assert_allclose(prices[1], p1_expected, rtol=1e-5)
    # The hoarded volume sits in the bank at the end of the static year.
    np.testing.assert_allclose(path[0]["banking_aggregate_bank"], 5.0, atol=1e-4)


def test_hoarding_year_never_absorbed_into_window():
    """Reviewer regression: with S = [80, 40, 48] and h0 = 30 the old search
    absorbed year 0 into window (0, 2) and silently ignored the hoarding.
    Hoarding years are static by definition, so the window must be [1, 2]
    with the hoarded 30 Mt in its budget:
    P1 = c(2E − S1 − S2 − h0)/(2 + r)."""
    path = solve_banking_path(
        build_markets_from_config(
            _config([80.0, 40.0, 48.0], hoarding=[30.0, 0.0, 0.0])
        ),
        discount_rate=R,
    )
    prices = _prices(path)
    # Static hoarding year clears at S0 − h0 = 50 → price c·(E − 50) = 5000.
    np.testing.assert_allclose(prices[0], C * (E - 50.0), rtol=1e-6)
    p1_expected = C * (2 * E - 40.0 - 48.0 - 30.0) / (2.0 + R)  # 4000
    np.testing.assert_allclose(prices[1], p1_expected, rtol=1e-5)
    np.testing.assert_allclose(prices[2], p1_expected * (1 + R), rtol=1e-5)
    assert path[0]["banking_regime"] == "static"
    assert path[1]["banking_regime"] == "hotelling"
    # Sensitivity: the solution MUST move with h0 (the old defect was h0-inert).
    path_no_hoard = solve_banking_path(
        build_markets_from_config(_config([80.0, 40.0, 48.0])), discount_rate=R
    )
    assert abs(_prices(path_no_hoard)[1] - prices[1]) > 1.0


def test_piecewise_mac_terminal_residual_is_loud(caplog):
    """Reviewer regression: step-function demand can make the window budget
    unattainable exactly; the terminal residual must be warned, not silent."""
    import logging

    config = _config([95.0, 75.0])
    for year in config["scenarios"][0]["years"]:
        year["participants"][0] = {
            "name": "Industry",
            "initial_emissions": E,
            "free_allocation_ratio": 0.0,
            "penalty_price": 0.0,
            "abatement_type": "piecewise",
            # One coarse 20 Mt block: the window budget (30 Mt shortage)
            # falls strictly between the 0 Mt and 40 Mt plateaus.
            "mac_blocks": [{"amount": 20.0, "marginal_cost": 1000.0}],
        }
    # Logger channel follows the moved code (v1 O9 / v2 O13): the terminal
    # residual warning is emitted by features/banking/window.py.
    with caplog.at_level(logging.WARNING, logger="ets.features.banking.window"):
        path = solve_banking_path(
            build_markets_from_config(config), discount_rate=R
        )
    assert any("terminal bank" in rec.message for rec in caplog.records) or (
        abs(path[-1]["banking_aggregate_bank"]) < 1e-3
    )


def test_end_to_end_config_routing_and_diagnostics():
    summary, _ = run_simulation_from_config(_config([95.0, 75.0]))
    assert "Banking Aggregate Bank" in summary.columns
    assert list(summary["Banking Regime"]) == ["hotelling", "hotelling"]
    p0_expected = C * (2 * E - 95.0 - 75.0) / (2.0 + R)
    np.testing.assert_allclose(
        summary["Equilibrium Carbon Price"].iloc[0], p0_expected, rtol=1e-5
    )
