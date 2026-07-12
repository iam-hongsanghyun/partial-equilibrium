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


def _steel_market_body(*, carbon_price: float = 0.0) -> dict:
    """The steel product market body — 2 identical producers, linear demand, imports."""
    return {
        "market_id": "steel",
        "model_approach": "product",
        "price_unit": "USD/t-steel",
        "carbon_price": carbon_price,
        "product_demand": {"form": "linear", "intercept": 40.0, "slope": _B_D},
        "import_supply": {"world_price": 0.0, "slope": _M_SLOPE, "sigma_foreign": _SIGMA_FOREIGN},
        "years": [
            {
                "year": "2030",
                "participants": [
                    {"name": "SteelCo A", **_PRODUCER},
                    {"name": "SteelCo B", **_PRODUCER},
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


def _joint_scenario(*, back_link: bool = True) -> dict:
    """The full steel↔carbon joint scenario.

    Args:
        back_link: When ``True`` both coupling links are present (the genuine
            2-way cycle). When ``False`` only carbon→steel remains — a
            block-recursive acyclic chain (the β→∞-style corner control).
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
    return {
        "scenarios": [
            {
                "name": "steel-carbon-joint",
                "markets": [_carbon_market_body(), _steel_market_body()],
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
