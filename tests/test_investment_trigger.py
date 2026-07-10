"""Tests for the Dixit–Pindyck investment-trigger module.

Regression-tests the closed-form β and trigger multiple against the K-MSR
paper's worked values (Appendices A.7/A.10) and the analytical σ = 0 limit.
"""

from __future__ import annotations

import numpy as np
import pytest

from ets.analysis.investment_trigger import (
    activation_year,
    beta_positive_root,
    credible_floor_multiple,
    effective_volatility,
    trigger_multiple,
)

R, Y = 0.055, 0.03  # paper's r = 5.5 %, y = 3 %


# ── β and the multiple against the paper's worked values ────────────────────


def test_beta_satisfies_fundamental_quadratic():
    """Analytical check: the root plugged back into ½σ²β(β−1)+(r−y)β−r ≈ 0."""
    for sigma in (0.1, 0.2, 0.3, 0.48):
        beta = beta_positive_root(sigma, R, Y)
        residual = 0.5 * sigma**2 * beta * (beta - 1.0) + (R - Y) * beta - R
        np.testing.assert_allclose(residual, 0.0, rtol=0, atol=1e-12)
        assert beta > 1.0


def test_paper_worked_value_sigma_020():
    """Paper A.7: σ=0.20, r=5.5%, y=3% → β ≈ 1.54, multiple ≈ 2.86."""
    beta = beta_positive_root(0.20, R, Y)
    np.testing.assert_allclose(beta, 1.54, rtol=5e-3)
    np.testing.assert_allclose(trigger_multiple(0.20, R, Y), 2.86, rtol=5e-3)


def test_paper_headline_sigma_030():
    """Paper §6: σ=0.30 implies a trigger of ≈ 3.86× break-even."""
    np.testing.assert_allclose(trigger_multiple(0.30, R, Y), 3.86, rtol=2e-3)


def test_paper_empirical_sigma_048():
    """Paper §3: at the KAU-estimated σ ≈ 0.48 the unfloored multiple is ≈ 6.4×."""
    np.testing.assert_allclose(trigger_multiple(0.48, R, Y), 6.4, rtol=5e-3)


def test_certainty_limit_is_timing_wedge():
    """Paper A.10: σ→0 gives β = r/(r−y) = 2.2 and multiple = r/y ≈ 1.83."""
    np.testing.assert_allclose(beta_positive_root(0.0, R, Y), 2.2, rtol=0, atol=1e-12)
    np.testing.assert_allclose(
        credible_floor_multiple(R, Y), R / Y, rtol=0, atol=1e-12
    )
    np.testing.assert_allclose(credible_floor_multiple(R, Y), 1.8333, rtol=1e-4)


def test_multiple_increases_with_volatility():
    sigmas = [0.0, 0.1, 0.2, 0.3, 0.48]
    multiples = [trigger_multiple(s, R, Y) for s in sigmas]
    assert all(a < b for a, b in zip(multiples, multiples[1:]))


def test_input_validation():
    with pytest.raises(ValueError):
        beta_positive_root(-0.1, R, Y)
    with pytest.raises(ValueError):
        beta_positive_root(0.3, 0.0, Y)
    with pytest.raises(ValueError):
        beta_positive_root(0.3, R, 0.0)
    with pytest.raises(ValueError):
        beta_positive_root(0.0, R, R)  # certainty limit needs y < r


# ── Credibility interpolation ────────────────────────────────────────────────


def test_effective_volatility_endpoints():
    np.testing.assert_allclose(effective_volatility(0.48, 1.0), 0.0, atol=1e-15)
    np.testing.assert_allclose(effective_volatility(0.48, 0.0), 0.48, atol=1e-15)
    with pytest.raises(ValueError):
        effective_volatility(0.48, 1.1)


def test_credibility_sweep_spans_paper_range():
    """q: 0 → 1 moves the multiple from ≈3.86 down to ≈1.83 (paper Fig. 5)."""
    lo = trigger_multiple(effective_volatility(0.30, 1.0), R, Y)
    hi = trigger_multiple(effective_volatility(0.30, 0.0), R, Y)
    np.testing.assert_allclose(lo, R / Y, rtol=1e-9)
    np.testing.assert_allclose(hi, 3.86, rtol=2e-3)


# ── Activation dating on a price path ────────────────────────────────────────


def test_activation_at_break_even():
    """Rule A tops out at the threshold: break-even dating activates in 2035."""
    path = {"2026": 22750.0, "2030": 55972.0, "2035": 97500.0, "2040": 97500.0}
    assert activation_year(path, 97500.0, multiple=1.0) == "2035"


def test_dixit_pindyck_dating_never_activates_on_a_capped_floor():
    """With any multiple > 1 a schedule capped AT break-even never triggers —
    the paper's point that the schedule must escalate above bare break-even."""
    path = {"2026": 22750.0, "2030": 55972.0, "2035": 97500.0, "2040": 97500.0}
    assert activation_year(path, 97500.0, multiple=credible_floor_multiple(R, Y)) is None


def test_declining_threshold_mapping():
    path = {"2030": 60000.0, "2035": 97500.0}
    theta = {"2030": 120000.0, "2035": 97500.0}
    assert activation_year(path, theta, multiple=1.0) == "2035"
    with pytest.raises(ValueError):
        activation_year(path, {"2030": 120000.0}, multiple=1.0)


def test_activation_rejects_sub_unity_multiple():
    with pytest.raises(ValueError):
        activation_year({"2030": 1.0}, 1.0, multiple=0.9)
