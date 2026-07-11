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
    MultiCommodityProducer,
    ProducerParams,
    optimize_producer,
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
