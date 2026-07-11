r"""Floor-cancellation direct-complementarity anchors (docs/floor-cancellation-fix.md §4).

The fix cures the single-market ``banking`` + ``unsold_treatment: "cancel"`` +
binding-floor 2-cycle (TODO.md). Two coupled, regime-aware changes:

* ``FloorCancellationRule`` decides binding by the price-free CONTEMPORANEOUS
  test ``e_t(F_t) < S_t`` (demand-at-floor below supply) on FIXED quantities,
  NOT the discontinuous lagged predicate ``floor > solved_price`` — the source
  of the orbit.
* the banking host gates the rule by REGIME. STATIC years apply it
  unconditionally (price-free, so no orbit). WINDOW years apply it only where
  the floor CLIPS the arbitrage price (``F_t > P_t``): a window year the floor
  does not clip banks its surplus and never cancels (V3, the spec's
  ``P_t >= F_t`` premise); a window year the floor DOES clip still cancels —
  BYTE-IDENTICAL to the pre-fix rule (the window-cancel path is anchored
  elsewhere: ``test_price_controls.py`` ``_floor_binding_config`` and the
  endogenous-investment V6 supply-accounting identity). Only the STATIC-year
  binding test changes here, and that is what kills the 2-cycle.

Hand-solvable economy (single participant, linear MAC slope σ = ``cost_slope``,
free-alloc 0, penalty 0): residual ``e(p) = E0 − p/σ``, static clearing
``P(S) = σ(E0 − S)``, ``unsold_treatment: "cancel"``. All anchors are asserted
against the closed form with explicit rtol/atol.

Anchor table:

    | V1 | σ=1, E0=100, S=90, F=30  | static: base P=10<F binds; e(F)=70; u=20 |
    | V2 | σ=1, E0=100, S=50, F=30  | static: base P=50>F slack; e(F)=70≥50 |
    | V3 | 3-yr window gating        | window slack (banks) + static cancel |
    | V4 | σ=1, E0=100, S=90, F=10  | static: F = base price; comp. slack |
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from pe.config_io import build_markets_from_config
from pe.engine import solve_banking_path
from pe.features.banking.solver import _is_period_two, _is_static_year
from pe.features.price_controls.rules import FloorCancellationRule

E0 = 100.0  # BAU emissions per year [Mt CO2e]
R = 0.05  # carry rate r [1/yr]
SOLVER_LOGGER = "pe.features.banking.solver"


def _year(
    label: int, supply: float, floor: float, *, sigma: float = 1.0, unsold: str = "cancel"
) -> dict:
    """One hand-solvable single-participant year (linear MAC, no free alloc)."""
    return {
        "year": str(label),
        "total_cap": supply,
        "auction_mode": "derive_from_cap",
        "auction_reserve_price": floor,
        "unsold_treatment": unsold,
        "banking_allowed": True,
        "borrowing_allowed": False,
        "expectation_rule": "next_year_baseline",
        "price_lower_bound": 0.0,
        "price_upper_bound": 100000.0,
        "participants": [
            {
                "name": "Industry",
                "initial_emissions": E0,
                "free_allocation_ratio": 0.0,
                "penalty_price": 0.0,
                "abatement_type": "linear",
                "max_abatement": E0,
                "cost_slope": sigma,
            }
        ],
    }


def _config(years: list[dict], *, r: float = R) -> dict:
    return {
        "scenarios": [
            {
                "name": "floor-cancel-anchor",
                "model_approach": "banking",
                "discount_rate": r,
                "banking_initial_bank": 0.0,
                "years": years,
            }
        ]
    }


def _solve(years: list[dict]) -> list[dict]:
    return solve_banking_path(build_markets_from_config(_config(years)), discount_rate=R)


# ── V1: binding static-year cancellation (the 2-cycle, cured) ────────────────


def test_v1_binding_floor_converges_to_complementarity(caplog: pytest.LogCaptureFixture):
    r"""V1: σ=1, E0=100, S=90, F=30. Base static price P(90)=10 < F, so the
    floor binds; e(F=30)=70, unsold u = S − e(F) = 20. The FIXED solver reaches
    the complementarity boundary (P=F=30, sold=e(F)=70, cancel 20, circulating
    supply 90 → 70) in ≤2 schedule iterations with no oscillation."""
    with caplog.at_level(logging.DEBUG, logger=SOLVER_LOGGER):
        path = _solve([_year(2030, 90.0, 30.0)])

    (item,) = path
    eq = item["equilibrium"]
    np.testing.assert_allclose(eq["price"], 30.0, rtol=0, atol=1e-6)  # P = F
    np.testing.assert_allclose(eq["auction_sold"], 70.0, rtol=0, atol=1e-6)  # e(F)
    np.testing.assert_allclose(eq["auction_offered"], 90.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(item["banking_floor_cancelled"], 20.0, rtol=0, atol=1e-6)
    # Circulating supply reduced by the cancelled volume: offered − sold = u.
    np.testing.assert_allclose(eq["auction_offered"] - eq["auction_sold"], 20.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(item["banking_aggregate_bank"], 0.0, rtol=0, atol=1e-6)

    # ≤2 schedule iterations (exact) and NO non-convergence fallback.
    iters = [rec for rec in caplog.records if "supply-rule iteration" in rec.message]
    assert len(iters) <= 2
    assert not any("did not converge" in rec.message for rec in caplog.records)
    assert not any("oscillates with period 2" in rec.message for rec in caplog.records)


def test_v1_pre_fix_predicate_would_2_cycle():
    r"""The pre-fix map 2-cycles; the fixed rule does not. At the HIGH-price
    phase of the pre-fix orbit the year's price equals F while the base supply
    is still oversupplied at the floor (S=90 > e(F)=70). The FIXED rule cancels
    there — its decision is on FIXED quantities (e(F) < S), price-independent —
    returning (e(F)=70, u=20). The superseded ``floor > solved_price`` predicate
    would evaluate ``30 > 30`` = False and NOT cancel, returning (90, 0): the
    flip that withdraws cancellation, collapses the price below the floor, and
    re-cancels — the period-2 supply orbit. This assertion is constructed to
    FAIL on the old predicate (which yields (90.0, 0.0))."""
    market = build_markets_from_config(_config([_year(2030, 90.0, 30.0)]))[0]
    supply, cancelled = FloorCancellationRule().apply_to_year(
        market, solved_price=30.0, supply=90.0
    )
    np.testing.assert_allclose(supply, 70.0, rtol=0, atol=1e-6)  # e(F), not base 90
    np.testing.assert_allclose(cancelled, 20.0, rtol=0, atol=1e-6)  # u, not 0

    # And the LOW-price phase (price < F) agrees old==new (both cancel): the
    # discontinuity is precisely at the equilibrium P = F, which the fixed test
    # solves on its boundary rather than across it.
    supply_low, cancelled_low = FloorCancellationRule().apply_to_year(
        market, solved_price=10.0, supply=90.0
    )
    np.testing.assert_allclose(supply_low, 70.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(cancelled_low, 20.0, rtol=0, atol=1e-6)


# ── V2: non-binding inertness (the slack path is untouched) ──────────────────


def test_v2_non_binding_floor_never_cancels():
    r"""V2: σ=1, E0=100, S=50, F=30. Base static price P(50)=50 > F, so the
    floor is slack: e(F=30)=70 ≥ S=50, the contemporaneous test does not fire,
    and nothing is cancelled (the slack path is bit-identical to no floor)."""
    (item,) = _solve([_year(2030, 50.0, 30.0)])
    eq = item["equilibrium"]
    np.testing.assert_allclose(eq["price"], 50.0, rtol=0, atol=1e-6)  # P(S) = σ(E0 − S)
    np.testing.assert_allclose(item["banking_floor_cancelled"], 0.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(eq["auction_sold"], 50.0, rtol=0, atol=1e-6)


# ── V3: window gating (cancel the STATIC year only) ──────────────────────────
#
# A REAL multi-year window plus a SEPARATE static year needs ≥3 years: a
# single-year "window" (a == b) has no intertemporal arbitrage and is itself
# static-regime. So the spec's 2-year intent is realised with 3 years —
# years 0..1 form the banking window [0, 1]; year 2 is the static-oversupplied
# binding-floor year (binds per V1).


def _v3_years() -> list[dict]:
    return [
        _year(2030, 50.0, 55.0),  # in window: e(F=55)=45 < S=50 would fire, but GATED
        _year(2031, 20.0, 5.0),  # in window: slack floor
        _year(2032, 90.0, 30.0),  # STATIC oversupplied: binds -> cancel 20 (V1)
    ]


def test_v3_gating_cancels_static_year_only():
    r"""V3: window gating. Years 0–1 form the banking window [0, 1]; year 2 is
    static-oversupplied. Cancellation fires ONLY on the static year 2 (P=F=30,
    e(F)=70, u=20). The window years never cancel — including year 0, where the
    local static test e(F=55)=45 < base S=50 WOULD fire but is gated off because
    P_0 ≥ F_0 holds by intertemporal arbitrage (surplus banks)."""
    y0, y1, y2 = _solve(_v3_years())

    # Static year 2: cancels to the complementarity boundary.
    assert y2["banking_regime"] == "static"
    np.testing.assert_allclose(y2["equilibrium"]["price"], 30.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(y2["equilibrium"]["auction_sold"], 70.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(y2["banking_floor_cancelled"], 20.0, rtol=0, atol=1e-6)

    # Window years 0, 1: NO cancellation despite year 0's local static test.
    assert y0["banking_regime"] == "hotelling"
    assert y1["banking_regime"] == "hotelling"
    np.testing.assert_allclose(y0["banking_floor_cancelled"], 0.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(y1["banking_floor_cancelled"], 0.0, rtol=0, atol=1e-12)
    assert y0["equilibrium"]["price"] > 55.0  # P_0 above its floor (arbitrage)


def test_v3_year0_rule_fires_in_isolation_so_the_host_gate_is_load_bearing():
    r"""The window exemption is the HOST's job, not the rule's: year 0's floor
    DOES satisfy the rule's local test (e(F=55)=45 < base circulating supply
    50), so the rule cancels 5 Mt when called directly. The path shows u_0 = 0
    only because ``_supply_schedule`` withholds the call for a window year the
    floor does not clip (F_0=55 < P_0≈63.4, so the surplus banks) — remove that
    gate and V3 would wrongly cancel year 0."""
    markets = build_markets_from_config(_config(_v3_years()))
    market0 = next(m for m in markets if str(m.year) == "2030")
    supply, cancelled = FloorCancellationRule().apply_to_year(
        market0, solved_price=0.0, supply=50.0
    )
    np.testing.assert_allclose(supply, 45.0, rtol=0, atol=1e-6)  # e(F=55)
    np.testing.assert_allclose(cancelled, 5.0, rtol=0, atol=1e-6)


# ── V4: boundary regression (F = base price) ─────────────────────────────────


def test_v4_floor_at_base_price_is_complementary_slack(caplog: pytest.LogCaptureFixture):
    r"""V4: σ=1, E0=100, S=90, F=10 = the base static price. Here e(F=10)=90 =
    S exactly, so the strict ``e(F) < S`` test does NOT fire (complementary
    slackness at the boundary): no cancellation, P = F = 10, u = 0 — and stable,
    no orbit (the pre-fix strict-``>`` edge is what this regresses)."""
    with caplog.at_level(logging.DEBUG, logger=SOLVER_LOGGER):
        (item,) = _solve([_year(2030, 90.0, 10.0)])

    eq = item["equilibrium"]
    np.testing.assert_allclose(eq["price"], 10.0, rtol=0, atol=1e-6)  # P = F = base
    np.testing.assert_allclose(item["banking_floor_cancelled"], 0.0, rtol=0, atol=1e-12)
    np.testing.assert_allclose(eq["auction_sold"], 90.0, rtol=0, atol=1e-6)
    assert not any("oscillates with period 2" in rec.message for rec in caplog.records)
    assert not any("did not converge" in rec.message for rec in caplog.records)


# ── Host gating + guard helpers (unit) ───────────────────────────────────────


def test_is_static_year_treats_degenerate_and_out_of_window_as_static():
    """A degenerate single-year window (a == b) has no arbitrage → static; a
    multi-year window (b > a) marks only its members window-regime."""
    assert _is_static_year(0, None) is True  # pure static path
    assert _is_static_year(0, (0, 0)) is True  # degenerate single-year window (V1)
    assert _is_static_year(1, (0, 2)) is False  # inside a multi-year window
    assert _is_static_year(0, (0, 2)) is False
    assert _is_static_year(2, (0, 2)) is False
    assert _is_static_year(3, (0, 2)) is True  # outside the window (V3 static year)


def test_is_period_two_detects_only_a_genuine_orbit():
    """Period-2 signature: back at the 2-ago iterate while bouncing off 1-ago."""
    tol = 1e-6
    # Clean 90 <-> 70 orbit: S_k == S_{k-2} != S_{k-1}.
    assert _is_period_two([70.0], [90.0], [70.0], tol) is True
    # Converging monotonically: not an orbit.
    assert _is_period_two([70.0], [70.0], [90.0], tol) is False
    # Already converged (all within tol): not an orbit.
    assert _is_period_two([70.0], [70.0], [70.0], tol) is False


def test_period_two_guard_takes_the_complementarity_solution(monkeypatch):
    r"""Defensive guard (spec §2 SECONDARY): the direct solve makes a real
    single-market orbit unreachable, so we drive ``solve_banking_path`` onto a
    synthetic 90 ⇄ 70 supply orbit by monkeypatching ``_supply_schedule`` to
    alternate. The guard must detect period-2, take the COMPLEMENTARITY
    solution (the max-cancellation phase, supply 70 = e(F)), warn, and stop —
    never an arbitrary last iterate (which could be 90)."""
    import pe.features.banking.solver as solver_mod

    calls = {"n": 0}
    orbit = [[70.0], [90.0], [70.0], [90.0], [70.0], [90.0]]

    def _fake_schedule(markets, prices, bank, initial_bank, factories, floor_factory, window):
        supplies = list(orbit[calls["n"] % len(orbit)])
        calls["n"] += 1
        diags = [
            {
                "msr_withheld": 0.0,
                "msr_released": 0.0,
                "msr_pool": 0.0,
                "floor_unsold_cancelled": 90.0 - supplies[0],
            }
        ]
        return supplies, diags

    monkeypatch.setattr(solver_mod, "_supply_schedule", _fake_schedule)

    caplog_records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = caplog_records.append  # type: ignore[method-assign]
    solver_mod.logger.addHandler(handler)
    try:
        (item,) = _solve([_year(2030, 90.0, 30.0)])
    finally:
        solver_mod.logger.removeHandler(handler)

    # Landed on the complementarity (fully-cancelled) phase: supply 70 = e(F),
    # so the delivered price is the floor and the cancelled diag is 20.
    np.testing.assert_allclose(item["banking_floor_cancelled"], 20.0, rtol=0, atol=1e-6)
    assert any("oscillates with period 2" in rec.getMessage() for rec in caplog_records)
