r"""D2-3 end-to-end: the joint (cyclic-SCC) engine wired THROUGH dispatch.

Exercises ``pe.engine.solve_multi_market_scenario``'s guarded cyclic branch
(``docs/joint-equilibrium-plan.md`` §5) via the real dispatch entry
``run_simulation_from_config`` — NOT the joint engine in isolation
(``tests/engine/test_joint.py`` covers that). This is an integration test, NOT a
captured golden (the converging + oscillating goldens are D2-6).

Hand anchor (``docs/joint-equilibrium.md`` §7, anchor J1). Two symmetric
THRESHOLD markets A<->B pin at their (mac_cost-shifted) threshold ⇒ own-price
pass-through ``s_m = 1``, so each clears at ``P_m = c_m + phi * P_neighbour``:

    P_A = c_A + phi_A * P_B,   P_B = c_B + phi_B * P_A,   g = phi_A * phi_B.

With c_A = 100, c_B = 80, phi_A = 0.4, phi_B = 0.5 ⇒ g = 0.2 and the linear 2x2
fixed point is P_A = (100 + 0.4*80)/0.8 = 165.0, P_B = (80 + 0.5*100)/0.8 =
162.5 — the exact J1 anchor values, now reached THROUGH the dispatch closure.
Each threshold market is interior (E0 - A_block = 60 < Q = 80 < E0 = 100), so
its clearing price sits AT the shifted threshold (a vertical step-demand at the
threshold for any interior auction).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from pe.engine import run_simulation_from_config

# Anchor constants (J1).
C_A, C_B = 100.0, 80.0
PHI_A, PHI_B = 0.4, 0.5  # phi_A carries P_B into A; phi_B carries P_A into B
P_A_IDEAL = (C_A + PHI_A * C_B) / (1.0 - PHI_A * PHI_B)  # 165.0
P_B_IDEAL = (C_B + PHI_B * C_A) / (1.0 - PHI_A * PHI_B)  # 162.5

PRICE_ATOL = 1e-6
JOINT_COLUMNS = (
    "Joint Converged",
    "Joint Outer Iterations",
    "Joint Max Normalized Change",
    "Joint Cycle Detected",
)


def _threshold_market(
    market_id: str, firm: str, block: str, threshold_cost: float
) -> dict[str, Any]:
    """One interior single-threshold-block market that pins at its (shifted) threshold."""
    return {
        "market_id": market_id,
        "price_unit": "USD/tCO2",
        "years": [
            {
                "year": "2030",
                "total_cap": 80.0,
                "auction_mode": "explicit",
                "auction_offered": 80.0,  # interior: 60 < 80 < 100
                "price_upper_bound": 100000.0,
                "participants": [
                    {
                        "name": firm,
                        "initial_emissions": 100.0,
                        "free_allocation_ratio": 0.0,
                        "penalty_price": 100000.0,
                        "abatement_type": "threshold",
                        "threshold_cost": 999.0,  # unused when a tech option is present
                        "max_abatement": 0.0,
                        "technology_options": [
                            {
                                "name": block,
                                "abatement_type": "threshold",
                                "threshold_cost": threshold_cost,
                                "initial_emissions": 100.0,
                                "max_abatement": 40.0,
                                "free_allocation_ratio": 0.0,
                                "penalty_price": 100000.0,
                                "max_activity_share": 1.0,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _mac_link(
    from_market: str, to_market: str, phi: float, firm: str, block: str
) -> dict[str, Any]:
    return {
        "from_market": from_market,
        "to_market": to_market,
        "channel": "mac_cost",
        "phi": phi,
        "phi_unit": "1/1",
        "target_participants": [firm],
        "target_technologies": [block],
    }


def _cyclic_config() -> dict[str, Any]:
    """A<->B cyclic scenario, tight joint tolerance so prices match to atol 1e-6."""
    a = _threshold_market("A", "A_firm", "blockA", C_A)
    b = _threshold_market("B", "B_firm", "blockB", C_B)
    return {
        "scenarios": [
            {
                "name": "cyc",
                "markets": [a, b],
                "links": [
                    _mac_link("B", "A", PHI_A, "A_firm", "blockA"),  # P_B into A
                    _mac_link("A", "B", PHI_B, "B_firm", "blockB"),  # P_A into B
                ],
                # Exercises the joint_solver config path (Part 4): tighten the
                # tolerance below the 1e-4 default so the STOPPED iterate matches
                # the hand fixed point to atol 1e-6.
                "joint_solver": {"tolerance": 1e-12, "max_iterations": 200},
            }
        ]
    }


def _price(summary: pd.DataFrame, scenario_key: str) -> float:
    rows = summary[summary["Scenario"] == scenario_key]
    return float(rows["Equilibrium Carbon Price"].iloc[0])


def test_cyclic_scenario_solves_through_dispatch_to_hand_fixed_point() -> None:
    """A<->B via run_simulation_from_config converges to the J1 hand values (atol 1e-6)."""
    summary, participants = run_simulation_from_config(_cyclic_config())

    # Both composite keys present (the "{scenario} :: {market_id}" grouping).
    assert set(summary["Scenario"]) == {"cyc :: A", "cyc :: B"}
    assert set(summary["Market"]) == {"A", "B"}

    np.testing.assert_allclose(_price(summary, "cyc :: A"), P_A_IDEAL, rtol=0.0, atol=PRICE_ATOL)
    np.testing.assert_allclose(_price(summary, "cyc :: B"), P_B_IDEAL, rtol=0.0, atol=PRICE_ATOL)
    # Participant frames were produced for both cyclic members.
    assert set(participants["Scenario"]) == {"cyc :: A", "cyc :: B"}


def test_cyclic_rows_carry_all_four_joint_columns_converged() -> None:
    """Every cyclic-SCC row carries the four Joint columns; Joint Converged == 1."""
    summary, _ = run_simulation_from_config(_cyclic_config())

    for column in JOINT_COLUMNS:
        assert column in summary.columns, f"missing guarded column {column!r}"
    # All cyclic rows: converged, no cycle detected, >= 2 outer sweeps (J1 needs
    # more than one sweep to reach the fixed point).
    assert all(summary["Joint Converged"] == 1.0)
    assert all(summary["Joint Cycle Detected"] == 0.0)
    assert all(summary["Joint Outer Iterations"] >= 2.0)


def test_acyclic_control_does_not_carry_joint_columns() -> None:
    """GUARD PROOF: a one-way (acyclic) A->B scenario never gains the Joint columns.

    Same markets, but a SINGLE link A->B (no back-edge) — an all-acyclic
    condensation takes the existing D1 path verbatim, which never stamps the
    Joint columns (key-presence guard). Run as its own config so the columns are
    genuinely absent from the frame, not merely NaN alongside a cyclic sibling.
    """
    a = _threshold_market("A", "A_firm", "blockA", C_A)
    b = _threshold_market("B", "B_firm", "blockB", C_B)
    acyclic = {
        "scenarios": [
            {
                "name": "oneway",
                "markets": [a, b],
                "links": [_mac_link("A", "B", PHI_B, "B_firm", "blockB")],  # A->B only
            }
        ]
    }
    summary, _ = run_simulation_from_config(acyclic)

    # The acyclic path still solves and stamps the D1 Market column...
    assert set(summary["Market"]) == {"A", "B"}
    # ...but NONE of the four Joint columns exist (the cyclic branch never ran).
    for column in JOINT_COLUMNS:
        assert column not in summary.columns
