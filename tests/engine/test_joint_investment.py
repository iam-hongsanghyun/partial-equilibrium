r"""D2-5: endogenous investment nested INSIDE a cyclic SCC (V-D2-4).

The MIDDLE (per-market adoption) loop runs against CURRENT neighbor prices on
every OUTER (joint SCC price) sweep, with the adoption state carried across
sweeps as a MONOTONE floor (``docs/joint-equilibrium.md`` §4). Exercised
end-to-end through the real dispatch entry ``run_simulation_from_config``
(``engine.dispatch._solve_cyclic_scc`` → the injected ``_solve_scc_member``
closure → ``feedback.solve_with_investment_feedback``); ``tests/engine/
test_joint_dispatch.py`` covers the joint loop without investment and
``tests/engine/test_investment_feedback.py`` covers Phase-1 investment
standalone.

Hand anchor — two symmetric THRESHOLD markets A<->B, each firm carrying a base
abatement block at cost ``H`` and a FLAGGED cheaper option block at cost ``L``.
A ``mac_cost`` link in each direction shifts BOTH blocks' cost by ``phi·P``, so
each interior market pins at its marginal block's (shifted) threshold ⇒ own-price
pass-through ``s_m = 1`` (the J1 construction). Two closed-form joint fixed
points bracket the adoption channel:

    UN-ADOPTED (option masked / removed):  P0 = H / (1 - phi)   [both markets]
    ADOPTED    (option available):         P* = L / (1 - phi)   [both markets]

with ``H = 100, L = 40, phi = 0.4`` ⇒ ``P0 = 166.666..., P* = 66.666...``.

Adoption boundary (``trigger_mode="break_even"`` ⇒ M = 1, so the trigger is θ
exactly). On the FIRST sweep market A is solved with its cycle-closing back-link
CUT (the V-D2-1 seed), so A's un-adopted seed price is exactly ``H``:

    theta <= H            : A adopts on sweep 1 from its OWN seed price H
                            (not neighbor-driven).
    H < theta < P0        : A does NOT cross on sweep 1 (seed H < theta); it
                            adopts on a LATER sweep, DRIVEN by the neighbour's
                            price feeding in through the back-link — the genuine
                            cyclic-adoption witness the floor must carry.
    theta > P0            : A's price never reaches theta ⇒ never adopts.

At ``P* = 66.67 < theta`` the entrant DEPRESSES the joint price below its own
trigger — ex-post regret, permitted (§4 (ii)); the option stays adopted ONLY
because the floor forbids the un-adopt (without it: adopt→price drops below
theta→un-adopt→price rises→adopt→… the discrete-flip oscillation the floor
kills).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import pe.engine.dispatch as dispatch
from pe.core.protocols import parse_adoption_state
from pe.engine import run_simulation_from_config

# ── Anchor constants ─────────────────────────────────────────────────────────
H = 100.0  # base block threshold cost [USD/tCO2]
L = 40.0  # flagged option block threshold cost [USD/tCO2] (L < H)
PHI = 0.4  # mac_cost link coefficient, each direction [dimensionless]
P0 = H / (1.0 - PHI)  # un-adopted joint fixed point  = 166.666...  [USD/tCO2]
PSTAR = L / (1.0 - PHI)  # adopted joint fixed point   =  66.666...  [USD/tCO2]

PRICE_ATOL = 1e-6
JOINT_COLUMNS = (
    "Joint Converged",
    "Joint Outer Iterations",
    "Joint Max Normalized Change",
    "Joint Cycle Detected",
)
INVESTMENT_COLUMNS = (
    "Investment Adoptions",
    "Investment Newly Effective",
    "Investment Feedback Iterations",
    "Investment Converged",
)


# ── Scenario builders (in-code config, no example files) ──────────────────────


def _participant(
    firm: str, base_blk: str, opt_blk: str, theta: float, with_opt: bool
) -> dict[str, Any]:
    """One firm: a base threshold block, plus (optionally) a FLAGGED cheaper block."""
    options: list[dict[str, Any]] = [
        {
            "name": base_blk,
            "abatement_type": "threshold",
            "threshold_cost": H,
            "initial_emissions": 100.0,
            "max_abatement": 40.0,
            "free_allocation_ratio": 0.0,
            "penalty_price": 100000.0,
            "max_activity_share": 1.0,
        }
    ]
    if with_opt:
        options.append(
            {
                "name": opt_blk,
                "abatement_type": "threshold",
                "threshold_cost": L,
                "initial_emissions": 100.0,
                "max_abatement": 40.0,
                "free_allocation_ratio": 0.0,
                "penalty_price": 100000.0,
                "max_activity_share": 1.0,
                "investment_trigger": {
                    "break_even_price": theta,  # M = 1 in break_even mode
                    "payout_yield": 0.03,
                    "trigger_mode": "break_even",
                },
            }
        )
    return {
        "name": firm,
        "initial_emissions": 100.0,
        "free_allocation_ratio": 0.0,
        "penalty_price": 100000.0,
        "abatement_type": "threshold",
        "threshold_cost": 999.0,  # placeholder base MAC (no abatement); blocks do the work
        "max_abatement": 0.0,
        "technology_options": options,
    }


def _market(
    mid: str, firm: str, base_blk: str, opt_blk: str, theta: float, with_opt: bool
) -> dict[str, Any]:
    """One interior single-year threshold market (E0 - block = 60 < S = 80 < E0 = 100)."""
    return {
        "market_id": mid,
        "price_unit": "USD/tCO2",
        "model_approach": "competitive",
        "discount_rate": 0.055,
        # Scenario-level flags live per market body in the multi-market shape.
        "investment_feedback_enabled": with_opt,
        "years": [
            {
                "year": "2030",
                "total_cap": 80.0,
                "auction_mode": "explicit",
                "auction_offered": 80.0,
                "price_upper_bound": 100000.0,
                "participants": [_participant(firm, base_blk, opt_blk, theta, with_opt)],
            }
        ],
    }


def _mac_link(
    frm: str, to: str, firm: str, base_blk: str, opt_blk: str, with_opt: bool
) -> dict[str, Any]:
    """A mac_cost link shifting BOTH the target firm's blocks by phi·P_source."""
    techs = [base_blk] + ([opt_blk] if with_opt else [])
    return {
        "from_market": frm,
        "to_market": to,
        "channel": "mac_cost",
        "phi": PHI,
        "phi_unit": "1/1",
        "target_participants": [firm],
        "target_technologies": techs,
    }


