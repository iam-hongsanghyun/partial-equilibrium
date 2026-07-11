"""Closed-form + property tests for the D3-1 product-market clearing primitive.

Anchors are the hand-solved values of ``docs/multi-commodity-spec.md`` §5 (the
multi-commodity "J1"): 2 identical domestic producers (aggregate
:math:`\\gamma=10, \\delta=1, \\sigma=2`), no intensity abatement
(:math:`\\beta\\to\\infty`, so a binding cap pins output at
:math:`q^*=\\mathrm{Cap}/\\sigma`), linear demand :math:`A_d=120, b_d=1`,
carbon-free elastic imports :math:`M=m P_s` with :math:`m=1`,
:math:`\\sigma_{\\mathrm{foreign}}=2`. The producer agent is D3-2, so these
tests inject a *synthetic* domestic supply (a constant for the pinned cap case,
a finite-slope FOC for the no-policy counterfactual).

We test :func:`pe.core.market.product_clearing.solve_product_equilibrium`
against those closed forms, the excess-demand identity for a finite-slope
supply, monotonicity ⇒ uniqueness, and byte-determinism.
"""

from __future__ import annotations

import numpy as np

from pe.core.market.product_clearing import (
    DemandCurve,
    ImportSupply,
    solve_product_equilibrium,
)

# ── Spec §5 primitives ────────────────────────────────────────────────────────
CAP = 40.0
SIGMA = 2.0
GAMMA = 10.0
DELTA = 1.0
Q_PINNED = CAP / SIGMA  # = 20 : β→∞ binding-cap output
LINEAR_DEMAND = DemandCurve(form="linear", a_d=120.0, b_d=1.0)


def _pinned_supply(price_steel: float, price_carbon: float) -> float:
    """β→∞ + binding cap pins aggregate output at Cap/σ = 20 (spec §5)."""
    return Q_PINNED


def _producer_supply(price_steel: float, price_carbon: float) -> float:
    """Output-FOC supply from a strictly convex (quadratic) cost, β→∞.

    :math:`q^* = \\max(0, (P_s - \\gamma - P_c\\sigma)/\\delta)` — the spec §2
    output margin with no abatement saving. Clipped at 0 (the FOC corner).
    """
    return max(0.0, (price_steel - GAMMA - price_carbon * SIGMA) / DELTA)


def test_anchor_binding_cap_price_50() -> None:
    """Spec §5 main anchor: pinned q=20, m=1 imports ⇒ P_s=50, M=50, D=70.

    excess(P_s) = 20 + 1·P_s − (120 − 1·P_s) = 2·P_s − 100 = 0 ⇒ P_s = 50.
    (P_carbon=10 at the joint fixed point; irrelevant here since the pinned
    supply is P_carbon-independent — the block-recursive corner, spec §5 [JC6].)
    """
    result = solve_product_equilibrium(
        _pinned_supply,
        price_carbon=10.0,
        demand=LINEAR_DEMAND,
        imports=ImportSupply(m=1.0),
    )
    np.testing.assert_allclose(result["price"], 50.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["domestic_supply"], 20.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["imports"], 50.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["quantity"], 70.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["excess"], 0.0, rtol=0.0, atol=1e-9)
    # domestic share of the cleared market = 20/70.
    np.testing.assert_allclose(result["coverage"], 20.0 / 70.0, rtol=0.0, atol=1e-9)
    assert result["regime"] == "interior"
    assert result["converged"] is True


def test_no_policy_counterfactual_finite_supply() -> None:
    """Spec §5 no-policy (P_carbon=0): finite FOC supply ⇒ P_s = 130/3.

    excess(P_s) = (P_s − 10) + P_s − (120 − P_s) = 3·P_s − 130 = 0
    ⇒ P_s = 130/3 = 43.33, q = 100/3, M = 130/3, D = 230/3.
    """
    result = solve_product_equilibrium(
        _producer_supply,
        price_carbon=0.0,
        demand=LINEAR_DEMAND,
        imports=ImportSupply(m=1.0),
    )
    np.testing.assert_allclose(result["price"], 130.0 / 3.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["domestic_supply"], 100.0 / 3.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["imports"], 130.0 / 3.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["quantity"], 230.0 / 3.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["excess"], 0.0, rtol=0.0, atol=1e-9)


def test_cbam_half_coverage_price_56_67() -> None:
    """Spec §5 levers-on (CBAM c=0.5): pinned q=20 ⇒ P_s = 170/3 = 56.67.

    M = m·(P_s − c·P_c·σ_foreign) = P_s − P_c with c=0.5, σ_foreign=2, P_c=40/3.
    excess = 20 + (P_s − P_c) − (120 − P_s) = 2·P_s − (100 + P_c) = 0
    ⇒ P_s = (100 + 40/3)/2 = 170/3 = 56.67, M = 170/3 − 40/3 = 130/3 = 43.33.
    """
    p_carbon = 40.0 / 3.0  # = 13.33, the CBAM-variant joint carbon price
    result = solve_product_equilibrium(
        _pinned_supply,
        price_carbon=p_carbon,
        demand=LINEAR_DEMAND,
        imports=ImportSupply(m=1.0, cbam_enabled=True, coverage=0.5, sigma_foreign=2.0),
    )
    np.testing.assert_allclose(result["price"], 170.0 / 3.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["imports"], 130.0 / 3.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["domestic_supply"], 20.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["excess"], 0.0, rtol=0.0, atol=1e-9)


