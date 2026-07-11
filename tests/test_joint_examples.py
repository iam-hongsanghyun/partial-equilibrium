"""Anchor tests for the flagship JOINT-equilibrium examples.

These sit alongside the golden-replay gate (``test_golden_baselines.py``) and
pin the ECONOMICS of the two headline cyclic examples to their hand fixed
points, derived from each config's OWN declared parameters (no magic numbers):

* ``joint_two_market`` -- a converging cyclic SCC (loop gain g=0.20) that must
  hit the linear-2x2 hand fixed point and stamp ``Joint Converged=1``;
* ``joint_oscillating`` -- a high-gain cyclic SCC (g=-1.50) that must CONVERGE
  to its hand fixed point at the shipped ``relaxation=0.5`` and OSCILLATE
  (``Joint Converged=0`` AND ``Joint Cycle Detected=2``) at ``relaxation=1.0``.

For both, each interior single-block threshold market pins at its (link-shifted)
block cost, so own-price pass-through s_m=1 and the closed-form fixed point is

    P_A = (c_A + phi_A*c_B) / (1 - g),   P_B = (c_B + phi_B*c_A) / (1 - g),
    g = phi_A * phi_B

with c_m the block threshold_cost and phi_m the coefficient of the link INTO
market m (docs/joint-equilibrium.md section 7).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from pe import run_simulation_from_config

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
PRICE_ATOL = 1e-6


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / f"{name}.json").read_text())


def _hand_fixed_point(config: dict) -> dict[str, float]:
    """Derive the closed-form joint fixed point from the config's declared values.

    Reads each market's single block threshold_cost c_m and each link's phi
    (the coefficient into its ``to_market``), then evaluates the linear-2x2
    joint fixed point. No hardcoded prices -- everything comes from the config.
    """
    scenario = config["scenarios"][0]
    c = {}
    for market in scenario["markets"]:
        options = market["years"][0]["participants"][0]["technology_options"]
        # The cheapest (only, or incumbent) block cost is the market intercept
        # c_m in the un-adopted regime these anchors sit in.
        c[market["market_id"]] = float(options[0]["threshold_cost"])
    phi_into = {link["to_market"]: float(link["phi"]) for link in scenario["links"]}
    ids = [m["market_id"] for m in scenario["markets"]]
    a, b = ids[0], ids[1]
    phi_a, phi_b = phi_into[a], phi_into[b]
    g = phi_a * phi_b
    p_a = (c[a] + phi_a * c[b]) / (1.0 - g)
    p_b = (c[b] + phi_b * c[a]) / (1.0 - g)
    return {a: p_a, b: p_b}


def _prices_by_market(summary) -> dict[str, float]:
    return {
        str(row["Market"]): float(row["Equilibrium Carbon Price"]) for _, row in summary.iterrows()
    }


# ── joint_two_market: converging flagship ────────────────────────────────────


def test_joint_two_market_hits_hand_fixed_point_and_converges() -> None:
    """The flagship converges to the linear-2x2 hand fixed point (165.0, 162.5)."""
    config = _load("joint_two_market")
    expected = _hand_fixed_point(config)  # {"A": 165.0, "B": 162.5}

    summary, _ = run_simulation_from_config(config)
    prices = _prices_by_market(summary)

    for market_id, target in expected.items():
        np.testing.assert_allclose(prices[market_id], target, rtol=0.0, atol=PRICE_ATOL)

    # Every cyclic-SCC row is a genuine converged equilibrium, no cycle.
    assert all(summary["Joint Converged"] == 1.0)
    assert all(summary["Joint Cycle Detected"] == 0.0)
    # The hand values themselves (a guard that the derivation is the J1 anchor).
    np.testing.assert_allclose(expected[list(expected)[0]], 165.0, rtol=0, atol=PRICE_ATOL)
    np.testing.assert_allclose(expected[list(expected)[1]], 162.5, rtol=0, atol=PRICE_ATOL)


# ── joint_oscillating: damping demonstrator ──────────────────────────────────


def _with_relaxation(config: dict, w: float) -> dict:
    cfg = copy.deepcopy(config)
    cfg["scenarios"][0]["joint_solver"]["relaxation"] = w
    return cfg


def test_joint_oscillating_converges_at_shipped_relaxation() -> None:
    """As shipped (relaxation=0.5) it converges to the hand fixed point (20, 160)."""
    config = _load("joint_oscillating")
    assert config["scenarios"][0]["joint_solver"]["relaxation"] == 0.5
    expected = _hand_fixed_point(config)  # {"A": 20.0, "B": 160.0}

    summary, _ = run_simulation_from_config(config)
    prices = _prices_by_market(summary)

    for market_id, target in expected.items():
        np.testing.assert_allclose(prices[market_id], target, rtol=0.0, atol=PRICE_ATOL)
    assert all(summary["Joint Converged"] == 1.0)
    assert all(summary["Joint Cycle Detected"] == 0.0)
    np.testing.assert_allclose(expected[list(expected)[0]], 20.0, rtol=0, atol=PRICE_ATOL)
    np.testing.assert_allclose(expected[list(expected)[1]], 160.0, rtol=0, atol=PRICE_ATOL)


def test_joint_oscillating_undamped_flags_period_2_cycle() -> None:
    """At relaxation=1.0 (undamped) the SCC oscillates: Joint Converged=0 AND
    Joint Cycle Detected=2 -- never a faked equilibrium number."""
    config = _load("joint_oscillating")
    summary, _ = run_simulation_from_config(_with_relaxation(config, 1.0))

    assert all(summary["Joint Converged"] == 0.0)
    assert all(summary["Joint Cycle Detected"] == 2.0)


@pytest.mark.parametrize("w", [0.5, 1.0])
def test_joint_oscillating_relaxation_is_the_remedy(w: float) -> None:
    """Same coupling, one knob: w=0.5 converges, w=1.0 oscillates. Damping is the
    fix, not more iterations (the config ships max_iterations=200 either way)."""
    config = _load("joint_oscillating")
    summary, _ = run_simulation_from_config(_with_relaxation(config, w))
    converged = bool(all(summary["Joint Converged"] == 1.0))
    assert converged is (w == 0.5)
