r"""Anchor tests for the D1-3 one-way multi-market DAG solve (engine/links + dispatch).

Binding spec ``docs/platform-spec-d0-d1.md`` §2d/§3/§4/§7; plan
``docs/platform-plan-d0-d1.md`` D1-3. The two-market linear chain is
hand-solvable, which makes A1 an analytical anchor:

* Market A — one participant, LINEAR MAC slope σ_A, cap Q_A. A pure buyer
  (no free allocation) abates a = P/σ_A and must cover residual E0_A − a with
  allowances; net demand E0_A − a clears the auction Q_A at
  ``P_A = σ_A (E0_A − Q_A)`` (competitive clearing is Brent at ~1e-12).
* Market B — one participant, one THRESHOLD technology block at level c_B
  (a step-demand market: abate the block iff price > threshold). With an
  interior auction (E0_B − A_B < Q_B < E0_B) the price sits AT the threshold.
  The ``mac_cost`` link A→B shifts that threshold to c_B + φ·P_A(t), so
  ``P_B = c_B + φ·P_A``.

Concrete anchor economy (all values exactly representable):
    σ_A = 2, E0_A = 100, Q_A = 60  ⇒  P_A = 2·(100 − 60) = 80
    c_B = 10, φ = 0.5, A_B = 40, Q_B = 80  ⇒  P_B = 10 + 0.5·80 = 50

The BANKING variant reruns B as a 2-year banking market on a FLAT source path
(A's two years identical), so the shifted threshold is flat and the delivered
price is c_B + φ·P_A each year (the step-demand banking equilibrium is
degenerate in its bank level — a documented discrete-MAC property — so its
CORRECTNESS is pinned by the master bit-identity pattern, not a hand bank).

MASTER ANCHOR PATTERN (spec §4): a link-compiled config's downstream result ==
the same downstream market solved standalone with the shift HAND-APPLIED to its
config, BIT-IDENTICALLY — the link is inert-as-mechanism, meaningful-as-
information.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from pe.core.protocols import LinkSpec
from pe.engine import run_simulation_from_config
from pe.engine.links import build_link_specs, topological_market_order

# Anchor economy constants.
SIGMA_A = 2.0
E0_A = 100.0
Q_A = 60.0
P_A_IDEAL = SIGMA_A * (E0_A - Q_A)  # 80

C_B = 10.0
PHI = 0.5
Q_B = 80.0  # interior: E0_B − A_B (=60) < 80 < E0_B (=100)
P_B_IDEAL = C_B + PHI * P_A_IDEAL  # 50

PRICE_ATOL = 1e-6


# ── Config builders ──────────────────────────────────────────────────────────


def _linear_firm() -> dict[str, Any]:
    """Market A's single linear-MAC participant (pure buyer, no free allocation)."""
    return {
        "name": "A_firm",
        "initial_emissions": E0_A,
        "free_allocation_ratio": 0.0,
        "penalty_price": 100000.0,
        "abatement_type": "linear",
        "cost_slope": SIGMA_A,
        "max_abatement": E0_A,
    }


def _threshold_firm(c_b: float = C_B) -> dict[str, Any]:
    """Market B's single participant carrying ONE threshold block ("block")."""
    return {
        "name": "B_firm",
        "initial_emissions": 100.0,
        "free_allocation_ratio": 0.0,
        "penalty_price": 100000.0,
        # Participant-level MAC is unused when a technology option is present.
        "abatement_type": "threshold",
        "threshold_cost": 999.0,
        "max_abatement": 0.0,
        "technology_options": [
            {
                "name": "block",
                "abatement_type": "threshold",
                "threshold_cost": c_b,
                "initial_emissions": 100.0,
                "max_abatement": 40.0,
                "free_allocation_ratio": 0.0,
                "penalty_price": 100000.0,
                "max_activity_share": 1.0,
            }
        ],
    }


def _market_a_body(years: tuple[str, ...] = ("2030",)) -> dict[str, Any]:
    return {
        "market_id": "A",
        "price_unit": "USD/tCO2",
        "years": [
            {
                "year": year,
                "total_cap": Q_A,
                "auction_mode": "explicit",
                "auction_offered": Q_A,
                "price_upper_bound": 100000.0,
                "participants": [_linear_firm()],
            }
            for year in years
        ],
    }