def _cyclic_config(theta: float, with_opt: bool = True) -> dict[str, Any]:
    """A<->B cyclic SCC; ``with_opt=False`` removes the option (investment-disabled)."""
    a = _market("A", "A_firm", "baseA", "optA", theta, with_opt)
    b = _market("B", "B_firm", "baseB", "optB", theta, with_opt)
    return {
        "scenarios": [
            {
                "name": "cyc",
                "markets": [a, b],
                "links": [
                    _mac_link("B", "A", "A_firm", "baseA", "optA", with_opt),  # P_B -> A
                    _mac_link("A", "B", "B_firm", "baseB", "optB", with_opt),  # P_A -> B
                ],
                "joint_solver": {"tolerance": 1e-12, "max_iterations": 200},
            }
        ]
    }


def _price(summary: Any, scenario_key: str) -> float:
    rows = summary[summary["Scenario"] == scenario_key]
    return float(rows["Equilibrium Carbon Price"].iloc[0])


def _adoption_pairs(summary: Any, scenario_key: str) -> frozenset[tuple[str, str]]:
    rows = summary[summary["Scenario"] == scenario_key]
    state = parse_adoption_state(str(rows["Investment Adoptions"].iloc[0]))
    return frozenset((e.participant_name, e.technology_name) for e in state)


# ── (a) + (c): converges with investment active, and investment BITES ─────────


