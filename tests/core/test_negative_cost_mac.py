"""Negative-cost MAC blocks ("no-regret" abatement measures).

Real marginal-abatement-cost curves include net-saving measures with a negative
marginal cost. These must load (amount stays non-negative, marginal_cost may be
negative) and be abated even at a low carbon price. The K-ETS Outlook example
exercises this end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ets.config_io import build_participant
from ets.costs import piecewise_abatement_factory
from ets.solvers import run_simulation_from_file

KETS = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "climate_solutions_k_ets_outlook.json"
)


def test_piecewise_factory_accepts_negative_marginal_cost():
    rule = piecewise_abatement_factory(
        [
            {"amount": 5.0, "marginal_cost": -100.0},  # no-regret, net-saving
            {"amount": 3.0, "marginal_cost": 40.0},
        ]
    )
    # At a zero price the no-regret block is still undertaken; the positive-cost
    # block is not.
    assert rule(0.0) == 5.0
    # At a price above the second block's cost, both are undertaken.
    assert rule(50.0) == 8.0


def test_amount_must_still_be_non_negative():
    with pytest.raises(ValueError):
        piecewise_abatement_factory([{"amount": -1.0, "marginal_cost": 10.0}])


def test_participant_with_negative_cost_block_builds_and_abates():
    p = build_participant(
        {
            "name": "Steel",
            "initial_emissions": 100.0,
            "free_allocation_ratio": 0.0,
            "penalty_price": 400.0,
            "abatement_type": "piecewise",
            "mac_blocks": [
                {"amount": 8.0, "marginal_cost": -50.0},
                {"amount": 12.0, "marginal_cost": 30.0},
            ],
        }
    )
    # Even at a price of 5 the no-regret block (mc -50) is worth abating in full
    # (allow a small tolerance from the bounded scalar optimiser).
    outcome = p.optimize_compliance(5.0)
    assert outcome.abatement == pytest.approx(8.0, abs=1e-3)


def test_kets_outlook_example_runs():
    summary, _ = run_simulation_from_file(str(KETS))
    assert summary["Scenario"].nunique() == 3
    # Prices are finite and non-negative across all scenario-years.
    prices = summary["Equilibrium Carbon Price"]
    assert prices.notna().all()
    assert (prices >= 0).all()
