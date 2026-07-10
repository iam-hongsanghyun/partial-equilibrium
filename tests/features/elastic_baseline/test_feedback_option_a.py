"""Tests for Feedback Option A — the price-elastic baseline.

Covers the activity-multiplier arithmetic, the neutrality guarantee (disabled →
identical to the inelastic tool), and the end-to-end demand-destruction effect.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ets.config_io import build_participant
from ets.features.elastic_baseline.plugin import stamp_and_attach
from ets.solvers import run_simulation_from_config, run_simulation_from_file

EXAMPLE = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "feedback_a_price_elastic_baseline.json"
)


def _participant(eps: float, p_ref: float):
    """Build a participant and stamp/attach the elastic baseline via the plugin door.

    Uses ``stamp_and_attach`` rather than a bare
    ``p.reference_carbon_price = p_ref`` assignment: the latter is the
    bypass ``MarketParticipant``'s loud guard rejects for ``eps > 0``
    (Arbitration outcomes, O8) — see
    ``tests/test_elastic_baseline_overlay.py`` for a direct test of that
    guard. This helper reproduces the exact multiplier values the
    pre-refactor direct assignment produced.
    """
    p = build_participant(
        {
            "name": "X",
            "initial_emissions": 100.0,
            "free_allocation_ratio": 0.0,
            "penalty_price": 400.0,
            "abatement_type": "linear",
            "max_abatement": 30.0,
            "cost_slope": 2.0,
            "threshold_cost": 0.0,
            "mac_blocks": [],
            "output_price_elasticity": eps,
        }
    )
    return stamp_and_attach(p, p_ref)


# ── Unit: the multiplier ─────────────────────────────────────────────────────


def test_multiplier_is_one_at_reference():
    p = _participant(eps=0.5, p_ref=50.0)
    np.testing.assert_allclose(p.activity_multiplier(50.0), 1.0, atol=1e-12)


def test_multiplier_contracts_above_and_expands_below():
    p = _participant(eps=0.5, p_ref=50.0)
    # +20% over reference → 1 - 0.5*0.2 = 0.90
    np.testing.assert_allclose(p.activity_multiplier(60.0), 0.90, atol=1e-12)
    # -20% under reference → 1 + 0.5*0.2 = 1.10
    np.testing.assert_allclose(p.activity_multiplier(40.0), 1.10, atol=1e-12)


def test_multiplier_floored_at_zero():
    p = _participant(eps=2.0, p_ref=50.0)
    # Huge price → linear form would go negative; must floor at 0.
    assert p.activity_multiplier(500.0) == 0.0


def test_disabled_returns_unity():
    assert _participant(eps=0.0, p_ref=50.0).activity_multiplier(120.0) == 1.0
    assert _participant(eps=0.5, p_ref=0.0).activity_multiplier(120.0) == 1.0


def test_negative_elasticity_rejected():
    with pytest.raises(ValueError):
        _participant(eps=-0.1, p_ref=50.0)


# ── Integration: neutrality and demand destruction ──────────────────────────


def _single_year(eps: float, p_ref: float) -> dict:
    return {
        "scenarios": [
            {
                "name": "S",
                "model_approach": "competitive",
                "reference_carbon_price": p_ref,
                "years": [
                    {
                        "year": "2030",
                        "total_cap": 500.0,
                        "auction_mode": "explicit",
                        "auction_offered": 300.0,
                        "price_lower_bound": 0.0,
                        "price_upper_bound": 400.0,
                        "banking_allowed": False,
                        "participants": [
                            {"name": "Steel", "initial_emissions": 200.0, "free_allocation_ratio": 0.3, "penalty_price": 400.0, "abatement_type": "linear", "max_abatement": 60.0, "cost_slope": 2.5, "output_price_elasticity": eps},
                            {"name": "Power", "initial_emissions": 250.0, "free_allocation_ratio": 0.2, "penalty_price": 400.0, "abatement_type": "linear", "max_abatement": 100.0, "cost_slope": 1.5, "output_price_elasticity": eps},
                        ],
                    }
                ],
            }
        ]
    }


def test_disabled_reproduces_inelastic_price():
    s_off, _ = run_simulation_from_config(_single_year(0.0, 50.0))
    s_ref0, _ = run_simulation_from_config(_single_year(0.5, 0.0))
    p_off = float(s_off["Equilibrium Carbon Price"].iloc[0])
    p_ref0 = float(s_ref0["Equilibrium Carbon Price"].iloc[0])
    np.testing.assert_allclose(p_off, p_ref0, rtol=0, atol=1e-9)


def test_contraction_lowers_price_when_reference_below_equilibrium():
    """Reference below the inelastic equilibrium → activity contracts → lower price."""
    base, _ = run_simulation_from_config(_single_year(0.0, 20.0))
    elastic, _ = run_simulation_from_config(_single_year(0.6, 20.0))
    p_base = float(base["Equilibrium Carbon Price"].iloc[0])
    p_elastic = float(elastic["Equilibrium Carbon Price"].iloc[0])
    assert p_elastic < p_base


def test_example_elastic_path_is_flatter_and_lower():
    summary, _ = run_simulation_from_file(str(EXAMPLE))
    fixed = summary[summary["Scenario"] == "Fixed Baseline (inelastic)"].sort_values("Year")
    elastic = summary[summary["Scenario"] == "Price-Elastic Baseline"].sort_values("Year")
    fp = fixed["Equilibrium Carbon Price"].to_numpy()
    ep = elastic["Equilibrium Carbon Price"].to_numpy()
    # Lower level and a flatter (smaller peak-to-trough) path under the elastic baseline.
    assert ep.max() < fp.max()
    assert (ep.max() - ep.min()) < (fp.max() - fp.min())


def test_example_reports_scaled_activity():
    """The participant 'Initial Emissions' column reflects E0*m(P) once elastic."""
    _, participants = run_simulation_from_file(str(EXAMPLE))
    el = participants[
        (participants["Scenario"] == "Price-Elastic Baseline")
        & (participants["Year"] == "2030")
        & (participants["Participant"] == "Steel")
    ]
    scaled = float(el["Initial Emissions"].iloc[0])
    assert scaled < 180.0  # nominal baseline was 180 Mt; high price contracted it
