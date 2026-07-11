r"""Regression tests for the price_controls feature module (O10).

Reference
---------
``docs/feature-modules-plan.md`` PLAN v2 §3 (price_controls verdict: the
trajectory plugin + ``FloorCancellationRule`` + ``DeliveredFloor`` move; the
in-clearing floor branch STAYS KERNEL — its permanent property test is
``tests/test_price_boundary_property.py``) and the binding Arbitration O10
item (MSR-then-floor order preserved; ``DeliveredFloor`` attach-always exact).

FloorCancellationRule contract (economist verdict 1c): NOT a
``core.protocols.SupplyRule`` — it composes on the CONTEMPORANEOUS year's
supply in a dedicated host slot AFTER the injected supply rules, not on the
lagged ``Observables`` a ``SupplyRule`` sees. Since the direct-complementarity
fix (``docs/floor-cancellation-fix.md`` §2) the rule's binding decision is
price-free (``e_t(F_t) < S_t`` on fixed quantities); the host gates window-year
cancellation by the contemporaneous price. Both facts are pinned here.

Anchor economy (hand-solvable, as ``tests/test_banking.py``): one participant,
BAU E = 100 Mt, linear MAC p = c·a with c = 100, r = 0.05. Supplies
(95, 85) with a 2500 KRW reserve floor + ``unsold_treatment: "cancel"`` on
2031 only:

    iterate 0: no-cancel window P = (975.6, 1024.4); floor 2500 binds 2031
    cancel:    u_1 = S_1 − e_1(F) = 85 − (100 − 2500/100) = 10 Mt
    iterate 1: S_eff = (95, 75) -> P_0 = c(2E − 170)/(2 + r) = 1463.41…,
               P_1 = 1536.59 < 2500 -> floor still binds, u_1 = 10 again ->
               schedule stable (the fixed point needs the cancellation).
    delivered: P_1 clips to the floor 2500 (DeliveredFloor, clip-LAST);
    banks:     B_0 = 95 − (E − P_0/c) = 9.63, B_1 = 0 (window [0, 1]).

Legacy anchor below captured on the PINNED environment at the pre-O10 tree
(2026-07-11) via ``solve_banking_path``; asserted at rtol=0, atol=0.
"""

from __future__ import annotations

import numpy as np
import pytest

from pe.config_io import build_markets_from_config
from pe.config_io.builder import _interp_value
from pe.core.protocols import PriceOverlay, SupplyRule
from pe.features.price_controls.plugin import DeliveredFloor, apply_price_bound_trajectories
from pe.features.price_controls.rules import FloorCancellationRule
from pe.engine import run_simulation_from_config, solve_banking_path

E = 100.0  # BAU emissions per year [Mt]
C = 100.0  # linear MAC slope [KRW per t per Mt]
R = 0.05  # carry rate [1/yr]


def _years(supplies, floors=None, unsold="reserve"):
    years = []
    for index, supply in enumerate(supplies):
        years.append(
            {
                "year": str(2030 + index),
                "total_cap": supply,
                "auction_mode": "derive_from_cap",
                "auction_reserve_price": (floors[index] if floors else 0.0),
                "unsold_treatment": unsold,
                "banking_allowed": False,
                "borrowing_allowed": False,
                "expectation_rule": "next_year_baseline",
                "price_lower_bound": 0.0,
                "price_upper_bound": 100000.0,
                "participants": [
                    {
                        "name": "Industry",
                        "initial_emissions": E,
                        "free_allocation_ratio": 0.0,
                        "penalty_price": 0.0,
                        "abatement_type": "linear",
                        "max_abatement": E,
                        "cost_slope": C,
                    }
                ],
            }
        )
    return years


def _floor_binding_config() -> dict:
    return {
        "scenarios": [
            {
                "name": "floor-cancel-anchor",
                "model_approach": "banking",
                "discount_rate": R,
                "banking_initial_bank": 0.0,
                "years": _years([95.0, 85.0], floors=[0.0, 2500.0], unsold="cancel"),
            }
        ]
    }


# Captured 2026-07-11 on the pinned environment (uv.lock) at the PRE-refactor
# tree (before the O10 extraction), via solve_banking_path. Tuples are
# (price, banking_floor_cancelled, banking_aggregate_bank, auction_sold) per
# year. Bar: rtol=0, atol=0 (bit-exact).
_PRE_REFACTOR_ANCHOR: dict[str, tuple[float, ...]] = {
    "2030": (1463.4146341463427, 0.0, 9.634146341463406, 85.3658536585366),
    "2031": (2500.0, 10.000000000000014, 0.0, 74.99999999999999),
}


