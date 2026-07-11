r"""The real 121-point market-clearing curve for joint/multi-market dashboard runs.

Closes the last usability gap: a joint (cyclic-SCC) run's market-clearing chart is
the SAME 121-point net-demand curve the flat single-market path draws, sourced from
the solved leg markets ``dispatch`` now surfaces (the link-shifted ``CarbonMarket``
objects at the converged neighbor prices), NOT the old two-point schematic.

Driven end-to-end through ``pe.web.api._build_dashboard_payload`` (the body behind
``POST /api/graph/run`` and ``/api/run``). The cyclic A<->B graph mirrors
``tests/engine/test_joint_dispatch.py``'s J1 anchor (two symmetric interior
threshold markets pinning at their shifted thresholds), so the surfaced curve is
anchored to a hand-checkable joint fixed point:

    P_A = c_A + phi_A * P_B,  P_B = c_B + phi_B * P_A
    c_A=100, c_B=80, phi_A=0.4, phi_B=0.5  =>  P_A=165.0, P_B=162.5

The price bound is 250 (not the anchor test's 100000): still non-binding above the
165.0 anchor, but fine enough that the 121-point grid RESOLVES the link shift — a
coarse 100000-wide grid would sample only p=0 and p>=833, hiding the threshold move
from c_B=80 to c_B+phi_B*P_A=162.5.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pe.web.api import _build_dashboard_payload

# J1 anchor constants (mirror tests/engine/test_joint_dispatch.py).
C_A, C_B = 100.0, 80.0
PHI_A, PHI_B = 0.4, 0.5
P_A_IDEAL = (C_A + PHI_A * C_B) / (1.0 - PHI_A * PHI_B)  # 165.0
P_B_IDEAL = (C_B + PHI_B * C_A) / (1.0 - PHI_A * PHI_B)  # 162.5

# Non-binding above the 165.0 anchor, fine enough for the 121-point grid to resolve
# the c_B=80 -> 162.5 threshold shift.
PRICE_UPPER = 250.0
POINT_COUNT = 121
PRICE_ATOL = 1e-6


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
                "price_upper_bound": PRICE_UPPER,
                "participants": [
                    {
                        "name": firm,
                        "initial_emissions": 100.0,
                        "free_allocation_ratio": 0.0,
                        "penalty_price": 100000.0,
                        "abatement_type": "threshold",
                        "threshold_cost": 999.0,
                        "max_abatement": 0.0,
                        "sector": "Power",
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
    """A<->B cyclic scenario, tight joint tolerance so prices match the J1 anchor."""
    return {
        "scenarios": [
            {
                "name": "cyc",
                "markets": [
                    _threshold_market("A", "A_firm", "blockA", C_A),
                    _threshold_market("B", "B_firm", "blockB", C_B),
                ],
                "links": [
                    _mac_link("B", "A", PHI_A, "A_firm", "blockA"),  # P_B into A
                    _mac_link("A", "B", PHI_B, "B_firm", "blockB"),  # P_A into B
                ],
                "joint_solver": {"tolerance": 1e-12, "max_iterations": 200},
            }
        ]
    }


def _isolated_b_config() -> dict[str, Any]:
    """Market B solved ALONE (flat single-market scenario, no links) — the shift baseline.

    Same B body, but as a top-level ``years`` scenario the flat path builds and solves.
    With no inbound link its block threshold stays c_B=80 (no phi_B * P_A shift), so its
    demand curve steps at 80 — the control the cyclic B curve (stepping at 162.5) differs
    from.
    """
    b = _threshold_market("B", "B_firm", "blockB", C_B)
    return {"scenarios": [{"name": "isoB", "years": b["years"]}]}


def _flat_two_year_config() -> dict[str, Any]:
    """A plain single-market two-year scenario — the inertness control."""
    return {
        "scenarios": [
            {
                "name": "flat",
                "years": [
                    {
                        "year": "2030",
                        "total_cap": 100.0,
                        "auction_mode": "explicit",
                        "auction_offered": 90.0,
                        "price_upper_bound": PRICE_UPPER,
                        "participants": [
                            {
                                "name": "F1",
                                "initial_emissions": 100.0,
                                "free_allocation_ratio": 0.1,
                                "penalty_price": 300.0,
                                "abatement_type": "linear",
                                "abatement_cost_slope": 2.0,
                                "max_abatement": 40.0,
                                "sector": "Power",
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _curve(result: dict) -> list[dict]:
    return result["demandCurve"]


# ── The real curve for a joint run ───────────────────────────────────────────


def test_joint_run_market_clearing_curve_has_121_points() -> None:
    """Both cyclic members' charts are the full 121-point curve, not the 2-pt schematic."""
    results = _build_dashboard_payload(_cyclic_config())["results"]

    # The composite ``scenario :: market_id`` keys the frontend looks up by.
    assert set(results.keys()) == {"cyc :: A", "cyc :: B"}
    for composite in ("cyc :: A", "cyc :: B"):
        curve = _curve(results[composite]["2030"])
        assert len(curve) == POINT_COUNT
        # Ascending price grid across the full [0, PRICE_UPPER] axis.
        assert curve[0]["p"] == 0.0
        np.testing.assert_allclose(curve[-1]["p"], PRICE_UPPER, rtol=0.0, atol=PRICE_ATOL)
        assert [pt["p"] for pt in curve] == sorted(pt["p"] for pt in curve)
        # Per-participant split is carried at every point (one entry per participant).
        assert all(len(pt["perPart"]) == 1 for pt in curve)