def test_cyclic_investment_converges_and_bites() -> None:
    """theta = 90 (< H): both firms adopt; the joint loop converges to P* with
    Joint Converged = 1, and the fixed point DIFFERS from the same SCC with
    investment disabled (P0) — investment bites."""
    on, _ = run_simulation_from_config(_cyclic_config(90.0, with_opt=True))

    # Both cyclic rows converged (never a faked equilibrium).
    for column in JOINT_COLUMNS:
        assert column in on.columns, f"missing guarded column {column!r}"
    assert all(on["Joint Converged"] == 1.0)
    assert all(on["Joint Cycle Detected"] == 0.0)

    # Converged WITH investment == the adopted hand fixed point P* (both markets).
    np.testing.assert_allclose(_price(on, "cyc :: A"), PSTAR, rtol=0.0, atol=PRICE_ATOL)
    np.testing.assert_allclose(_price(on, "cyc :: B"), PSTAR, rtol=0.0, atol=PRICE_ATOL)

    # Both options adopted, and the converged price sits BELOW the trigger — the
    # entrant depressed the joint price under its own hurdle (ex-post regret,
    # §4 (ii)); the floor is what keeps it adopted rather than oscillating.
    assert _adoption_pairs(on, "cyc :: A") == {("A_firm", "optA")}
    assert _adoption_pairs(on, "cyc :: B") == {("B_firm", "optB")}
    assert PSTAR < 90.0

    # Investment DISABLED (option removed) == the un-adopted hand fixed point P0.
    off, _ = run_simulation_from_config(_cyclic_config(90.0, with_opt=False))
    np.testing.assert_allclose(_price(off, "cyc :: A"), P0, rtol=0.0, atol=PRICE_ATOL)
    np.testing.assert_allclose(_price(off, "cyc :: B"), P0, rtol=0.0, atol=PRICE_ATOL)

    # The bite: the joint fixed point moved (P* != P0).
    assert abs(_price(on, "cyc :: A") - _price(off, "cyc :: A")) > 1.0
    assert INVESTMENT_COLUMNS[0] not in off.columns  # disabled path: no investment cols


# ── (b): adoption is MONOTONE across outer sweeps (the floor carry) ───────────


def _record_per_sweep_floor(config: dict[str, Any]) -> tuple[Any, dict[str, list[frozenset]]]:
    """Solve ``config`` while recording each SCC member's final adoption state per
    ``_solve_scc_member`` call (one call per market per outer sweep, plus the
    reporting re-solve), keyed by market id in call order."""
    calls: dict[str, list[frozenset[tuple[str, str]]]] = {}
    floor_in: dict[str, list[frozenset[tuple[str, str]]]] = {}
    original = dispatch._solve_scc_member

    def _spy(market_id, composite, bodies_by_id, links, delivered_paths, *, adoption_floor=None):
        ordered, path, final_state = original(
            market_id,
            composite,
            bodies_by_id,
            links,
            delivered_paths,
            adoption_floor=adoption_floor,
        )
        pairs = frozenset((e.participant_name, e.technology_name) for e in final_state)
        calls.setdefault(market_id, []).append(pairs)
        seeded = frozenset((e.participant_name, e.technology_name) for e in (adoption_floor or ()))
        floor_in.setdefault(market_id, []).append(seeded)
        return ordered, path, final_state

    dispatch._solve_scc_member = _spy  # type: ignore[assignment]
    try:
        summary, _ = run_simulation_from_config(config)
    finally:
        dispatch._solve_scc_member = original
    # Per-call superset invariant: each sweep's converged state contains the floor
    # it was seeded with (the middle loop can only ADD above the floor).
    for market_id, outs in calls.items():
        for seeded, out in zip(floor_in[market_id], outs, strict=True):
            assert seeded <= out, f"{market_id}: middle loop dropped a seeded adoption"
    return summary, calls