def _assert_matches_anchor(path: list[dict]) -> None:
    assert len(path) == len(_PRE_REFACTOR_ANCHOR)
    for item in path:
        year = str(item["market"].year)
        price, cancelled, bank, sold = _PRE_REFACTOR_ANCHOR[year]
        np.testing.assert_allclose(float(item["equilibrium"]["price"]), price, rtol=0, atol=0)
        np.testing.assert_allclose(
            float(item["banking_floor_cancelled"]), cancelled, rtol=0, atol=0
        )
        np.testing.assert_allclose(float(item["banking_aggregate_bank"]), bank, rtol=0, atol=0)
        np.testing.assert_allclose(float(item["equilibrium"]["auction_sold"]), sold, rtol=0, atol=0)
        assert item["banking_regime"] == "hotelling"
        assert (item["banking_window_start"], item["banking_window_end"]) == (0, 1)


# ── Contract shape (economist verdict 1c) ────────────────────────────────────


def test_delivered_floor_satisfies_price_overlay():
    assert isinstance(DeliveredFloor(), PriceOverlay)


def test_floor_cancellation_rule_is_deliberately_not_a_supply_rule():
    """1c: the rule composes on the contemporaneous-year supply in a dedicated
    host slot (after the supply rules), not the lagged Observables — so it must
    NOT conform to the SupplyRule protocol."""
    assert not isinstance(FloorCancellationRule(), SupplyRule)


# ── Closed form: the rule in isolation ───────────────────────────────────────


def _floor_market(floor: float, unsold: str):
    cfg = {
        "scenarios": [
            {
                "name": "one-year",
                "model_approach": "competitive",
                "years": _years([85.0], floors=[floor], unsold=unsold),
            }
        ]
    }
    return build_markets_from_config(cfg)[0]


def test_binding_floor_cancels_the_unsold_volume():
    """u = S − e(F) = 85 − (100 − 2500/100) = 10; supply replaced by e(F)."""
    supply, cancelled = FloorCancellationRule().apply_to_year(
        _floor_market(2500.0, "cancel"), solved_price=1024.4, supply=85.0
    )
    np.testing.assert_allclose(cancelled, 10.0, rtol=0, atol=1e-6)
    np.testing.assert_allclose(supply, 75.0, rtol=0, atol=1e-6)


def test_non_binding_floor_is_a_no_op():
    """Floor slack by the contemporaneous test e(F) >= S: with supply 50 and
    e(F) = 100 - 2500/100 = 75, demand-at-floor exceeds supply, so nothing is
    unsold and supply passes through untouched. The rule is price-free — it no
    longer reads ``solved_price`` (a stale price above the floor no longer
    fakes a no-op); see ``test_floor_cancellation.py`` V2 for the anchor."""
    supply, cancelled = FloorCancellationRule().apply_to_year(
        _floor_market(2500.0, "cancel"), solved_price=3000.0, supply=50.0
    )
    assert (supply, cancelled) == (50.0, 0.0)


def test_reserve_treatment_never_cancels():
    """unsold_treatment != "cancel": the floor binds but nothing is removed
    from circulation (the unsold volume is reserved, not cancelled)."""
    supply, cancelled = FloorCancellationRule().apply_to_year(
        _floor_market(2500.0, "reserve"), solved_price=1024.4, supply=85.0
    )
    assert (supply, cancelled) == (85.0, 0.0)


# ── Legacy equivalence: the banking fixed point with the injected rule ───────


def test_default_slot_reproduces_the_pre_refactor_numbers():
    """Default wiring (None -> FloorCancellationRule + DeliveredFloor) must
    reproduce the pre-extraction solver bit-for-bit."""
    path = solve_banking_path(build_markets_from_config(_floor_binding_config()), discount_rate=R)
    _assert_matches_anchor(path)


def test_explicitly_injected_floor_rule_matches_the_default():
    """Injecting the factory by hand (what engine/wiring.py will do) is the
    same equilibrium as the attach-always default."""
    path = solve_banking_path(
        build_markets_from_config(_floor_binding_config()),
        discount_rate=R,
        floor_rule_factory=FloorCancellationRule,
    )
    _assert_matches_anchor(path)