def test_joint_run_curve_is_anchored_to_the_joint_fixed_point() -> None:
    """Each surfaced curve's equilibrium price is the J1 joint anchor (not B-in-isolation)."""
    results = _build_dashboard_payload(_cyclic_config())["results"]
    np.testing.assert_allclose(
        results["cyc :: A"]["2030"]["price"], P_A_IDEAL, rtol=0.0, atol=PRICE_ATOL
    )
    np.testing.assert_allclose(
        results["cyc :: B"]["2030"]["price"], P_B_IDEAL, rtol=0.0, atol=PRICE_ATOL
    )


def test_joint_curve_reflects_the_link_shift() -> None:
    """WITNESS: B's cyclic curve (link-shifted MAC) differs from B-in-isolation's.

    The link A->B shifts B's block threshold from c_B=80 to c_B + phi_B * P_A = 162.5,
    so between those thresholds B-in-isolation has already abated (net demand 60) while
    cyclic B has not (net demand 100). The two 121-point curves — built by the SAME
    code on the SAME price grid — must therefore diverge on the interior points.
    """
    cyc = _build_dashboard_payload(_cyclic_config())["results"]["cyc :: B"]["2030"]
    iso = _build_dashboard_payload(_isolated_b_config())["results"]["isoB"]["2030"]

    # The isolation control pins at the UNSHIFTED threshold; the cyclic curve at the
    # SHIFTED joint price — proof the surfaced leg market carries the inbound shift.
    np.testing.assert_allclose(iso["price"], C_B, rtol=0.0, atol=PRICE_ATOL)
    np.testing.assert_allclose(cyc["price"], P_B_IDEAL, rtol=0.0, atol=PRICE_ATOL)

    cyc_curve, iso_curve = _curve(cyc), _curve(iso)
    assert [pt["p"] for pt in cyc_curve] == [pt["p"] for pt in iso_curve]  # same grid
    differing = [
        pt["p"]
        for pt_c, pt_i in zip(cyc_curve, iso_curve, strict=True)
        if abs(pt_c["total"] - pt_i["total"]) > 1e-9
        for pt in (pt_c,)
    ]
    # The interior band [80, 162.5] on the grid — dozens of points — must differ.
    assert differing, "cyclic B curve is identical to B-in-isolation: the link shift was lost"
    assert all(C_B <= p <= P_B_IDEAL for p in differing)


def test_joint_curve_equilibrium_price_sits_on_the_curve() -> None:
    """The equilibrium dot (P*, Q) lies on the net-demand curve: it crosses Q at P*."""
    for composite, p_ideal in (("cyc :: A", P_A_IDEAL), ("cyc :: B", P_B_IDEAL)):
        result = _build_dashboard_payload(_cyclic_config())["results"][composite]["2030"]
        curve = _curve(result)
        p_star = result["price"]
        cleared = result["auctionSold"]
        assert curve[0]["p"] <= p_star <= curve[-1]["p"]  # within the sampled axis
        # Net demand descends through the cleared quantity as price rises past P*.
        totals_below = [pt["total"] for pt in curve if pt["p"] < p_star]
        totals_above = [pt["total"] for pt in curve if pt["p"] > p_star]
        assert max(totals_below) >= cleared >= min(totals_above)


# ── Single-market inertness ──────────────────────────────────────────────────


def test_single_market_curve_still_built_by_the_shared_builder() -> None:
    """The flat path still produces the real 121-point curve (shared builder, unchanged)."""
    result = _build_dashboard_payload(_flat_two_year_config())["results"]["flat"]["2030"]
    curve = _curve(result)
    assert len(curve) == POINT_COUNT
    assert curve[0]["p"] == 0.0
    np.testing.assert_allclose(curve[-1]["p"], PRICE_UPPER, rtol=0.0, atol=PRICE_ATOL)


def test_multi_market_enrichment_does_not_perturb_a_flat_scenario() -> None:
    """INERTNESS: a flat scenario's result is BYTE-IDENTICAL with or without a linked sibling.

    Running the flat scenario alongside the cyclic one must leave its result dict — the
    121-point demand curve, KPIs, and per-participant panel — exactly what it is when the
    flat scenario runs by itself. The joint-run enrichment retains + surfaces solved leg
    markets; it never leaks into the single-market code path.
    """
    flat_only = _build_dashboard_payload(_flat_two_year_config())["results"]["flat"]

    combined_config = _flat_two_year_config()
    combined_config["scenarios"].extend(_cyclic_config()["scenarios"])
    combined = _build_dashboard_payload(combined_config)["results"]

    assert combined["flat"] == flat_only