def test_adoption_floor_monotone_across_outer_sweeps() -> None:
    """theta = 130 (H < theta < P0): A does NOT adopt on sweep 1 (seed H = 100 <
    130) but adopts on a LATER sweep once the neighbour's price feeds in — the
    genuine cyclic-adoption witness. Across every outer sweep the per-market
    adoption floor is MONOTONE non-decreasing (never un-adopts), the loop
    converges (Joint Converged = 1), and the fixed point is the adopted P*."""
    summary, calls = _record_per_sweep_floor(_cyclic_config(130.0, with_opt=True))

    assert all(summary["Joint Converged"] == 1.0)
    np.testing.assert_allclose(_price(summary, "cyc :: A"), PSTAR, rtol=0.0, atol=PRICE_ATOL)
    np.testing.assert_allclose(_price(summary, "cyc :: B"), PSTAR, rtol=0.0, atol=PRICE_ATOL)

    # Monotone across sweeps for BOTH members (the adoption-as-outer-FLOOR
    # invariant): the adopted set only ever grows.
    for market_id, seq in calls.items():
        for earlier, later in zip(seq, seq[1:], strict=False):
            assert earlier <= later, f"{market_id}: adoption floor SHRANK across a sweep {seq}"

    # A is DELAYED: empty on sweep 1 (seed H = 100 < theta = 130), then adopts —
    # proof the floor carried a neighbour-driven crossing across outer sweeps.
    a_seq = calls["A"]
    assert a_seq[0] == frozenset(), "A adopted on sweep 1 despite seed H < theta"
    assert a_seq[-1] == {("A_firm", "optA")}, "A never adopted"
    assert any(a_seq[i] == frozenset() and a_seq[i + 1] for i in range(len(a_seq) - 1))


# ── (d): adoption-boundary straddle (closed-form) ─────────────────────────────


@pytest.mark.parametrize(
    ("theta", "expected_price", "adopts"),
    [
        (90.0, PSTAR, True),  # theta < H (=100): A adopts on sweep 1 from seed H
        (200.0, P0, False),  # theta > P0 (=166.67): A never reaches theta
    ],
)
def test_adoption_boundary_straddle(theta: float, expected_price: float, adopts: bool) -> None:
    """The joint-with-investment fixed point straddles the adoption boundary: for
    theta below the crossing the SCC converges to the adopted P*, for theta above
    P0 it converges to the un-adopted P0 with no adoption — both closed-form, both
    Joint Converged = 1 (a non-adopting SCC is still a genuine equilibrium)."""
    summary, _ = run_simulation_from_config(_cyclic_config(theta, with_opt=True))
    assert all(summary["Joint Converged"] == 1.0)
    for key in ("cyc :: A", "cyc :: B"):
        np.testing.assert_allclose(_price(summary, key), expected_price, rtol=0.0, atol=PRICE_ATOL)
        pairs = _adoption_pairs(summary, key)
        assert bool(pairs) is adopts


# ── control: acyclic investment is byte-identical to Phase 1 (inertness) ──────


def test_acyclic_investment_byte_identical_to_phase1() -> None:
    """INERTNESS WITNESS: a one-way (acyclic) A->B scenario carrying investment on
    the SOURCE market A (which has NO inbound link, so it solves independently)
    reproduces the standalone single-market Phase-1 solve of A bit-for-bit — the
    cyclic nesting never perturbs the acyclic investment path (which routes
    through the untouched ``_solve_market_leg``, not ``_solve_scc_member``)."""
    a = _market("A", "A_firm", "baseA", "optA", 90.0, with_opt=True)
    b = _market("B", "B_firm", "baseB", "optB", 90.0, with_opt=True)
    acyclic = {
        "scenarios": [
            {
                "name": "way",
                "markets": [a, b],
                "links": [
                    _mac_link("A", "B", "B_firm", "baseB", "optB", with_opt=True)
                ],  # A->B only
            }
        ]
    }
    multi, _ = run_simulation_from_config(acyclic)

    # A as its own single-market scenario (the Phase-1 reference), under the same
    # composite grouping key the multi-market path uses.
    single_body = {k: v for k, v in a.items() if k != "market_id"}
    standalone, _ = run_simulation_from_config(
        {"scenarios": [{"name": "way :: A", **single_body, "policy_events": []}]}
    )

    multi_a = multi[multi["Scenario"] == "way :: A"].reset_index(drop=True)
    for column in INVESTMENT_COLUMNS:
        assert str(multi_a[column].iloc[0]) == str(standalone[column].iloc[0]), (
            f"acyclic investment differs from Phase 1 on {column!r}"
        )
    np.testing.assert_allclose(
        float(multi_a["Equilibrium Carbon Price"].iloc[0]),
        float(standalone["Equilibrium Carbon Price"].iloc[0]),
        rtol=0.0,
        atol=0.0,  # byte-identical: A has no inbound link, so its solve is unchanged
    )
    # And the acyclic path carries NO Joint columns (the cyclic branch never ran).
    for column in JOINT_COLUMNS:
        assert column not in multi.columns