def test_neutral_floor_rule_disables_cancellation_but_not_the_delivered_clip():
    """Slot discriminator: a neutral rule turns the cancellation feedback off
    (supply keeps the full 85 Mt in 2031 -> P_0 = c(2E − 180)/(2 + r)), while
    the DELIVERED price still clips to the floor — cancellation (supply
    channel) and the clip (price overlay) are separate mechanisms."""

    class _NeutralFloorRule:
        def apply_to_year(self, market, solved_price, supply):
            return supply, 0.0

    path = solve_banking_path(
        build_markets_from_config(_floor_binding_config()),
        discount_rate=R,
        floor_rule_factory=_NeutralFloorRule,
    )
    p0_no_cancel = C * (2 * E - 95.0 - 85.0) / (2.0 + R)  # 975.61
    np.testing.assert_allclose(float(path[0]["equilibrium"]["price"]), p0_no_cancel, rtol=1e-5)
    # Clip-last still delivers the floor in 2031 (solved 1024.4 -> 2500).
    np.testing.assert_allclose(float(path[1]["equilibrium"]["price"]), 2500.0, rtol=0, atol=0)
    np.testing.assert_allclose(float(path[1]["banking_floor_cancelled"]), 0.0, rtol=0, atol=0)
    # And it really is a different equilibrium from the cancelling anchor.
    assert abs(float(path[0]["equilibrium"]["price"]) - _PRE_REFACTOR_ANCHOR["2030"][0]) > 100.0


# ── DeliveredFloor unit behaviour ────────────────────────────────────────────


def test_delivered_floor_clips_and_is_neutral_without_a_floor():
    overlay = DeliveredFloor()
    floored = _floor_market(2500.0, "cancel")
    unfloored = _floor_market(0.0, "reserve")
    np.testing.assert_allclose(overlay.delivered(1024.4, floored), 2500.0, rtol=0, atol=0)
    np.testing.assert_allclose(overlay.delivered(3000.0, floored), 3000.0, rtol=0, atol=0)
    # Attach-always exactness: max(p, 0) = p for every solved p >= 0.
    for p in (0.0, 17.3, 4000.0):
        assert overlay.delivered(p, unfloored) == p


# ── Trajectory arms (config door) ────────────────────────────────────────────


def test_apply_price_bound_trajectories_interpolates_and_passes_through():
    meta = {
        "price_floor_trajectory": {
            "start_year": "2030",
            "end_year": "2032",
            "start_value": 10.0,
            "end_value": 30.0,
        },
        "price_ceiling_trajectory": {},
    }
    lower, upper = apply_price_bound_trajectories(
        2031.0, meta, 5.0, 99.0, interp_value=_interp_value
    )
    np.testing.assert_allclose(lower, 20.0, rtol=0, atol=1e-9)  # midpoint
    assert upper == 99.0  # absent trajectory leaves the per-year value

    lower, upper = apply_price_bound_trajectories(
        2031.0, {}, None, None, interp_value=_interp_value
    )
    assert lower is None and upper is None  # fully unconfigured: no-op


@pytest.mark.parametrize(
    "traj_key,bound_attr,values",
    [
        ("price_floor_trajectory", "price_lower_bound", (100.0, 200.0, 300.0)),
        ("price_ceiling_trajectory", "price_upper_bound", (50000.0, 60000.0, 70000.0)),
    ],
)
def test_builder_end_to_end_trajectory_override(traj_key, bound_attr, values):
    """The extracted arm patches the built markets exactly as the inline
    builder code did: linear interpolation, endpoint clamping, override of
    the per-year bound."""
    cfg = {
        "scenarios": [
            {
                "name": "trajectory",
                "model_approach": "competitive",
                traj_key: {
                    "start_year": "2030",
                    "end_year": "2032",
                    "start_value": values[0],
                    "end_value": values[2],
                },
                "years": _years([95.0, 85.0, 75.0]),
            }
        ]
    }
    markets = sorted(build_markets_from_config(cfg), key=lambda m: str(m.year))
    for market, expected in zip(markets, values, strict=True):
        np.testing.assert_allclose(float(getattr(market, bound_attr)), expected, rtol=0, atol=1e-9)


def test_summary_reports_the_delivered_floor_price():
    """End-to-end through run_simulation: the 2031 summary price is the
    floor (2500), the cancellation shows in the diagnostics column."""
    summary, _ = run_simulation_from_config(_floor_binding_config())
    prices = dict(zip(summary["Year"], summary["Equilibrium Carbon Price"]))
    cancelled = dict(zip(summary["Year"], summary["Banking Floor Cancelled"]))
    np.testing.assert_allclose(prices["2031"], 2500.0, rtol=0, atol=0)
    np.testing.assert_allclose(prices["2030"], _PRE_REFACTOR_ANCHOR["2030"][0], rtol=0, atol=0)
    np.testing.assert_allclose(cancelled["2031"], 10.0, rtol=0, atol=1e-6)