def _market_b_body(
    *,
    approach: str = "competitive",
    years: tuple[str, ...] = ("2030",),
    banking: bool = False,
    c_b: float = C_B,
) -> dict[str, Any]:
    return {
        "market_id": "B",
        "price_unit": "USD/tCO2",
        "model_approach": approach,
        "discount_rate": 0.05,
        "years": [
            {
                "year": year,
                "total_cap": Q_B,
                "auction_mode": "explicit",
                "auction_offered": Q_B,
                "price_upper_bound": 100000.0,
                "banking_allowed": banking,
                "participants": [_threshold_firm(c_b)],
            }
            for year in years
        ],
    }


def _mac_link() -> dict[str, Any]:
    return {
        "from_market": "A",
        "to_market": "B",
        "channel": "mac_cost",
        "phi": PHI,
        "phi_unit": "1/1",
        "target_participants": ["B_firm"],
        "target_technologies": ["block"],
    }


def _chain_config(
    *,
    approach_b: str = "competitive",
    b_years: tuple[str, ...] = ("2030",),
    a_years: tuple[str, ...] = ("2030",),
    banking: bool = False,
    with_link: bool = True,
    reversed_declaration: bool = False,
    name: str = "chain",
) -> dict[str, Any]:
    a = _market_a_body(a_years)
    b = _market_b_body(approach=approach_b, years=b_years, banking=banking)
    markets = [b, a] if reversed_declaration else [a, b]
    scenario: dict[str, Any] = {"name": name, "markets": markets}
    if with_link:
        scenario["links"] = [_mac_link()]
    return {"scenarios": [scenario]}


# ── Readers ──────────────────────────────────────────────────────────────────


def _price(summary: pd.DataFrame, scenario_key: str, year: str | None = None) -> float:
    rows = summary[summary["Scenario"] == scenario_key]
    if year is not None:
        rows = rows[rows["Year"] == year]
    return float(rows["Equilibrium Carbon Price"].iloc[0])


def _participant_rows(participants: pd.DataFrame, scenario_key: str) -> pd.DataFrame:
    rows = participants[participants["Scenario"] == scenario_key].drop(columns=["Scenario"])
    return rows.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
# A1 — two-market linear chain, hand-solved (competitive)
# ══════════════════════════════════════════════════════════════════════════════


def test_a1_competitive_prices_match_hand_values() -> None:
    """P_A = σ_A(E0−Q_A) = 80; P_B = c_B + φ·P_A = 50 (atol 1e-6)."""
    summary, _ = run_simulation_from_config(_chain_config())
    np.testing.assert_allclose(_price(summary, "chain :: A"), P_A_IDEAL, rtol=0, atol=PRICE_ATOL)
    np.testing.assert_allclose(_price(summary, "chain :: B"), P_B_IDEAL, rtol=0, atol=PRICE_ATOL)


def test_a1_competitive_market_and_diagnostic_columns() -> None:
    """Guarded Market column + E6 link-diagnostic columns (exact ASCII strings)."""
    summary, _ = run_simulation_from_config(_chain_config())

    b_row = summary[summary["Market"] == "B"]
    a_row = summary[summary["Market"] == "A"]
    assert len(b_row) == 1 and len(a_row) == 1

    # Price In (per (from,to) pair) and Input Shift (channel-qualified) on B.
    np.testing.assert_allclose(
        float(b_row["Link A->B Price In"].iloc[0]), P_A_IDEAL, rtol=0, atol=PRICE_ATOL
    )
    np.testing.assert_allclose(
        float(b_row["Link A->B mac_cost Input Shift"].iloc[0]),
        PHI * P_A_IDEAL,
        rtol=0,
        atol=PRICE_ATOL,
    )
    # A has no inbound link → the guarded link columns are absent for its row.
    assert pd.isna(a_row["Link A->B Price In"].iloc[0])


def test_flat_config_has_no_multi_market_columns() -> None:
    """A single-market (flat) config never gains Market/Link columns (multi-only guard)."""
    flat = {"scenarios": [{"name": "solo", **_market_b_body(c_b=50.0)}]}
    # A flat scenario body carries no "market_id"; strip the D1 key.
    flat["scenarios"][0].pop("market_id", None)
    flat["scenarios"][0].pop("price_unit", None)
    summary, _ = run_simulation_from_config(flat)
    assert "Market" not in summary.columns
    assert not any(str(c).startswith("Link ") for c in summary.columns)


# ══════════════════════════════════════════════════════════════════════════════
# A1 — banking variant (banking B: 2-yr, flat source path, carry checks)
# ══════════════════════════════════════════════════════════════════════════════


