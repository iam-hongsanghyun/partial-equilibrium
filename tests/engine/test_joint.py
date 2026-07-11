r"""Joint-equilibrium outer loop (D2-2): the J1/J2 hand-solvable anchors.

Covers ``pe.engine.joint.solve_joint_scc`` against the closed-form 2-market
anchors of ``docs/joint-equilibrium.md`` (table J1-J6). The injected solver is a
synthetic linear-MAC 2-market model: each market clears at its shifted intercept
so the own-price pass-through is ``s_m = 1`` and the mac_cost channel shifts the
baseline by ``phi * (neighbour price)``. With ``s_m = 1`` the 2-cycle loop gain
is ``g = s_A s_B phi_AB phi_BA = phi_AB phi_BA`` and the linear 2x2 fixed point is

    P_A = (alpha_A + phi_AB * alpha_B) / (1 - g)
    P_B = (alpha_B + phi_BA * alpha_A) / (1 - g)

(``docs/joint-equilibrium.md`` §7), which the tests assert to atol 1e-6.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pytest

from pe.core.protocols import LinkSpec
from pe.engine.joint import JOINT_DEFAULTS, JointResult, solve_joint_scc

YEAR = "2030"


def _link(from_market: str, to_market: str, phi: float) -> LinkSpec:
    return LinkSpec(
        from_market=from_market,
        to_market=to_market,
        channel="mac_cost",
        phi=phi,
        phi_unit="KRW/tCO2 per KRW/tCO2",
        target_participants=("*",),
        target_technologies=("t",),
    )


def _linear_mac_solver(
    alpha: Mapping[str, float], phi: Mapping[tuple[str, str], float]
) -> Callable[[str, Mapping[str, Mapping[str, float]]], Mapping[str, float]]:
    r"""Synthetic linear-MAC solver: P_m = alpha_m + sum_n phi[(m, n)] * P_n.

    ``phi[(m, n)]`` is the coefficient on neighbour n's price INTO market m — a
    market m with ``s_m = 1`` sits exactly at its shifted intercept, so a single
    solved year is ``P_m(t) = alpha_m + sum over neighbours n of phi[(m,n)] *
    P_n(t)`` (the coupling shifts market m's baseline by ``phi * (neighbour
    price)``). This is the D2-3 injection point stood in for by a hand-solvable
    model; the real dispatch closure lands there in D2-3.
    """

    def solve_one_market(
        market_id: str, delivered_paths: Mapping[str, Mapping[str, float]]
    ) -> Mapping[str, float]:
        total = alpha[market_id]
        for (m, n), coeff in phi.items():
            if m == market_id:
                total += coeff * delivered_paths.get(n, {}).get(YEAR, 0.0)
        return {YEAR: total}

    return solve_one_market


# ── J1: converging 2-market cycle, g = 0.2 ───────────────────────────────────
# alpha_A = 100, alpha_B = 80, phi_AB = 0.4, phi_BA = 0.5 => g = 0.2.
# Hand fixed point: P_A = (100 + 0.4*80)/0.8 = 165.0, P_B = (80 + 0.5*100)/0.8 = 162.5.
J1_ALPHA = {"A": 100.0, "B": 80.0}
J1_PHI = {("A", "B"): 0.4, ("B", "A"): 0.5}
J1_LINKS = [_link("B", "A", 0.4), _link("A", "B", 0.5)]  # B->A carries phi_AB into A, etc.


def test_j1_converges_to_hand_fixed_point() -> None:
    """J1: the outer loop converges to the exact hand values (atol 1e-6)."""
    solver = _linear_mac_solver(J1_ALPHA, J1_PHI)
    result = solve_joint_scc(
        ["A", "B"],
        solver,
        links=J1_LINKS,
        relaxation=0.5,  # the w = 0.5 default (asserted below)
        tolerance=1e-13,  # tight so the STOPPED value matches the hand value
        max_iterations=500,
    )

    assert result.converged is True
    np.testing.assert_allclose(result.market_paths["A"][YEAR], 165.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result.market_paths["B"][YEAR], 162.5, rtol=0.0, atol=1e-6)
    assert result.cycle_period == 0
    assert result.report_columns()["Joint Converged"] == 1.0


def test_j1_requires_more_than_one_sweep() -> None:
    """J1: a single Gauss-Seidel sweep does NOT reach the fixed point."""
    solver = _linear_mac_solver(J1_ALPHA, J1_PHI)

    # One sweep only: not converged, and the iterate is the one-way seed (100, 130),
    # far from the (165, 162.5) fixed point.
    one = solve_joint_scc(["A", "B"], solver, links=J1_LINKS, relaxation=0.5, max_iterations=1)
    assert one.converged is False
    assert one.outer_iterations == 1
    np.testing.assert_allclose(one.market_paths["A"][YEAR], 100.0, rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(one.market_paths["B"][YEAR], 130.0, rtol=0.0, atol=1e-9)

    # Allowed to iterate: convergence needs strictly MORE than one sweep.
    full = solve_joint_scc(
        ["A", "B"], solver, links=J1_LINKS, relaxation=0.5, tolerance=1e-13, max_iterations=500
    )
    assert full.converged is True
    assert full.outer_iterations >= 2


def test_j1_default_relaxation_is_half() -> None:
    """The module default relaxation weight is w = 0.5 (§3, V-D2-5)."""
    assert JOINT_DEFAULTS["relaxation"] == 0.5
    solver = _linear_mac_solver(J1_ALPHA, J1_PHI)
    # relaxation=None resolves to the default and still lands on the fixed point.
    result = solve_joint_scc(
        ["A", "B"], solver, links=J1_LINKS, relaxation=None, tolerance=1e-13, max_iterations=500
    )
    assert result.converged is True
    np.testing.assert_allclose(result.market_paths["A"][YEAR], 165.0, rtol=0.0, atol=1e-6)


# ── J2: oscillation boundary, g = -1.5 ───────────────────────────────────────
# phi_AB = -0.5, phi_BA = 3.0 => g = -1.5. alpha_A = alpha_B = 100.
# Hand fixed point: P_A = (100 - 0.5*100)/2.5 = 20.0, P_B = (100 + 3*100)/2.5 = 160.0.
# The relaxed-Gauss-Seidel iteration matrix is upper-triangular with eigenvalues
# (1 - w) and (1 - w) + w*g; at w = 0.5 the coupled eigenvalue is -0.25 (converges),
# at w = 1 it is g = -1.5 (diverging period-2 oscillation).
J2_ALPHA = {"A": 100.0, "B": 100.0}
J2_PHI = {("A", "B"): -0.5, ("B", "A"): 3.0}
J2_LINKS = [_link("B", "A", -0.5), _link("A", "B", 3.0)]


def test_j2_undamped_oscillates_and_is_flagged() -> None:
    """J2 at w = 1: eigenvalue -1.5 => NOT converged AND Joint Cycle Detected = 2."""
    solver = _linear_mac_solver(J2_ALPHA, J2_PHI)
    result = solve_joint_scc(
        ["A", "B"], solver, links=J2_LINKS, relaxation=1.0, tolerance=1e-9, max_iterations=60
    )

    assert result.converged is False
    assert result.cycle_period == 2  # period exactly 2
    cols = result.report_columns()
    assert cols["Joint Converged"] == 0.0
    assert cols["Joint Cycle Detected"] == 2.0


def test_j2_damping_recovers_the_fixed_point() -> None:
    """J2 at w = 0.5: eigenvalue -0.25 => converges to the hand fixed point."""
    solver = _linear_mac_solver(J2_ALPHA, J2_PHI)
    result = solve_joint_scc(
        ["A", "B"], solver, links=J2_LINKS, relaxation=0.5, tolerance=1e-13, max_iterations=500
    )

    assert result.converged is True
    assert result.cycle_period == 0
    np.testing.assert_allclose(result.market_paths["A"][YEAR], 20.0, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result.market_paths["B"][YEAR], 160.0, rtol=0.0, atol=1e-6)


def test_j2_damping_is_the_remedy_not_iterations() -> None:
    """Same coupling: w = 1 fails (cycle), w = 0.5 succeeds — damping is the fix."""
    solver = _linear_mac_solver(J2_ALPHA, J2_PHI)
    undamped = solve_joint_scc(
        ["A", "B"], solver, links=J2_LINKS, relaxation=1.0, tolerance=1e-13, max_iterations=500
    )
    damped = solve_joint_scc(
        ["A", "B"], solver, links=J2_LINKS, relaxation=0.5, tolerance=1e-13, max_iterations=500
    )
    # More iterations at w = 1 does NOT rescue an oscillation; damping does.
    assert undamped.converged is False and undamped.cycle_period == 2
    assert damped.converged is True and damped.cycle_period == 0


# ── §3a witness: converges WITH alternation in the folding band -1 < λ < -1/2 ──
# w = 1 (undamped GS), phi_AB = -0.7, phi_BA = 1.0 => loop gain g = -0.7. With
# w = 1 the coupled Gauss-Seidel eigenvalue IS g = -0.7 (the other is 1-w = 0),
# so the iterate ALTERNATES (folds: -0.7 < -1/2) yet CONVERGES (|-0.7| < 1).
# Hand fixed point (alpha_A = alpha_B = 100):
#   P_A = (100 + (-0.7)*100)/(1 - (-0.7)) = 30/1.7,
#   P_B = (100 +   1.0 *100)/(1 - (-0.7)) = 200/1.7.
# This is the RATIFICATION WITNESS (docs/joint-equilibrium.md §3a conditions 1&2):
# the folding predicate fires every descent sweep, so D2-2's early break on
# fold_run>=2 would have wrongly stamped Converged=0 here. The terminal
# derivation must return converged=True, cycle_period=0 (no latch). The existing
# J2-at-w=0.5 (eigenvalue -0.25) sits in the NON-folding zone (-0.25 > -1/2) and
# does NOT exercise this band.
LAMBDA_FOLD_ALPHA = {"A": 100.0, "B": 100.0}
LAMBDA_FOLD_PHI = {("A", "B"): -0.7, ("B", "A"): 1.0}
LAMBDA_FOLD_LINKS = [_link("B", "A", -0.7), _link("A", "B", 1.0)]


def test_converging_alternation_in_folding_band_reports_no_cycle() -> None:
    """-1 < λ = -0.7 < -1/2: folds every sweep yet converges => cycle_period 0."""
    solver = _linear_mac_solver(LAMBDA_FOLD_ALPHA, LAMBDA_FOLD_PHI)
    result = solve_joint_scc(
        ["A", "B"],
        solver,
        links=LAMBDA_FOLD_LINKS,
        relaxation=1.0,  # undamped: the coupled eigenvalue is exactly g = -0.7
        tolerance=1e-12,
        max_iterations=400,
    )

    # Conditions 1 & 2: a folding-but-converging run is NOT a reportable cycle.
    assert result.converged is True
    assert result.cycle_period == 0
    assert result.report_columns()["Joint Cycle Detected"] == 0.0
    # It genuinely ALTERNATED its way there (many sweeps), not a one-shot solve —
    # this is what makes it the witness for the removed early break.
    assert result.outer_iterations >= 3
    # And it reached the exact hand fixed point (a true convergence).
    np.testing.assert_allclose(result.market_paths["A"][YEAR], 30.0 / 1.7, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(result.market_paths["B"][YEAR], 200.0 / 1.7, rtol=0.0, atol=1e-6)


# ── J3-flavoured: inert cycle edge collapses to the recursive (D1) answer ─────
def test_inert_back_edge_seeded_converges_in_one_iteration() -> None:
    """phi_AB = 0 (B->A inert): seeded with the exact answer, converges in 1 sweep.

    The J3 anchor's spirit: a structurally-present but inert cycle edge makes the
    system recursive, so the D1 one-way seed IS the answer and one sweep suffices
    (``Joint Outer Iterations == 1``).
    """
    alpha = {"A": 100.0, "B": 80.0}
    phi = {("A", "B"): 0.0, ("B", "A"): 0.5}  # A independent of B; B = 80 + 0.5*A
    solver = _linear_mac_solver(alpha, phi)
    exact = {"A": {YEAR: 100.0}, "B": {YEAR: 130.0}}  # A=100, B=80+0.5*100=130

    result = solve_joint_scc(
        ["A", "B"],
        solver,
        links=[_link("B", "A", 0.0), _link("A", "B", 0.5)],
        relaxation=0.5,
        tolerance=1e-9,
        max_iterations=50,
        initial_guess=exact,
    )
    assert result.converged is True
    assert result.outer_iterations == 1
    np.testing.assert_allclose(result.market_paths["A"][YEAR], 100.0, rtol=0.0, atol=1e-9)
    np.testing.assert_allclose(result.market_paths["B"][YEAR], 130.0, rtol=0.0, atol=1e-9)


# ── validation / reporting ───────────────────────────────────────────────────
@pytest.mark.parametrize("bad_w", [0.0, -0.1, 1.5])
def test_relaxation_bounds_validated(bad_w: float) -> None:
    """w must be in (0, 1] — loud ValueError otherwise."""
    solver = _linear_mac_solver(J1_ALPHA, J1_PHI)
    with pytest.raises(ValueError, match="relaxation"):
        solve_joint_scc(["A", "B"], solver, links=J1_LINKS, relaxation=bad_w)


def test_result_report_columns_shape() -> None:
    """report_columns exposes exactly the four guarded Joint columns."""
    result = JointResult(
        market_paths={"A": {YEAR: 1.0}},
        converged=True,
        outer_iterations=3,
        max_normalized_change=1e-9,
        cycle_period=0,
    )
    cols = result.report_columns()
    assert set(cols) == {
        "Joint Converged",
        "Joint Outer Iterations",
        "Joint Max Normalized Change",
        "Joint Cycle Detected",
    }
    assert cols["Joint Converged"] == 1.0
    assert cols["Joint Outer Iterations"] == 3.0
