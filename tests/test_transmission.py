"""Tests for forward-transmission (λ) blending — K-MSR working paper (2026).

Covers the blend arithmetic, the endpoint identities (λ=0 → competitive,
λ=1 → Hotelling), the midpoint analytical property, the blend-then-clip
operation order, and the λ-independent floor (the paper's transmission-
immunity result) end to end through the config layer.
"""

from __future__ import annotations

import numpy as np
import pytest

from ets.config_io import build_markets_from_config, normalize_config
from ets.solvers import (
    run_simulation_from_config,
    solve_hotelling_path,
    solve_scenario_path,
    solve_transmission_path,
)
from ets.solvers.transmission import blend_prices

DISCOUNT_RATE = 0.055


def _base_config(
    lam: float | None = None,
    reserve_prices: dict[str, float] | None = None,
) -> dict:
    """Three-year, one-participant scenario with a stepped piecewise MAC."""
    reserve_prices = reserve_prices or {}
    years = []
    for year, cap in [("2030", 90.0), ("2031", 80.0), ("2032", 70.0)]:
        years.append(
            {
                "year": year,
                "total_cap": cap,
                "auction_mode": "derive_from_cap",
                "auction_reserve_price": float(reserve_prices.get(year, 0.0)),
                "unsold_treatment": "cancel",
                "banking_allowed": False,
                "borrowing_allowed": False,
                "expectation_rule": "next_year_baseline",
                "price_lower_bound": 0.0,
                "price_upper_bound": 10000.0,
                "participants": [
                    {
                        "name": "Industry",
                        "initial_emissions": 100.0,
                        "free_allocation_ratio": 0.0,
                        "penalty_price": 0.0,
                        "abatement_type": "piecewise",
                        "mac_blocks": [
                            {"amount": 10.0, "marginal_cost": 10.0},
                            {"amount": 10.0, "marginal_cost": 20.0},
                            {"amount": 10.0, "marginal_cost": 40.0},
                            {"amount": 10.0, "marginal_cost": 80.0},
                        ],
                    }
                ],
            }
        )
    scenario = {
        "name": "lambda-test",
        "model_approach": "competitive",
        "discount_rate": DISCOUNT_RATE,
        "years": years,
    }
    if lam is not None:
        scenario["forward_transmission_lambda"] = lam
    return {"scenarios": [scenario]}


def _path_prices(path: list[dict]) -> dict[str, float]:
    return {
        str(item["market"].year): float(item["equilibrium"]["price"])
        for item in path
    }


def _component_prices() -> tuple[dict[str, float], dict[str, float]]:
    """No-floor competitive and Hotelling component prices for the base config."""
    comp = _path_prices(solve_scenario_path(build_markets_from_config(_base_config())))
    hot = _path_prices(
        solve_hotelling_path(
            build_markets_from_config(_base_config()), discount_rate=DISCOUNT_RATE
        )
    )
    return comp, hot


# ── Unit: the blend arithmetic ───────────────────────────────────────────────


def test_blend_prices_closed_form():
    np.testing.assert_allclose(blend_prices(10.0, 30.0, 0.0), 10.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(blend_prices(10.0, 30.0, 1.0), 30.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(blend_prices(10.0, 30.0, 0.25), 15.0, rtol=0, atol=1e-12)


def test_blend_prices_rejects_out_of_range_lambda():
    with pytest.raises(ValueError):
        blend_prices(10.0, 30.0, 1.2)
    with pytest.raises(ValueError):
        blend_prices(10.0, 30.0, -0.1)


# ── Endpoints: λ=0 and λ=1 recover the component solvers exactly ────────────


def test_lambda_zero_equals_competitive_path():
    comp, _ = _component_prices()
    delivered = _path_prices(
        solve_transmission_path(
            build_markets_from_config(_base_config()),
            lam=0.0,
            discount_rate=DISCOUNT_RATE,
        )
    )
    for year, price in comp.items():
        np.testing.assert_allclose(delivered[year], price, rtol=1e-9)


def test_lambda_one_equals_hotelling_path():
    _, hot = _component_prices()
    delivered = _path_prices(
        solve_transmission_path(
            build_markets_from_config(_base_config()),
            lam=1.0,
            discount_rate=DISCOUNT_RATE,
        )
    )
    for year, price in hot.items():
        np.testing.assert_allclose(delivered[year], price, rtol=1e-9)


def test_lambda_half_is_arithmetic_mean_of_components():
    comp, hot = _component_prices()
    delivered = _path_prices(
        solve_transmission_path(
            build_markets_from_config(_base_config()),
            lam=0.5,
            discount_rate=DISCOUNT_RATE,
        )
    )
    for year in comp:
        np.testing.assert_allclose(
            delivered[year], 0.5 * (comp[year] + hot[year]), rtol=1e-9
        )


# ── Operation order: blend FIRST, clip at the floor LAST ────────────────────


def test_blend_then_clip_not_clip_then_blend():
    """With comp < blend < floor < hot, delivered must equal the floor exactly.

    Clip-then-blend would instead deliver (1-λ)·floor + λ·hot > floor.
    """
    lam = 0.5
    comp, hot = _component_prices()
    year = "2030"
    blend = blend_prices(comp[year], hot[year], lam)
    assert comp[year] < hot[year], "test setup requires an upward Hotelling tilt"
    floor = 0.5 * (blend + hot[year])  # strictly between blend and hot component
    assert blend < floor < hot[year]

    delivered = _path_prices(
        solve_transmission_path(
            build_markets_from_config(_base_config(reserve_prices={year: floor})),
            lam=lam,
            discount_rate=DISCOUNT_RATE,
        )
    )
    np.testing.assert_allclose(delivered[year], floor, rtol=1e-9)
    clip_then_blend = (1.0 - lam) * floor + lam * hot[year]
    assert delivered[year] < clip_then_blend


# ── The paper's transmission-immunity result ─────────────────────────────────


def test_binding_floor_is_lambda_invariant():
    """Where the floor exceeds both components, delivered price is the floor
    for every λ — the reserve price is λ-independent (paper Result 2)."""
    floors = {"2030": 1000.0, "2031": 1100.0, "2032": 1200.0}
    paths = {}
    for lam in (0.0, 0.55, 0.9):
        paths[lam] = _path_prices(
            solve_transmission_path(
                build_markets_from_config(_base_config(reserve_prices=floors)),
                lam=lam,
                discount_rate=DISCOUNT_RATE,
            )
        )
    for year, floor in floors.items():
        for lam, prices in paths.items():
            np.testing.assert_allclose(prices[year], floor, rtol=1e-12)


# ── Config layer ─────────────────────────────────────────────────────────────


def test_builder_validates_lambda_range():
    with pytest.raises(ValueError):
        normalize_config(_base_config(lam=1.5))


def test_lambda_flows_from_config_to_summary():
    summary, _ = run_simulation_from_config(_base_config(lam=0.55))
    assert "Forward Transmission Lambda" in summary.columns
    np.testing.assert_allclose(
        summary["Forward Transmission Lambda"].to_numpy(), 0.55, rtol=0, atol=1e-12
    )
    assert {"Static Component Price", "Hotelling Component Price",
            "Reserve Floor Price"} <= set(summary.columns)


def test_lambda_absent_keeps_plain_competitive_behaviour():
    summary, _ = run_simulation_from_config(_base_config())
    assert "Forward Transmission Lambda" not in summary.columns