def test_a1_banking_prices_flat_at_shifted_threshold() -> None:
    """Banking B over 2 flat years clears each year at c_B + φ·P_A = 50 (atol 1e-6)."""
    summary, _ = run_simulation_from_config(
        _chain_config(approach_b="banking", a_years=("2030", "2031"), b_years=("2030", "2031"), banking=True)
    )
    p_2030 = _price(summary, "chain :: B", "2030")
    p_2031 = _price(summary, "chain :: B", "2031")
    np.testing.assert_allclose(p_2030, P_B_IDEAL, rtol=0, atol=PRICE_ATOL)
    np.testing.assert_allclose(p_2031, P_B_IDEAL, rtol=0, atol=PRICE_ATOL)
    # Carry check: a flat source path yields a flat delivered path — banking
    # forms no arbitrage RAMP (P_{t+1}/P_t == 1, not 1+r).
    np.testing.assert_allclose(p_2031 / p_2030, 1.0, rtol=0, atol=PRICE_ATOL)
    # Banking diagnostics are present on a banking-approach market.
    assert "Banking Regime" in summary.columns
    assert "Banking Aggregate Bank" in summary.columns


def test_a1_banking_link_is_bit_identical_to_hand_shifted_standalone() -> None:
    """MASTER PATTERN (banking): linked B == standalone B with the shift HAND-APPLIED."""
    linked_summary, linked_parts = run_simulation_from_config(
        _chain_config(approach_b="banking", a_years=("2030", "2031"), b_years=("2030", "2031"), banking=True)
    )
    p_a = _price(linked_summary, "chain :: A", "2030")  # the SOLVED source price

    # Standalone banking B with threshold hand-set to c_B + φ·P_A_solved (exact).
    standalone = {
        "scenarios": [
            {"name": "standalone", **_market_b_body(approach="banking", years=("2030", "2031"), banking=True, c_b=C_B + PHI * p_a)}
        ]
    }
    standalone["scenarios"][0].pop("market_id", None)
    standalone["scenarios"][0].pop("price_unit", None)
    _, standalone_parts = run_simulation_from_config(standalone)

    pd.testing.assert_frame_equal(
        _participant_rows(linked_parts, "chain :: B"),
        _participant_rows(standalone_parts, "standalone"),
    )


