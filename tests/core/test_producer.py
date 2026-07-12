"""Analytical-anchor tests for the D3-2 multi-commodity producer (T0).

Anchors on the economist's finite-β case (V-D3-5b): per-firm parameters
γ=5, δ=2, σ=5, β=10, a_max=5, φ_OBA=0, F_lump=0, evaluated at
(P_steel=60, P_carbon=10). Every numeric assertion uses
``np.testing.assert_allclose`` with an explicit tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest

from pe.core.market.model import CarbonMarket
from pe.core.participant.models import ComplianceOutcome
from pe.core.participant.producer import (
    CleanTechOption,
    MultiCommodityProducer,
    ProducerParams,
    effective_intensity,
    optimize_producer,
    propose_clean_tech_adoptions,
)

# The economist's finite-β anchor (V-D3-5b), per representative firm.
ANCHOR = ProducerParams(gamma=5.0, delta=2.0, sigma=5.0, beta=10.0, a_max=5.0)
P_STEEL = 60.0
P_CARBON = 10.0


def test_finite_beta_anchor_interior() -> None:
    """Interior a* (clip slack): q*=5, a*=1, e*=20, B=45, π=25 per firm."""
    out = optimize_producer(ANCHOR, P_STEEL, P_CARBON)
    # a* = clip(P_c/β, 0, a_max) = clip(10/10, 0, 5) = 1.0 (clip inactive)
    np.testing.assert_allclose(out.a, 1.0, rtol=0, atol=1e-9)
    assert out.clip_binds is False
    # B = 0.5*10*1 + 10*(5-1) = 45
    np.testing.assert_allclose(out.net_carbon_burden, 45.0, rtol=0, atol=1e-9)
    # q* = (60 - 5 - 45) / 2 = 5.0
    np.testing.assert_allclose(out.q, 5.0, rtol=0, atol=1e-9)
    # e* = (5 - 1) * 5 = 20.0
    np.testing.assert_allclose(out.emissions, 20.0, rtol=0, atol=1e-9)
    # π = 60*5 - (5*5 + 0.5*2*25) - 0.5*10*1*5 - 10*20 + 0 = 25
    np.testing.assert_allclose(out.profit, 25.0, rtol=0, atol=1e-9)
    assert out.output_floored is False


def test_amax_clip_binds() -> None:
    """β=1, a_max=1: a* clipped to 1 (not P_c/β=10); B, q* use the clipped a*."""
    params = ProducerParams(gamma=5.0, delta=2.0, sigma=5.0, beta=1.0, a_max=1.0)
    out = optimize_producer(params, P_STEEL, P_CARBON)
    # a* = clip(10/1, 0, 1) = 1.0, and the clip is ACTIVE
    np.testing.assert_allclose(out.a, 1.0, rtol=0, atol=1e-9)
    assert out.clip_binds is True
    # B computed from the CLIPPED a* = 1: 0.5*1*1 + 10*(5-1) = 40.5 (NOT P_c/β)
    np.testing.assert_allclose(out.net_carbon_burden, 40.5, rtol=0, atol=1e-9)
    # q* = (60 - 5 - 40.5) / 2 = 7.25
    np.testing.assert_allclose(out.q, 7.25, rtol=0, atol=1e-9)
    # e* = (5 - 1) * 7.25 = 29.0
    np.testing.assert_allclose(out.emissions, 29.0, rtol=0, atol=1e-9)


def test_output_floor_exit() -> None:
    """A steel price below break-even (γ+B) shuts output: q*=0, e*=0."""
    # Break-even P_steel = γ + B = 5 + 45 = 50; probe below it.
    out = optimize_producer(ANCHOR, 40.0, P_CARBON)
    np.testing.assert_allclose(out.q, 0.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(out.emissions, 0.0, rtol=0, atol=1e-12)
    assert out.output_floored is True
    # a* is still the intensity FOC even when output is shut.
    np.testing.assert_allclose(out.a, 1.0, rtol=0, atol=1e-9)


def test_oba_raises_output_and_lowers_net_demand() -> None:
    """OBA φ_OBA>0 raises q* and cuts net demand by φ_OBA·q*; a* unchanged."""
    no_oba = optimize_producer(ANCHOR, P_STEEL, P_CARBON)
    with_oba = optimize_producer(
        ProducerParams(gamma=5.0, delta=2.0, sigma=5.0, beta=10.0, a_max=5.0, phi_oba=1.0),
        P_STEEL,
        P_CARBON,
    )
    # OBA is a marginal output subsidy: q* strictly rises...
    assert with_oba.q > no_oba.q
    # ...q* = (60 - 5 - (45 - 10*1)) / 2 = 10.0
    np.testing.assert_allclose(with_oba.q, 10.0, rtol=0, atol=1e-9)
    # ...while a* is untouched (OBA enters B only, not the intensity FOC).
    np.testing.assert_allclose(with_oba.a, no_oba.a, rtol=0, atol=1e-12)
    # Net demand = e* - free_alloc, free_alloc = F_lump + φ_OBA·q* = 0 + 1*10 = 10.
    np.testing.assert_allclose(with_oba.free_allocation, 10.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(
        with_oba.net_allowance_demand,
        with_oba.emissions - (0.0 + 1.0 * with_oba.q),
        rtol=0,
        atol=1e-12,
    )
    # e* = (5-1)*10 = 40 ⇒ net = 40 - 10 = 30.
    np.testing.assert_allclose(with_oba.net_allowance_demand, 30.0, rtol=0, atol=1e-9)


def test_carbon_face_returns_net_demand() -> None:
    """optimize_compliance duck-types the participant protocol: net = e* - F."""
    prod = MultiCommodityProducer(name="steel", params=ANCHOR)
    prod.stamp_steel_price(P_STEEL)
    outcome = prod.optimize_compliance(P_CARBON)
    assert isinstance(outcome, ComplianceOutcome)
    # net_allowances_traded = residual - free_alloc = 20 - 0 = 20 (anchor).
    np.testing.assert_allclose(outcome.net_allowances_traded, 20.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(outcome.residual_emissions, 20.0, rtol=0, atol=1e-9)
    np.testing.assert_allclose(outcome.free_allocation, 0.0, rtol=0, atol=1e-12)


def test_carbon_face_reads_stamped_steel_price() -> None:
    """The carbon face prices output off the STAMPED steel price."""
    prod = MultiCommodityProducer(name="steel", params=ANCHOR)
    prod.stamp_steel_price(60.0)
    hi = prod.optimize_compliance(P_CARBON).net_allowances_traded
    prod.stamp_steel_price(50.0)
    lo = prod.optimize_compliance(P_CARBON).net_allowances_traded
    # Lower steel price ⇒ less output ⇒ lower emissions ⇒ lower net demand.
    assert lo < hi
    # At P_steel = γ + B = 50 exactly, q*=0 ⇒ net demand = 0.
    np.testing.assert_allclose(lo, 0.0, rtol=0, atol=1e-9)


def test_steel_face_reads_stamped_carbon_price() -> None:
    """The steel face returns q* priced off the STAMPED carbon price."""
    prod = MultiCommodityProducer(name="steel", params=ANCHOR)
    prod.stamp_carbon_price(P_CARBON)
    np.testing.assert_allclose(prod.product_supply(P_STEEL), 5.0, rtol=0, atol=1e-9)
    # A carbon-price override bypasses the stamp.
    np.testing.assert_allclose(
        prod.product_supply(P_STEEL, carbon_price=0.0),
        (P_STEEL - ANCHOR.gamma) / ANCHOR.delta,  # P_c=0 ⇒ a=0, B=0 ⇒ q=(60-5)/2
        rtol=0,
        atol=1e-9,
    )


def test_duck_types_solve_equilibrium() -> None:
    """solve_equilibrium accepts a producer in its participant list unchanged.

    Documents the read surface: name / penalty_price / free_allocation (read by
    CarbonMarket.__init__) and optimize_compliance -> .net_allowances_traded
    (read by the carbon Brent solve).
    """
    prod = MultiCommodityProducer(name="steel", params=ANCHOR)
    prod.stamp_steel_price(P_STEEL)

    # Protocol surface the carbon solver relies on.
    assert isinstance(prod.name, str)
    assert prod.penalty_price >= 0.0
    assert np.isfinite(prod.free_allocation)
    assert callable(prod.optimize_compliance)
    probe = prod.optimize_compliance(5.0)
    assert hasattr(probe, "net_allowances_traded")

    # Stand-in smoke: the carbon Brent solve runs with a producer participant.
    market = CarbonMarket(
        participants=[prod],
        total_cap=1000.0,
        auction_offered=100.0,
        price_upper_bound=1000.0,
        scenario_name="producer-smoke",
    )
    result = market.solve_equilibrium()
    assert "price" in result
    assert np.isfinite(result["price"])
    assert result["price"] >= 0.0


def test_determinism() -> None:
    """Identical (P_steel, P_carbon) ⇒ bit-identical outcome."""
    a = optimize_producer(ANCHOR, P_STEEL, P_CARBON)
    b = optimize_producer(ANCHOR, P_STEEL, P_CARBON)
    for fieldname in (
        "q",
        "a",
        "emissions",
        "profit",
        "net_carbon_burden",
        "free_allocation",
        "net_allowance_demand",
        "abatement_cost",
        "initial_emissions",
    ):
        assert getattr(a, fieldname) == getattr(b, fieldname)


def test_delta_non_positive_rejected() -> None:
    """δ <= 0 is indeterminate output and is rejected at construction (JC3)."""
    with pytest.raises(ValueError, match="delta"):
        ProducerParams(gamma=5.0, delta=0.0, sigma=5.0, beta=10.0, a_max=5.0)
    with pytest.raises(ValueError, match="delta"):
        ProducerParams(gamma=5.0, delta=-1.0, sigma=5.0, beta=10.0, a_max=5.0)


def test_beta_non_positive_rejected() -> None:
    """β <= 0 makes the intensity FOC ill-posed and is rejected."""
    with pytest.raises(ValueError, match="beta"):
        ProducerParams(gamma=5.0, delta=2.0, sigma=5.0, beta=0.0, a_max=5.0)


# ── D3-5 cleaner-tech adoption (the long-run intensity margin, spec §4g) ────────

_H2 = CleanTechOption(name="H2-DRI", sigma_prime=3.0, theta=9.0)


def test_effective_intensity_takes_the_lowest_adopted_option() -> None:
    """σ_eff = min(σ, adopted σ'); un-adopted keeps σ; adopted drops to σ'."""
    options = (_H2,)
    assert effective_intensity(5.0, options, frozenset()) == 5.0
    assert effective_intensity(5.0, options, frozenset({"H2-DRI"})) == 3.0
    # Two options: the lowest adopted wins (monotone downward shift).
    both = (_H2, CleanTechOption(name="CCS", sigma_prime=4.0, theta=6.0))
    assert effective_intensity(5.0, both, frozenset({"H2-DRI", "CCS"})) == 3.0


def test_propose_adoptions_fires_only_at_or_above_the_trigger() -> None:
    """Monotone trigger read: adopt iff P_c ≥ P* and not already adopted."""
    assert propose_clean_tech_adoptions((_H2,), 8.999, frozenset()) == []
    assert propose_clean_tech_adoptions((_H2,), 9.0, frozenset()) == ["H2-DRI"]
    assert propose_clean_tech_adoptions((_H2,), 20.0, frozenset()) == ["H2-DRI"]
    # Already adopted ⇒ no re-proposal (the caller's monotone floor).
    assert propose_clean_tech_adoptions((_H2,), 20.0, frozenset({"H2-DRI"})) == []


def test_break_even_trigger_reports_p_star_equal_theta() -> None:
    """Ruling #1: break_even mode ⇒ M ≡ 1 ⇒ P* = θ (the D3-6 golden mode)."""
    np.testing.assert_allclose(_H2.trigger_multiple(), 1.0, rtol=0, atol=0)
    np.testing.assert_allclose(_H2.p_star, 9.0, rtol=0, atol=0)


def test_option_value_trigger_multiple_matches_core_investment() -> None:
    """Ruling #1: option_value M = β/(β−1) reuses core.investment, P* = M·θ.

    Analytical anchor: the certainty limit (σ_eff = 0 via credibility q = 1)
    is the pure timing wedge M = r/y (paper A.10), so P* = (r/y)·θ.
    """
    from pe.core.investment import effective_volatility, trigger_multiple

    opt = CleanTechOption(
        name="H2-DRI",
        sigma_prime=3.0,
        theta=9.0,
        trigger_mode="option_value",
        sigma=0.48,
        credibility=0.0,
        discount_rate=0.055,
        payout_yield=0.03,
    )
    expected_M = trigger_multiple(effective_volatility(0.48, 0.0), 0.055, 0.03)
    np.testing.assert_allclose(opt.trigger_multiple(), expected_M, rtol=0, atol=1e-12)
    np.testing.assert_allclose(opt.p_star, expected_M * 9.0, rtol=0, atol=1e-12)
    assert opt.p_star > 9.0  # the option-value wedge sits ABOVE the break-even θ

    # Certainty limit q = 1 ⇒ σ_eff = 0 ⇒ M = r/y (0.055/0.03), P* = (r/y)·θ.
    certain = CleanTechOption(
        name="H2-DRI",
        sigma_prime=3.0,
        theta=9.0,
        trigger_mode="option_value",
        sigma=0.48,
        credibility=1.0,
        discount_rate=0.055,
        payout_yield=0.03,
    )
    np.testing.assert_allclose(certain.trigger_multiple(), 0.055 / 0.03, rtol=0, atol=1e-12)


def test_trigger_multiple_override_pins_m_directly() -> None:
    """Ruling #1: trigger_multiple_override pins M (the M=1 escape hatch)."""
    override = CleanTechOption(
        name="H2-DRI", sigma_prime=3.0, theta=9.0, trigger_multiple_override=1.0
    )
    np.testing.assert_allclose(override.p_star, 9.0, rtol=0, atol=0)
    lifted = CleanTechOption(
        name="H2-DRI", sigma_prime=3.0, theta=9.0, trigger_multiple_override=2.0
    )
    np.testing.assert_allclose(lifted.p_star, 18.0, rtol=0, atol=0)


def test_option_value_requires_well_posed_r_and_y() -> None:
    """option_value with no override needs r > 0 and y > 0 (fail loud, ruling #1)."""
    with pytest.raises(ValueError, match="discount_rate"):
        CleanTechOption(
            name="x", sigma_prime=3.0, theta=9.0, trigger_mode="option_value", payout_yield=0.03
        )
    with pytest.raises(ValueError, match="payout_yield"):
        CleanTechOption(
            name="x", sigma_prime=3.0, theta=9.0, trigger_mode="option_value", discount_rate=0.055
        )


def test_adopted_intensity_feeds_the_output_foc_analytically() -> None:
    """With H2-DRI adopted (σ'=3) at (P_s=60, P_c=10): a=1, q=(60−5−B)/2.

    B = ½·10·1² + 10·(3−1) = 5 + 20 = 25 ⇒ q = (60−5−25)/2 = 15, e = (3−1)·15 = 30.
    """
    params = ProducerParams(
        gamma=5.0,
        delta=2.0,
        sigma=5.0,
        beta=10.0,
        a_max=5.0,
        technology_options=(_H2,),
        adopted_tech=frozenset({"H2-DRI"}),
    )
    out = optimize_producer(params, 60.0, 10.0)
    np.testing.assert_allclose(out.a, 1.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(out.net_carbon_burden, 25.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(out.q, 15.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(out.emissions, 30.0, rtol=0, atol=1e-12)


def test_clean_tech_option_validates_bounds() -> None:
    """σ' and θ must be finite and positive; name non-empty; mode in the set."""
    with pytest.raises(ValueError, match="sigma_prime"):
        CleanTechOption(name="x", sigma_prime=-1.0, theta=9.0)
    with pytest.raises(ValueError, match="theta"):
        CleanTechOption(name="x", sigma_prime=3.0, theta=-1.0)
    with pytest.raises(ValueError, match="theta"):
        CleanTechOption(name="x", sigma_prime=3.0, theta=0.0)
    with pytest.raises(ValueError, match="name"):
        CleanTechOption(name="", sigma_prime=3.0, theta=9.0)
    with pytest.raises(ValueError, match="trigger_mode"):
        CleanTechOption(name="x", sigma_prime=3.0, theta=9.0, trigger_mode="bogus")
    with pytest.raises(ValueError, match="trigger_multiple_override"):
        CleanTechOption(name="x", sigma_prime=3.0, theta=9.0, trigger_multiple_override=0.5)