def test_no_policy_matches_direct_solve_no_cbam() -> None:
    """CBAM off must reduce to the base import schedule (regression guard)."""
    base = solve_product_equilibrium(
        _pinned_supply,
        price_carbon=10.0,
        demand=LINEAR_DEMAND,
        imports=ImportSupply(m=1.0),
    )
    cbam_off = solve_product_equilibrium(
        _pinned_supply,
        price_carbon=10.0,
        demand=LINEAR_DEMAND,
        imports=ImportSupply(m=1.0, cbam_enabled=False, coverage=0.5, sigma_foreign=2.0),
    )
    np.testing.assert_allclose(cbam_off["price"], base["price"], rtol=0.0, atol=1e-12)


def test_finite_slope_supply_clears_at_zero_excess_and_is_monotone() -> None:
    """Upward-sloping supply: excess≈0 at the returned price; excess strictly ↑.

    Monotone excess ⇒ a unique root (the primitive's whole justification for a
    single bracket-then-Brent solve).
    """
    supply = _producer_supply
    imports = ImportSupply(m_0=5.0, m=0.5)
    p_carbon = 3.0
    result = solve_product_equilibrium(
        supply,
        price_carbon=p_carbon,
        demand=LINEAR_DEMAND,
        imports=imports,
    )
    price = float(result["price"])

    def excess(p: float) -> float:
        return supply(p, p_carbon) + imports(p, p_carbon) - LINEAR_DEMAND(p)

    # Excess-demand identity: supply + imports = demand at the clearing price.
    np.testing.assert_allclose(excess(price), 0.0, rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(
        result["domestic_supply"] + result["imports"],
        result["quantity"],
        rtol=0.0,
        atol=1e-9,
    )

    # Monotonicity ⇒ uniqueness: excess strictly increasing over the bracket.
    grid = np.linspace(15.0, 120.0, 400)  # above the FOC corner (P_s > γ)
    excess_vals = np.array([excess(float(p)) for p in grid])
    assert np.all(np.diff(excess_vals) > 0.0)
    # A single sign change ⇒ exactly one root.
    sign_changes = int(np.sum(np.diff(np.sign(excess_vals)) != 0))
    assert sign_changes == 1


def test_isoelastic_demand_numeric_root() -> None:
    """Isoelastic demand D=κ·P_s^{-η} solved numerically against its quadratic.

    κ=1000, η=1, pinned q=20, M=P_s (m=1): excess = 20 + P_s − 1000/P_s = 0
    ⇒ P_s² + 20·P_s − 1000 = 0 ⇒ P_s = (−20 + √4400)/2.
    """
    demand = DemandCurve(form="isoelastic", kappa=1000.0, eta=1.0)
    result = solve_product_equilibrium(
        _pinned_supply,
        price_carbon=0.0,
        demand=demand,
        imports=ImportSupply(m=1.0),
    )
    p_expected = (-20.0 + np.sqrt(4400.0)) / 2.0
    np.testing.assert_allclose(result["price"], p_expected, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result["excess"], 0.0, rtol=0.0, atol=1e-6)


def test_glut_boundary_pins_to_floor_never_raises() -> None:
    """Supply ≥ demand at the floor ⇒ price pinned to the floor (total clearing).

    Constant supply 200 > choke demand 120 at P_s=0 ⇒ excess(0) > 0 ⇒ glut.
    """

    def big_supply(price_steel: float, price_carbon: float) -> float:
        return 200.0

    result = solve_product_equilibrium(
        big_supply,
        price_carbon=0.0,
        demand=LINEAR_DEMAND,
        imports=ImportSupply(m=0.0),
        price_lower=0.0,
    )
    np.testing.assert_allclose(result["price"], 0.0, rtol=0.0, atol=1e-12)
    assert result["regime"] == "glut"
    assert result["converged"] is True


def test_unbracketable_demand_clamps_to_ceiling_loudly() -> None:
    """Demand outruns supply everywhere ⇒ ceiling fallback, never raises.

    Constant demand 500 with zero supply/imports can never be met ⇒ excess<0
    on the whole (capped) bracket ⇒ regime='ceiling', converged=False.
    """

    def zero_supply(price_steel: float, price_carbon: float) -> float:
        return 0.0

    flat_demand = DemandCurve(form="linear", a_d=500.0, b_d=0.0)
    result = solve_product_equilibrium(
        zero_supply,
        price_carbon=0.0,
        demand=flat_demand,
        imports=ImportSupply(m=0.0),
        max_bracket_expansions=3,
    )
    assert result["regime"] == "ceiling"
    assert result["converged"] is False
    assert result["bracket_expansions"] == 3


def test_determinism_identical_inputs_identical_price() -> None:
    """Fixed Brent tolerances ⇒ identical inputs return a bit-identical price."""
    kwargs = dict(
        price_carbon=7.5,
        demand=LINEAR_DEMAND,
        imports=ImportSupply(m_0=2.0, m=0.75),
    )
    first = solve_product_equilibrium(_producer_supply, **kwargs)
    second = solve_product_equilibrium(_producer_supply, **kwargs)
    assert first["price"] == second["price"]
    assert first == second
