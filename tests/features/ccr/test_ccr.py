"""Tests for the Carbon Cap Rule (CCR) — Benmir, Roman & Taschini (2025).

Covers the closed-form rule arithmetic (against hand-computed values) and the
end-to-end behaviour wired into the competitive simulation path.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ets.ccr import CCR_DEFAULTS, CCRState
from ets.solvers import run_simulation_from_file

EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "benmir_ccr_carbon_cap_rule.json"


# ── Unit: the rule arithmetic ────────────────────────────────────────────────


def test_first_period_has_no_adjustment():
    """With no realised history, Q_0 = Qbar (zero adjustment)."""
    state = CCRState()
    adj, dev_e, dev_z = state.cap_adjustment(
        phi_emissions=-100.0,
        phi_abatement_cost=20.0,
        reference_emissions=400.0,
        reference_abatement_cost=2000.0,
    )
    assert (adj, dev_e, dev_z) == (0.0, 0.0, 0.0)


def test_adjustment_matches_closed_form():
    r"""ΔQ = phi_e*(e-ebar)/ebar + phi_z*(z-zbar)/zbar against hand calc."""
    state = CCRState()
    state.record(emissions=440.0, abatement_cost=2400.0)  # period t-1 outcome

    phi_e, phi_z = -120.0, 30.0
    ebar, zbar = 400.0, 2000.0
    adj, dev_e, dev_z = state.cap_adjustment(
        phi_emissions=phi_e,
        phi_abatement_cost=phi_z,
        reference_emissions=ebar,
        reference_abatement_cost=zbar,
    )

    expected_dev_e = (440.0 - 400.0) / 400.0   # +0.10
    expected_dev_z = (2400.0 - 2000.0) / 2000.0  # +0.20
    expected_adj = phi_e * expected_dev_e + phi_z * expected_dev_z  # -12 + 6 = -6
    np.testing.assert_allclose(dev_e, expected_dev_e, rtol=0, atol=1e-12)
    np.testing.assert_allclose(dev_z, expected_dev_z, rtol=0, atol=1e-12)
    np.testing.assert_allclose(adj, expected_adj, rtol=0, atol=1e-12)


def test_sign_conventions():
    """phi_z>0 loosens on high cost; phi_e<0 tightens on high emissions."""
    # Costs above reference, emissions at reference → loosen (positive ΔQ).
    s1 = CCRState()
    s1.record(emissions=400.0, abatement_cost=3000.0)
    adj1, _, _ = s1.cap_adjustment(0.0, 25.0, 400.0, 2000.0)
    assert adj1 > 0.0

    # Emissions above reference, costs at reference → tighten (negative ΔQ).
    s2 = CCRState()
    s2.record(emissions=440.0, abatement_cost=2000.0)
    adj2, _, _ = s2.cap_adjustment(-100.0, 0.0, 400.0, 2000.0)
    assert adj2 < 0.0


def test_zero_reference_disables_term():
    """A reference of 0 disables its term (no division by zero)."""
    state = CCRState()
    state.record(emissions=440.0, abatement_cost=2400.0)
    # Emissions term disabled (ebar=0); only the cost term contributes.
    adj, dev_e, dev_z = state.cap_adjustment(
        phi_emissions=-100.0,
        phi_abatement_cost=10.0,
        reference_emissions=0.0,
        reference_abatement_cost=2000.0,
    )
    assert dev_e == 0.0
    np.testing.assert_allclose(dev_z, 0.20, rtol=0, atol=1e-12)
    np.testing.assert_allclose(adj, 10.0 * 0.20, rtol=0, atol=1e-12)


def test_defaults_are_disabled_and_neutral():
    """Shipped defaults must leave the CCR off and produce no adjustment."""
    assert CCR_DEFAULTS["ccr_enabled"] is False
    assert CCR_DEFAULTS["ccr_phi_emissions"] == 0.0
    assert CCR_DEFAULTS["ccr_phi_abatement_cost"] == 0.0
    assert CCR_DEFAULTS["ccr_reference_emissions"] == 0.0
    assert CCR_DEFAULTS["ccr_reference_abatement_cost"] == 0.0


# ── Integration: wired into the simulation ───────────────────────────────────


@pytest.fixture(scope="module")
def example_summary():
    summary, _ = run_simulation_from_file(str(EXAMPLE))
    return summary


def test_example_exposes_ccr_columns(example_summary):
    for col in ("CCR Cap Adjustment", "CCR Emissions Deviation", "CCR Cost Deviation"):
        assert col in example_summary.columns


def test_fixed_cap_scenario_never_adjusts(example_summary):
    fixed = example_summary[example_summary["Scenario"] == "Fixed Cap"]
    assert (fixed["CCR Cap Adjustment"] == 0.0).all()


def test_ccr_first_year_zero_then_responds(example_summary):
    ccr = example_summary[example_summary["Scenario"] == "Carbon Cap Rule (CCR)"]
    ccr = ccr.sort_values("Year")
    adjustments = ccr["CCR Cap Adjustment"].to_numpy()
    # First year: no history → no adjustment.
    np.testing.assert_allclose(adjustments[0], 0.0, atol=1e-12)
    # Later years respond to the persistent shock.
    assert np.any(np.abs(adjustments[1:]) > 1.0)


def test_ccr_loosens_when_abatement_cost_runs_hot(example_summary):
    """During the high-cost shock the cost deviation is positive and, with
    phi_z>0, the cap adjustment is positive (loosen)."""
    ccr = example_summary[example_summary["Scenario"] == "Carbon Cap Rule (CCR)"]
    hot = ccr[ccr["CCR Cost Deviation"] > 0.5]
    assert len(hot) >= 1
    assert (hot["CCR Cap Adjustment"] > 0.0).all()


def test_ccr_reduces_price_volatility(example_summary):
    """The headline result: the CCR damps carbon-price volatility vs a fixed cap."""
    fixed = example_summary[example_summary["Scenario"] == "Fixed Cap"]
    ccr = example_summary[example_summary["Scenario"] == "Carbon Cap Rule (CCR)"]
    std_fixed = float(np.std(fixed["Equilibrium Carbon Price"].to_numpy()))
    std_ccr = float(np.std(ccr["Equilibrium Carbon Price"].to_numpy()))
    assert std_ccr < std_fixed
