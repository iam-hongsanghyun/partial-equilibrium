r"""D3-4 flagship: the steel↔carbon joint cycle, price-driven coupling.

Lights the joint cycle (``docs/multi-commodity-spec.md`` §7 V-D3-5b, the genuine
finite-β cyclic anchor). A ``carbon`` market (competitive, fixed cap = 40, a
``producer_ref`` to the steel producers) and a ``steel`` product market (2
identical firms γ=5, δ=2, σ=5, β=10, a_max=5; linear demand A_d=40, b_d=0.3;
carbon-free imports m=0.2, σ_foreign=5) are wired by the two D3-4 coupling links
(carbon→steel ``carbon_input_price``, steel→carbon ``output_ref_price``). Because
finite β makes output endogenous at a fixed cap, this is a REAL 2-way SCC that the
UNCHANGED joint engine (``engine/scc.py`` + ``engine/joint.py``) solves via damped
Gauss-Seidel to the economist's finite-β anchor:

    P_steel* = 60, P_carbon* = 10, per-firm q* = 5, a* = 1, Σe* = 40 = Cap,
    imports M* = 12, D = 22; loop gain g = s_c·s_s = 0.627 ∈ (0, 1).

The coupling is PRICE-DRIVEN (V-D3-3): each leg re-derives q*/e* from BOTH prices;
no quantity crosses the SCC, so the joint engine's price norm suffices.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from pe.core.participant.producer import ProducerParams
from pe.engine import run_simulation_from_config
from pe.features.product_market.solver import product_scc_loop_gain

# ── The V-D3-5b anchor economy (in-code config; the D3-6 golden FILE is later) ──
_SIGMA_FOREIGN = 5.0
_M_SLOPE = 0.2
_B_D = 0.3
_PRODUCER = {
    "kind": "producer",
    "output_cost": {"gamma": 5.0, "delta": 2.0},
    "intensity": 5.0,
    "abatement": {"beta": 10.0, "a_max": 5.0},
}

# Hand-verified anchor targets (spec §7 V-D3-5b).
_P_STEEL_STAR = 60.0
_P_CARBON_STAR = 10.0
_Q_STAR = 5.0
_A_STAR = 1.0
_CAP = 40.0
_M_STAR = 12.0
_DEMAND = 22.0
_LOOP_GAIN = 0.6274509803921569  # s_c·s_s = 0.235·2.667

# No-policy counterfactual (P_carbon = 0): P_s⁰=30, e⁰=125, M⁰=6 ⇒ L = 0.353.
_P_STEEL_0 = 30.0
_E_DOM_0 = 125.0
_M_0 = 6.0
_LEAKAGE = _SIGMA_FOREIGN * (_M_STAR - _M_0) / (_E_DOM_0 - _CAP)  # 30/85 = 0.35294

_ATOL = 1e-6


def _steel_market_body(
    *,
    carbon_price: float = 0.0,
    cbam: dict | None = None,
    phi_oba: float = 0.0,
    tech_options: list[dict] | None = None,
) -> dict:
    """The steel product market body — 2 identical producers, linear demand, imports.

    D3-5 lever knobs (each off-by-default): ``cbam`` (price-active import charge,
    spec §4e), ``phi_oba`` (marginal output subsidy, §4d), ``tech_options`` (the
    cleaner-tech adoption option, §4g). All absent ⇒ the D3-4 anchor verbatim.
    """
    producer = dict(_PRODUCER)
    if phi_oba:
        producer["oba_benchmark"] = phi_oba
    if tech_options is not None:
        producer["technology_options"] = tech_options
    import_supply: dict = {"world_price": 0.0, "slope": _M_SLOPE, "sigma_foreign": _SIGMA_FOREIGN}
    if cbam is not None:
        import_supply["cbam"] = cbam
    return {
        "market_id": "steel",
        "model_approach": "product",
        "price_unit": "USD/t-steel",
        "carbon_price": carbon_price,
        "product_demand": {"form": "linear", "intercept": 40.0, "slope": _B_D},
        "import_supply": import_supply,
        "years": [
            {
                "year": "2030",
                "participants": [
                    {"name": "SteelCo A", **producer},
                    {"name": "SteelCo B", **producer},
                ],
            }
        ],
    }


def _carbon_market_body() -> dict:
    """The carbon market body — competitive, fixed cap = 40, a producer_ref to steel.

    No free-alloc supply bucket (spec §7): auction_offered = cap = 40, clearing is
    purely Σe* = Cap. The producer emitter views (expanded from producer_ref) are
    its only participants. A generous ``price_upper_bound`` supplies the Brent
    bracket (the views carry no penalty_price); it never binds (P_c* = 10).
    """
    return {
        "market_id": "carbon",
        "model_approach": "competitive",
        "price_unit": "USD/tCO2",
        "producer_ref": {"market": "steel"},
        "years": [
            {
                "year": "2030",
                "total_cap": _CAP,
                "auction_offered": _CAP,
                "auction_mode": "explicit",
                "price_upper_bound": 200.0,
                "participants": [],
            }
        ],
    }


def _joint_scenario(
    *,
    back_link: bool = True,
    cbam: dict | None = None,
    phi_oba: float = 0.0,
    tech_options: list[dict] | None = None,
) -> dict:
    """The full steel↔carbon joint scenario.

    Args:
        back_link: When ``True`` both coupling links are present (the genuine
            2-way cycle). When ``False`` only carbon→steel remains — a
            block-recursive acyclic chain (the β→∞-style corner control).
        cbam: Optional price-active CBAM lever config (spec §4e).
        phi_oba: Optional OBA marginal output subsidy benchmark (§4d).
        tech_options: Optional cleaner-tech adoption options (§4g).
    """
    links = [
        {
            "from_market": "carbon",
            "to_market": "steel",
            "channel": "carbon_input_price",
            "phi": 1.0,
            "phi_unit": "1/1",
            "target_participants": ["*"],
        }
    ]
    if back_link:
        links.append(
            {
                "from_market": "steel",
                "to_market": "carbon",
                "channel": "output_ref_price",
                "phi": 1.0,
                "phi_unit": "1/1",
                "target_participants": ["*"],
            }
        )
    steel = _steel_market_body(cbam=cbam, phi_oba=phi_oba, tech_options=tech_options)
    return {
        "scenarios": [
            {
                "name": "steel-carbon-joint",
                "markets": [_carbon_market_body(), steel],
                "links": links,
                # Tight tolerance so the reported prices land on the exact anchor
                # (atol 1e-6); damped w=0.5 per the flagship spec.
                "joint_solver": {"relaxation": 0.5, "tolerance": 1e-12, "max_iterations": 400},
            }
        ]
    }


def _price(summary, market_id: str) -> float:
    row = summary[summary["Market"] == market_id]
    return float(row["Equilibrium Carbon Price"].iloc[0])


def test_joint_cycle_solves_to_the_finite_beta_anchor() -> None:
    """P_steel*=60, P_carbon*=10, q*=5, a*=1, Σe*=40=Cap, M*=12, D=22 (atol 1e-6)."""
    summary, participants = run_simulation_from_config(_joint_scenario())

    # Two prices, both blades of the mixed-unit SCC.
    np.testing.assert_allclose(_price(summary, "steel"), _P_STEEL_STAR, rtol=0, atol=_ATOL)
    np.testing.assert_allclose(_price(summary, "carbon"), _P_CARBON_STAR, rtol=0, atol=_ATOL)

    steel_rows = participants[participants["Scenario"].str.endswith("steel")]
    np.testing.assert_allclose(
        steel_rows["Output"].to_numpy(dtype=float), [_Q_STAR, _Q_STAR], rtol=0, atol=_ATOL
    )
    np.testing.assert_allclose(
        steel_rows["Intensity Abatement"].to_numpy(dtype=float),
        [_A_STAR, _A_STAR],
        rtol=0,
        atol=_ATOL,
    )
    np.testing.assert_allclose(float(steel_rows["Emissions"].sum()), _CAP, rtol=0, atol=_ATOL)

    # Carbon leg: the producer emitter views' residual emissions clear to the cap
    # (Σe* = Cap, no free-alloc bucket).
    carbon_rows = participants[participants["Scenario"].str.endswith("carbon")]
    np.testing.assert_allclose(
        float(carbon_rows["Residual Emissions"].sum()), _CAP, rtol=0, atol=_ATOL
    )

    # Imports M* = m·P_steel* = 12 and demand D = A_d − b_d·P_steel* = 22.
    p_steel = _price(summary, "steel")
    np.testing.assert_allclose(_M_SLOPE * p_steel, _M_STAR, rtol=0, atol=_ATOL)
    np.testing.assert_allclose(40.0 - _B_D * p_steel, _DEMAND, rtol=0, atol=_ATOL)


def test_joint_cycle_convergence_diagnostics() -> None:
    """Joint Converged=1, Cycle Detected=0, Outer Iterations >= 2 (a genuine cycle)."""
    summary, _ = run_simulation_from_config(_joint_scenario())
    for market_id in ("carbon", "steel"):
        row = summary[summary["Market"] == market_id]
        assert float(row["Joint Converged"].iloc[0]) == 1.0
        assert float(row["Joint Cycle Detected"].iloc[0]) == 0.0
        # One sweep cannot reach it (block-recursive would): a real 2-way cycle.
        assert float(row["Joint Outer Iterations"].iloc[0]) >= 2.0


def test_leakage_rate_matches_the_anchor() -> None:
    """L = σ_foreign·ΔM / (−Δe_dom) = 30/85 = 0.353 vs the no-policy counterfactual."""
    summary, participants = run_simulation_from_config(_joint_scenario())
    p_steel = _price(summary, "steel")
    m_star = _M_SLOPE * p_steel
    e_dom_star = float(
        participants[participants["Scenario"].str.endswith("steel")]["Emissions"].sum()
    )
    leakage = _SIGMA_FOREIGN * (m_star - _M_0) / (_E_DOM_0 - e_dom_star)
    np.testing.assert_allclose(leakage, _LEAKAGE, rtol=0, atol=_ATOL)
    np.testing.assert_allclose(leakage, 30.0 / 85.0, rtol=0, atol=_ATOL)


def test_no_policy_counterfactual_slice() -> None:
    """Standalone steel at P_c=0 reproduces P_s⁰=30, e⁰=125, M⁰=6 (the L denominator)."""
    cf = {"scenarios": [{"name": "steel-nopolicy", **_steel_market_body(carbon_price=0.0)}]}
    # Strip the multi-market key so it runs as a flat product scenario.
    cf["scenarios"][0].pop("market_id")
    summary, participants = run_simulation_from_config(cf)
    p_steel0 = float(summary.iloc[0]["Equilibrium Carbon Price"])
    np.testing.assert_allclose(p_steel0, _P_STEEL_0, rtol=0, atol=_ATOL)
    np.testing.assert_allclose(float(participants["Emissions"].sum()), _E_DOM_0, rtol=0, atol=_ATOL)
    np.testing.assert_allclose(_M_SLOPE * p_steel0, _M_0, rtol=0, atol=_ATOL)


def test_r37_actual_jacobian_gain_does_not_warn() -> None:
    """g = s_c·s_s = 0.627 < 1 ⇒ no R37 loop-gain WARNING fires (spec §7 R37 adaptation)."""
    # The pure gain at the converged operating point.
    params = [
        ProducerParams(gamma=5.0, delta=2.0, sigma=5.0, beta=10.0, a_max=5.0) for _ in range(2)
    ]
    g = product_scc_loop_gain(
        params, b_d=_B_D, m=_M_SLOPE, price_steel=_P_STEEL_STAR, price_carbon=_P_CARBON_STAR
    )
    np.testing.assert_allclose(g, _LOOP_GAIN, rtol=0, atol=1e-9)
    assert abs(g) < 1.0

    # And the runtime guard stays silent across the whole solve.
    with _capture_warnings() as records:
        run_simulation_from_config(_joint_scenario())
    assert not [r for r in records if "loop gain" in r.getMessage().lower()]


def test_disabling_back_link_is_block_recursive_and_still_solves() -> None:
    """Control: one-way carbon→steel is acyclic (no cycle) — the engine still solves it."""
    summary, _ = run_simulation_from_config(_joint_scenario(back_link=False))
    # Acyclic ⇒ no joint outer loop ⇒ the four "Joint *" columns are absent.
    assert "Joint Converged" not in summary.columns
    # Carbon has no steel-price stamp (no back-link) ⇒ e*=0 ⇒ boundary P_c=0;
    # steel then clears at the no-policy price P_s⁰=30. Both markets solved.
    np.testing.assert_allclose(_price(summary, "carbon"), 0.0, rtol=0, atol=_ATOL)
    np.testing.assert_allclose(_price(summary, "steel"), _P_STEEL_0, rtol=0, atol=_ATOL)


# ── D3-5 lever helpers ────────────────────────────────────────────────────────


def _steel_row(summary):
    return summary[summary["Market"] == "steel"]


def _q_agg(participants) -> float:
    return float(participants[participants["Scenario"].str.endswith("steel")]["Output"].sum())


def _a_first(participants) -> float:
    steel = participants[participants["Scenario"].str.endswith("steel")]
    return float(steel["Intensity Abatement"].to_numpy(dtype=float)[0])


def _imports(summary, participants) -> float:
    """Actual imports M* = D(P_s*) − Σq* (includes any CBAM shift)."""
    p_steel = _price(summary, "steel")
    return (40.0 - _B_D * p_steel) - _q_agg(participants)


# ── D3-5 (a) CBAM — price-active import charge; the two-sided anti-leakage lever ─
#
# Numerically-computed goldens (the coupled steel↔carbon fixed point under the
# finite-β anchor + the CBAM shift; not closed-form, pinned per spec §7).
_CBAM_HALF_P_STEEL = 71.2632628565
_CBAM_HALF_P_CARBON = 12.7258694436
_CBAM_HALF_LEAKAGE = 0.1111598735
_CBAM_FULL_P_CARBON = 17.8736088645
_CBAM_FULL_Q_AGG = 12.4508230424
_CBAM_FULL_LEAKAGE = -0.3355584940
_PIN = 1e-6


def test_cbam_half_coverage_drives_leakage_toward_zero() -> None:
    """CBAM c=0.5 (spec §4e/§7): leakage FALLS from 0.353 toward zero (0.111)."""
    summary, participants = run_simulation_from_config(
        _joint_scenario(cbam={"enabled": True, "coverage": 0.5})
    )
    np.testing.assert_allclose(_price(summary, "steel"), _CBAM_HALF_P_STEEL, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_price(summary, "carbon"), _CBAM_HALF_P_CARBON, rtol=0, atol=_PIN)
    leakage = float(_steel_row(summary)["Leakage Rate"].iloc[0])
    np.testing.assert_allclose(leakage, _CBAM_HALF_LEAKAGE, rtol=0, atol=_PIN)
    # Direction: strictly between the anchor (0.353) and neutralised (0).
    assert 0.0 < leakage < _LEAKAGE


def test_cbam_full_coverage_over_corrects_leakage_negative() -> None:
    """CBAM c=1 over-corrects (spec §7): P_c↑≈17.9, q↑≈12.5, imports collapse, L<0."""
    summary, participants = run_simulation_from_config(
        _joint_scenario(cbam={"enabled": True, "coverage": 1.0})
    )
    np.testing.assert_allclose(_price(summary, "carbon"), _CBAM_FULL_P_CARBON, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_q_agg(participants), _CBAM_FULL_Q_AGG, rtol=0, atol=_PIN)
    leakage = float(_steel_row(summary)["Leakage Rate"].iloc[0])
    np.testing.assert_allclose(leakage, _CBAM_FULL_LEAKAGE, rtol=0, atol=_PIN)
    # Over-correction: imports collapse (M* ≈ 0.30 vs anchor 12) and leakage < 0.
    assert leakage < 0.0
    assert _imports(summary, participants) < 1.0
    # Emission-intensive tightening: carbon price and per-firm output both rise.
    assert _price(summary, "carbon") > _P_CARBON_STAR
    assert _q_agg(participants) > 2.0 * _Q_STAR


# ── D3-5 (b) Leakage diagnostic column — guarded, multi-market product rows only ─


def test_leakage_rate_column_present_on_product_row_only() -> None:
    """ "Leakage Rate" reads 0.353 on the steel row, absent on the carbon row."""
    summary, _ = run_simulation_from_config(_joint_scenario())
    assert "Leakage Rate" in summary.columns
    np.testing.assert_allclose(
        float(_steel_row(summary)["Leakage Rate"].iloc[0]), _LEAKAGE, rtol=0, atol=_PIN
    )
    # Guarded: the carbon row carries NO leakage value (NaN after the frame join).
    carbon_leak = summary[summary["Market"] == "carbon"]["Leakage Rate"]
    assert bool(carbon_leak.isna().all())


def test_leakage_rate_column_absent_for_single_market_run() -> None:
    """A standalone product run carries NO "Leakage Rate" column (config-driven)."""
    cf = {"scenarios": [{"name": "steel-only", **_steel_market_body(carbon_price=0.0)}]}
    cf["scenarios"][0].pop("market_id")
    summary, _ = run_simulation_from_config(cf)
    assert "Leakage Rate" not in summary.columns


# ── D3-5 (c) OBA — marginal output subsidy: q* rises, a* unchanged, leakage falls ─
_OBA_P_STEEL = 53.3333333333
_OBA_Q_AGG = 13.3333333333
_OBA_LEAKAGE = 0.3255813953


def test_oba_raises_output_leaves_abatement_untouched_and_cuts_leakage() -> None:
    """OBA φ>0 (spec §4d): q* RISES, a* UNCHANGED, leakage FALLS (output preserved)."""
    base_summary, base_participants = run_simulation_from_config(_joint_scenario())
    summary, participants = run_simulation_from_config(_joint_scenario(phi_oba=1.0))

    np.testing.assert_allclose(_price(summary, "steel"), _OBA_P_STEEL, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_q_agg(participants), _OBA_Q_AGG, rtol=0, atol=_PIN)
    # a* is a pure function of P_c only (a=P_c/β); OBA leaves it exactly at 1.0.
    np.testing.assert_allclose(
        _a_first(participants), _a_first(base_participants), rtol=0, atol=_PIN
    )
    # Output preserved domestically ⇒ q* rises above the no-OBA anchor.
    assert _q_agg(participants) > _q_agg(base_participants)
    leakage = float(_steel_row(summary)["Leakage Rate"].iloc[0])
    np.testing.assert_allclose(leakage, _OBA_LEAKAGE, rtol=0, atol=_PIN)
    assert leakage < _LEAKAGE


# ── D3-5 (d) Investment — cleaner tech, the long-run margin (adoption-in-cycle) ──
_H2_DRI = [{"name": "H2-DRI", "sigma_prime": 3.0, "trigger": 9.0}]
_ADOPT_P_STEEL = 43.7581014729
_ADOPT_P_CARBON = 7.9261020626
_ADOPT_Q_AGG = 18.1209502350


def test_investment_adoption_recovers_output_and_loosens_the_cap() -> None:
    """P_c crosses θ=9 ⇒ H2-DRI adopts ⇒ σ↓ ⇒ P_c falls, output recovers (spec §4g)."""
    summary, participants = run_simulation_from_config(_joint_scenario(tech_options=_H2_DRI))

    # Converged joint fixed point WITH adoption (a genuine cyclic SCC).
    carbon_summary = summary[summary["Market"] == "carbon"]
    assert float(carbon_summary["Joint Converged"].iloc[0]) == 1.0

    # The adopted fixed point DIFFERS from the no-adopt anchor.
    np.testing.assert_allclose(_price(summary, "steel"), _ADOPT_P_STEEL, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_price(summary, "carbon"), _ADOPT_P_CARBON, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_q_agg(participants), _ADOPT_Q_AGG, rtol=0, atol=_PIN)

    # σ drops → the cap loosens → P_c FALLS below the no-adopt anchor (ex-post
    # regret permitted: 7.93 < the θ=9 trigger), and output RECOVERS.
    assert _price(summary, "carbon") < _P_CARBON_STAR
    assert _q_agg(participants) > 2.0 * _Q_STAR

    # Adoption is recorded on the steel row (the clean tech was adopted once).
    assert float(_steel_row(summary)["Investment Newly Effective"].iloc[0]) == 2.0
    assert "H2-DRI" in str(_steel_row(summary)["Investment Adoptions"].iloc[0])


def test_investment_trigger_not_crossed_reproduces_the_no_adopt_anchor() -> None:
    """θ=11 > P_c*=10 ⇒ no adoption ⇒ the fixed point is the D3-4 anchor exactly."""
    no_adopt = [{"name": "H2-DRI", "sigma_prime": 3.0, "trigger": 11.0}]
    summary, participants = run_simulation_from_config(_joint_scenario(tech_options=no_adopt))
    np.testing.assert_allclose(_price(summary, "steel"), _P_STEEL_STAR, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_price(summary, "carbon"), _P_CARBON_STAR, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_q_agg(participants), 2.0 * _Q_STAR, rtol=0, atol=_PIN)


# ── D3-5 composition — the levers compose (any subset can be on together) ───────


def test_cbam_and_oba_compose() -> None:
    """CBAM + OBA together still converge to a single joint fixed point."""
    summary, participants = run_simulation_from_config(
        _joint_scenario(cbam={"enabled": True, "coverage": 0.5}, phi_oba=0.5)
    )
    assert float(summary[summary["Market"] == "carbon"]["Joint Converged"].iloc[0]) == 1.0
    # Both anti-leakage levers active ⇒ a well-defined leakage read on the steel row.
    assert "Leakage Rate" in summary.columns
    assert np.isfinite(float(_steel_row(summary)["Leakage Rate"].iloc[0]))


# ── V-D3-5 ruling #4: OBA cap-RELAXING vs CBAM cap-PRESERVING (Σe surfaced) ──────


def test_cbam_is_cap_preserving_gross_emissions_equal_cap() -> None:
    """CBAM (ruling #4): no free allowances ⇒ gross Σe = Cap = 40 (cap-preserving)."""
    summary, _ = run_simulation_from_config(
        _joint_scenario(cbam={"enabled": True, "coverage": 0.5})
    )
    row = _steel_row(summary)
    np.testing.assert_allclose(float(row["Gross Emissions"].iloc[0]), _CAP, rtol=0, atol=_PIN)
    np.testing.assert_allclose(float(row["OBA Free Allocation"].iloc[0]), 0.0, rtol=0, atol=_PIN)


def test_oba_is_cap_relaxing_gross_emissions_exceed_cap() -> None:
    """OBA (ruling #4): Σe = Cap + φ·Σq = 40 + 13.33 = 53.33; the cap FLOATS up +33%."""
    summary, participants = run_simulation_from_config(_joint_scenario(phi_oba=1.0))
    row = _steel_row(summary)
    # φ·Σq free allowances issued ON TOP of the cap.
    np.testing.assert_allclose(
        float(row["OBA Free Allocation"].iloc[0]), _OBA_Q_AGG, rtol=0, atol=_PIN
    )
    # Gross residual emissions = Cap + φ·Σq (cap-relaxing).
    np.testing.assert_allclose(
        float(row["Gross Emissions"].iloc[0]), _CAP + _OBA_Q_AGG, rtol=0, atol=_PIN
    )
    np.testing.assert_allclose(
        float(row["Gross Emissions"].iloc[0]), 53.3333333333, rtol=0, atol=_PIN
    )
    assert str(row["OBA Mode"].iloc[0]) == "output_based"
    # The contrast: OBA floats emissions ABOVE the cap, CBAM does not.
    assert float(row["Gross Emissions"].iloc[0]) > _CAP


# ── V-D3-5 ruling #1: the θ/M trigger surface reports P* = M·θ ───────────────────


def test_clean_tech_trigger_price_reported_as_p_star() -> None:
    """Ruling #1: break_even ⇒ P* = θ = 9 reported as 'Clean Tech Trigger Price'."""
    summary, _ = run_simulation_from_config(_joint_scenario(tech_options=_H2_DRI))
    np.testing.assert_allclose(
        float(_steel_row(summary)["Clean Tech Trigger Price"].iloc[0]), 9.0, rtol=0, atol=_PIN
    )


def test_option_value_trigger_lifts_p_star_above_theta_and_blocks_adoption() -> None:
    """Ruling #1: option_value M>1 lifts P* above θ; a high wedge blocks adoption.

    θ=9 with an option-value multiple pushes P* = M·9 well above the base
    P_c*=10, so the switch does NOT fire and the fixed point is the no-adopt
    anchor — the irreversibility-under-uncertainty wedge, kept as real economics
    (not folded into a single trigger number).
    """
    option_value = [
        {
            "name": "H2-DRI",
            "sigma_prime": 3.0,
            "theta": 9.0,
            "trigger_mode": "option_value",
            "sigma": 0.48,
            "credibility": 0.0,
            "discount_rate": 0.055,
            "payout_yield": 0.03,
        }
    ]
    summary, participants = run_simulation_from_config(_joint_scenario(tech_options=option_value))
    # P* = M·θ > θ = 9, and (here) above P_c* ⇒ no adoption ⇒ the D3-4 anchor.
    assert float(_steel_row(summary)["Clean Tech Trigger Price"].iloc[0]) > 9.0
    np.testing.assert_allclose(_price(summary, "steel"), _P_STEEL_STAR, rtol=0, atol=_PIN)
    np.testing.assert_allclose(_price(summary, "carbon"), _P_CARBON_STAR, rtol=0, atol=_PIN)


# ── V-D3-5 ruling #2: leakage counterfactual at the UN-ADOPTED σ ─────────────────

_ADOPT_HEADLINE_LEAKAGE = 0.1618595826
_ADOPT_CONDITIONAL_LEAKAGE = 0.3930893232


def test_investment_headline_leakage_uses_unadopted_counterfactual() -> None:
    """Ruling #2: headline leakage holds the P_c=0 counterfactual at the UN-ADOPTED σ.

    Adoption preserves domestic output, so scored against the un-adopted
    baseline the whole-policy leakage is LOWER than the post-adoption-σ′
    conditional leakage. The two coincide only when nothing adopts.
    """
    summary, _ = run_simulation_from_config(_joint_scenario(tech_options=_H2_DRI))
    row = _steel_row(summary)
    headline = float(row["Leakage Rate"].iloc[0])
    conditional = float(row["Conditional Leakage"].iloc[0])
    np.testing.assert_allclose(headline, _ADOPT_HEADLINE_LEAKAGE, rtol=0, atol=_PIN)
    np.testing.assert_allclose(conditional, _ADOPT_CONDITIONAL_LEAKAGE, rtol=0, atol=_PIN)
    # The induced tech-switch lowers whole-policy leakage below the conditional.
    assert headline < conditional


def test_no_adoption_headline_and_conditional_leakage_coincide() -> None:
    """Ruling #2: with no adoption the two counterfactuals are identical (0.353)."""
    summary, _ = run_simulation_from_config(_joint_scenario())
    row = _steel_row(summary)
    np.testing.assert_allclose(
        float(row["Leakage Rate"].iloc[0]),
        float(row["Conditional Leakage"].iloc[0]),
        rtol=0,
        atol=_PIN,
    )
    np.testing.assert_allclose(float(row["Leakage Rate"].iloc[0]), _LEAKAGE, rtol=0, atol=_PIN)


# ── V-D3-5 ruling #3: the convergence-time leg-agreement assertion ──────────────


def test_leg_agreement_assertion_passes_when_faces_agree() -> None:
    """Consistent converged floors (same firm, same tech on both faces) ⇒ no raise."""
    from pe.engine.dispatch import _assert_leg_adoption_agreement

    member_firms = {"steel": {"SteelCo A"}, "carbon": {"SteelCo A"}}
    member_adopted = {
        "steel": {"SteelCo A": frozenset({"H2-DRI"})},
        "carbon": {"SteelCo A": frozenset({"H2-DRI"})},
    }
    # Does not raise.
    _assert_leg_adoption_agreement(member_firms, member_adopted, "ok")


def test_leg_agreement_assertion_raises_on_inconsistent_converged_state() -> None:
    """Ruling #3: same firm on σ (carbon face) but σ′ (steel face) MUST raise.

    A deliberately-inconsistent converged construction: SteelCo A adopted H2-DRI
    on the steel output face but NOT on the carbon emitter face — the exact
    leg-inconsistent 'equilibrium' the assertion must reject loudly.
    """
    from pe.engine.dispatch import _assert_leg_adoption_agreement

    member_firms = {"steel": {"SteelCo A"}, "carbon": {"SteelCo A"}}
    member_adopted = {
        "steel": {"SteelCo A": frozenset({"H2-DRI"})},
        "carbon": {"SteelCo A": frozenset()},  # baseline σ on the carbon face
    }
    with pytest.raises(ValueError, match="INCONSISTENT clean-tech adoption"):
        _assert_leg_adoption_agreement(member_firms, member_adopted, "steel-carbon")


def test_real_joint_investment_run_passes_the_leg_agreement_assertion() -> None:
    """The genuine adopting run converges WITHOUT tripping the leg-agreement guard."""
    summary, _ = run_simulation_from_config(_joint_scenario(tech_options=_H2_DRI))
    # If the two faces disagreed at convergence the solve would have RAISED.
    assert float(summary[summary["Market"] == "carbon"]["Joint Converged"].iloc[0]) == 1.0
    assert "H2-DRI" in str(_steel_row(summary)["Investment Adoptions"].iloc[0])


class _capture_warnings:
    """Context manager collecting WARNING records from the product-market solver."""

    def __init__(self) -> None:
        self._logger = logging.getLogger("pe.features.product_market.solver")
        self._records: list[logging.LogRecord] = []
        self._handler = logging.Handler()
        self._handler.setLevel(logging.WARNING)
        self._handler.emit = self._records.append  # type: ignore[method-assign]

    def __enter__(self) -> list[logging.LogRecord]:
        self._prev_level = self._logger.level
        self._logger.setLevel(logging.WARNING)
        self._logger.addHandler(self._handler)
        return self._records

    def __exit__(self, *exc: object) -> None:
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._prev_level)