def test_a1_competitive_link_is_bit_identical_to_hand_shifted_standalone() -> None:
    """MASTER PATTERN (competitive): linked B == standalone hand-shifted B, bit-identical."""
    linked_summary, linked_parts = run_simulation_from_config(_chain_config())
    p_a = _price(linked_summary, "chain :: A")

    standalone = {"scenarios": [{"name": "standalone", **_market_b_body(c_b=C_B + PHI * p_a)}]}
    standalone["scenarios"][0].pop("market_id", None)
    standalone["scenarios"][0].pop("price_unit", None)
    _, standalone_parts = run_simulation_from_config(standalone)

    pd.testing.assert_frame_equal(
        _participant_rows(linked_parts, "chain :: B"),
        _participant_rows(standalone_parts, "standalone"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# A6 — upstream invariance (I3): A is bit-identical with/without its outgoing link
# ══════════════════════════════════════════════════════════════════════════════


def test_a6_upstream_invariance() -> None:
    """A solved WITH and WITHOUT its outgoing link → A's frames bit-identical."""
    _, with_link = run_simulation_from_config(_chain_config(with_link=True))
    _, without_link = run_simulation_from_config(_chain_config(with_link=False))
    pd.testing.assert_frame_equal(
        _participant_rows(with_link, "chain :: A"),
        _participant_rows(without_link, "chain :: A"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# A3 — declaration-order invariance
# ══════════════════════════════════════════════════════════════════════════════


def test_a3_declaration_order_invariance() -> None:
    """Declaring [B, A] vs [A, B] with link A→B → per-market frames identical."""
    _, forward = run_simulation_from_config(_chain_config(reversed_declaration=False))
    _, reversed_ = run_simulation_from_config(_chain_config(reversed_declaration=True))
    for market_key in ("chain :: A", "chain :: B"):
        pd.testing.assert_frame_equal(
            _participant_rows(forward, market_key),
            _participant_rows(reversed_, market_key),
        )


def test_a3_topological_order_is_declaration_invariant() -> None:
    """topological_market_order returns A before B regardless of declared order."""
    link = LinkSpec(
        from_market="A", to_market="B", channel="mac_cost", phi=1.0,
        phi_unit="1/1", target_participants=("*",), target_technologies=("block",),
    )
    assert topological_market_order(["A", "B"], [link]) == ["A", "B"]
    assert topological_market_order(["B", "A"], [link]) == ["A", "B"]


# ══════════════════════════════════════════════════════════════════════════════
# Guards: cycle (R34), events×multi-market (E7), missing source year (E8)
# ══════════════════════════════════════════════════════════════════════════════


def test_cycle_raises_r34_engine_side() -> None:
    """A link cycle A→B→A is rejected, citing D2 (R34 engine-side enforcement)."""
    a_to_b = LinkSpec(
        from_market="A", to_market="B", channel="mac_cost", phi=1.0,
        phi_unit="1/1", target_participants=("*",), target_technologies=("block",),
    )
    b_to_a = LinkSpec(
        from_market="B", to_market="A", channel="mac_cost", phi=1.0,
        phi_unit="1/1", target_participants=("*",), target_technologies=("block",),
    )
    with pytest.raises(ValueError, match="D2"):
        topological_market_order(["A", "B"], [a_to_b, b_to_a])


def test_cycle_no_longer_raises_and_dispatches_to_joint_solver() -> None:
    """R34 FLIPPED (D2-3): a cyclic config is LEGAL and routes to the joint solver.

    The pre-D2-3 assertion (cycle -> ValueError 'Cyclic') is retired here — a
    cyclic SCC is now the joint fixed point, solved through
    ``solve_multi_market_scenario``'s guarded branch. Two symmetric interior
    threshold markets M1<->M2 (mac_cost, phi=0.5 each => loop gain g=0.25 < 1)
    converge; the full hand-value + acyclic-control coverage lives in
    ``tests/engine/test_joint_dispatch.py``.
    """
    m1 = _market_b_body()
    m1["market_id"] = "M1"
    m1["years"][0]["participants"][0]["name"] = "M1_firm"
    m2 = _market_b_body()
    m2["market_id"] = "M2"
    m2["years"][0]["participants"][0]["name"] = "M2_firm"
    config = {
        "scenarios": [
            {
                "name": "cyc",
                "markets": [m1, m2],
                "links": [
                    {"from_market": "M1", "to_market": "M2", "channel": "mac_cost", "phi": PHI,
                     "phi_unit": "1/1", "target_participants": ["M2_firm"], "target_technologies": ["block"]},
                    {"from_market": "M2", "to_market": "M1", "channel": "mac_cost", "phi": PHI,
                     "phi_unit": "1/1", "target_participants": ["M1_firm"], "target_technologies": ["block"]},
                ],
            }
        ]
    }
    summary, _ = run_simulation_from_config(config)  # no raise — cycles are legal now
    assert "Joint Converged" in summary.columns  # cyclic rows carry the guarded columns
    assert set(summary["Market"]) == {"M1", "M2"}
    assert all(summary["Joint Converged"] == 1.0)


def test_events_on_multi_market_raises_e7() -> None:
    """policy_events on a multi-market scenario is deferred (E7), naming the sink relaxation."""
    config = _chain_config()
    config["scenarios"][0]["policy_events"] = [{"trigger_year": "2030", "changes": {}}]
    with pytest.raises(ValueError, match="SINK"):
        run_simulation_from_config(config)


def test_missing_source_year_raises_e8() -> None:
    """A target year absent from the source horizon is an E8 strict-subset error."""
    # B declares 2030 AND 2031; A declares only 2030.
    config = _chain_config(a_years=("2030",), b_years=("2030", "2031"))
    with pytest.raises(ValueError, match="E8 strict-subset"):
        run_simulation_from_config(config)


# ══════════════════════════════════════════════════════════════════════════════
# build_link_specs — construction from the plugin-validated records
# ══════════════════════════════════════════════════════════════════════════════


def test_build_link_specs_constructs_linkspec_objects() -> None:
    scenario = _chain_config()["scenarios"][0]
    links = build_link_specs(scenario)
    assert len(links) == 1
    (link,) = links
    assert isinstance(link, LinkSpec)
    assert (link.from_market, link.to_market, link.channel) == ("A", "B", "mac_cost")
    assert link.phi == PHI
    assert link.target_participants == ("B_firm",)
    assert link.target_technologies == ("block",)


def test_build_link_specs_empty_for_flat_scenario() -> None:
    """A flat scenario (no markets/links) yields no links — the inertness default."""
    flat_scenario = {"name": "solo", **_market_b_body(c_b=50.0)}
    flat_scenario.pop("market_id", None)
    flat_scenario.pop("price_unit", None)
    assert build_link_specs(flat_scenario) == ()
