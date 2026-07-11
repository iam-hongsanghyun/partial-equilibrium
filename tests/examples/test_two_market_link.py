r"""D1-6 two-market ONE-WAY linked golden anchors (docs/platform-spec-d0-d1.md
§2 PriceLink semantics, §3 recursive-PE DAG, §7 E4/E8).

``examples/showcase_two_market_link.json`` is the first end-to-end
demonstration of the D1 multi-market solve and the acyclic template the D2
cyclic goldens mirror: two competitive carbon markets joined by a SINGLE
one-way link ``upstream_ets -> downstream_sector`` on the ``mac_cost``
channel. The upstream carbon price ``P_A(t)`` shifts the downstream
electrified process's marginal abatement cost by ``phi * P_A(t)`` (spec §2a
additive-linear, §2c contemporaneous); the downstream sector is the marginal
abater so it clears exactly at its shifted MAC level.

Everything the anchors need is read from the example's OWN declared values
(``phi``, the market ids, the target participant/technology, the base MAC
threshold) or from the solved output — no hand-transcribed magic. The four
behaviours pinned here:

1. Both composite legs ``"<scenario> :: <market_id>"`` are present and solve.
2. The link fired: market B's summary rows carry the guarded
   ``"Link A->B Price In"`` and ``"Link A->B mac_cost Input Shift"`` columns,
   both non-zero, with ``shift == phi * price_in`` (channel arithmetic).
3. The link BITES: B's linked price path differs materially from B solved in
   isolation (same scenario, link stripped), by exactly ``phi * P_A(t)``.
4. ONE-WAY: A's solved price path is byte-identical whether the link/B is
   present or not (the source has no inbound edge; recursive-PE solves it
   first) — asserted with exact ``==``.

Plus a hand-check anchor (assertion set 5): B's shifted MAC intercept equals
``base + phi * P_A(t)`` to atol 1e-6, proving the channel arithmetic, not
merely that "something moved".
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from pe import run_simulation_from_config
from pe.engine.dispatch import solve_multi_market_scenario

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
EXAMPLE_PATH = EXAMPLES_DIR / "showcase_two_market_link.json"


# ── config readers (no magic beyond the example's own declared values) ──────


def _load_scenario() -> dict[str, Any]:
    raw = json.loads(EXAMPLE_PATH.read_text())
    return raw["scenarios"][0]


def _link(scenario: dict[str, Any]) -> dict[str, Any]:
    (link,) = scenario["links"]  # exactly one link in this golden
    return link


def _market_body(scenario: dict[str, Any], market_id: str) -> dict[str, Any]:
    return next(m for m in scenario["markets"] if m["market_id"] == market_id)


def _base_threshold(scenario: dict[str, Any], link: dict[str, Any]) -> float:
    """The target technology option's UNSHIFTED MAC level, read from config."""
    body = _market_body(scenario, link["to_market"])
    participant = next(
        p for p in body["years"][0]["participants"] if p["name"] == link["target_participants"][0]
    )
    option = next(
        o for o in participant["technology_options"] if o["name"] == link["target_technologies"][0]
    )
    return float(option["threshold_cost"])


def _prices(summary, market_id: str) -> list[float]:
    """Equilibrium price path (year order) for one market leg of the solve."""
    rows = summary[summary["Market"] == market_id]
    return [float(r["Equilibrium Carbon Price"]) for _, r in rows.iterrows()]


def _col(summary, market_id: str, column: str) -> list[float]:
    rows = summary[summary["Market"] == market_id]
    return [float(r[column]) for _, r in rows.iterrows()]


def _price_in_col(link: dict[str, Any]) -> str:
    return f"Link {link['from_market']}->{link['to_market']} Price In"


def _shift_col(link: dict[str, Any]) -> str:
    return f"Link {link['from_market']}->{link['to_market']} {link['channel']} Input Shift"


# ── Assertion 1: both legs present and solve ────────────────────────────────


def test_both_market_legs_present_and_solve() -> None:
    scenario = _load_scenario()
    summary, _ = solve_multi_market_scenario(copy.deepcopy(scenario))

    name = scenario["name"]
    link = _link(scenario)
    expected_keys = {
        f"{name} :: {link['from_market']}",
        f"{name} :: {link['to_market']}",
    }
    assert set(summary["Scenario"].unique()) == expected_keys

    # "and solve": every leg produced a finite, strictly positive price.
    for market_id in (link["from_market"], link["to_market"]):
        prices = _prices(summary, market_id)
        assert len(prices) == len(_market_body(scenario, market_id)["years"])
        assert all(np.isfinite(p) and p > 0.0 for p in prices), (market_id, prices)


# ── Assertion 2: the link fired (diagnostics present, non-zero, consistent) ──


def test_link_diagnostics_present_and_nonzero() -> None:
    scenario = _load_scenario()
    link = _link(scenario)
    phi = float(link["phi"])
    summary, _ = solve_multi_market_scenario(copy.deepcopy(scenario))

    price_in_col = _price_in_col(link)
    shift_col = _shift_col(link)
    b_rows = summary[summary["Market"] == link["to_market"]]

    # Guarded columns are PRESENT on the target market's rows.
    assert price_in_col in summary.columns
    assert shift_col in summary.columns
    assert b_rows[price_in_col].notna().all()
    assert b_rows[shift_col].notna().all()

    price_in = _col(summary, link["to_market"], price_in_col)
    shift = _col(summary, link["to_market"], shift_col)

    # Non-zero (the link actually fired every year).
    assert all(abs(p) > 0.0 for p in price_in), price_in
    assert all(abs(s) > 0.0 for s in shift), shift

    # Channel arithmetic: the input shift IS phi * P_A(t), exactly.
    np.testing.assert_allclose(shift, [phi * p for p in price_in], rtol=0, atol=0)

    # The "Price In" is A's OWN solved delivered price (the E4 source path).
    np.testing.assert_allclose(price_in, _prices(summary, link["from_market"]), rtol=0, atol=0)


# ── Assertion 3: the link BITES (linked vs isolation) ───────────────────────


def test_link_bites_downstream_vs_isolation() -> None:
    scenario = _load_scenario()
    link = _link(scenario)
    phi = float(link["phi"])

    summary_linked, _ = solve_multi_market_scenario(copy.deepcopy(scenario))
    b_linked = _prices(summary_linked, link["to_market"])

    # B in ISOLATION: the identical two-market scenario with the link stripped
    # (spec §6 inertness default links=[]), so B solves on its unshifted MAC.
    isolated = copy.deepcopy(scenario)
    isolated["links"] = []
    summary_iso, _ = solve_multi_market_scenario(isolated)
    b_isolated = _prices(summary_iso, link["to_market"])

    delta = [linked - iso for linked, iso in zip(b_linked, b_isolated, strict=True)]

    # Material at every year (the smallest bite here is phi * min(P_A) = 10).
    assert min(delta) > 1.0, delta
    # And the bite is exactly phi * P_A(t) (the mac_cost shift, contemporaneous).
    price_in = _col(summary_linked, link["to_market"], _price_in_col(link))
    np.testing.assert_allclose(delta, [phi * p for p in price_in], rtol=0, atol=1e-6)
    # Concrete numbers for the record: base 40 -> [50, 57.5, 67.5] with the
    # link vs [40, 40, 40] without.
    np.testing.assert_allclose(b_linked, [50.0, 57.5, 67.5], rtol=0, atol=1e-6)
    np.testing.assert_allclose(b_isolated, [40.0, 40.0, 40.0], rtol=0, atol=1e-6)


# ── Assertion 4: ONE-WAY — the source is byte-identical, link or no link ─────


def test_one_way_source_price_byte_identical() -> None:
    scenario = _load_scenario()
    link = _link(scenario)
    source_id = link["from_market"]

    summary_linked, _ = solve_multi_market_scenario(copy.deepcopy(scenario))
    a_linked = _prices(summary_linked, source_id)

    # Same two markets, link stripped: A must not move (no inbound edge).
    stripped = copy.deepcopy(scenario)
    stripped["links"] = []
    summary_stripped, _ = solve_multi_market_scenario(stripped)
    a_stripped = _prices(summary_stripped, source_id)

    assert a_linked == a_stripped, (a_linked, a_stripped)

    # And identical to A solved entirely alone (a flat single-market scenario):
    # B's very existence never perturbs the source.
    body = {k: v for k, v in _market_body(scenario, source_id).items() if k != "market_id"}
    body["name"] = "upstream_ets standalone"
    summary_alone, _ = run_simulation_from_config({"scenarios": [body]})
    a_alone = [float(r["Equilibrium Carbon Price"]) for _, r in summary_alone.iterrows()]

    assert a_linked == a_alone, (a_linked, a_alone)


# ── Assertion 5: hand check — shifted MAC intercept == base + phi * P_A(t) ───


def test_shifted_mac_intercept_hand_check() -> None:
    scenario = _load_scenario()
    link = _link(scenario)
    phi = float(link["phi"])
    base = _base_threshold(scenario, link)

    summary, _ = solve_multi_market_scenario(copy.deepcopy(scenario))
    b_prices = _prices(summary, link["to_market"])
    price_in = _col(summary, link["to_market"], _price_in_col(link))

    # B is the marginal abater, so its clearing price IS its shifted MAC
    # intercept: base threshold + phi * P_A(t) (proves the channel arithmetic,
    # not merely that the price changed).
    expected = [base + phi * p for p in price_in]
    np.testing.assert_allclose(b_prices, expected, rtol=0, atol=1e-6)


# ── example vocabulary sanity (mirrors test_rps_showcase's normalize check) ──


def test_example_declares_linked_market_price_units() -> None:
    """Every linked market declares price_unit (spec §2e/§6) and the link is
    a single acyclic mac_cost edge (the D1 template, not a D2 cycle)."""
    scenario = _load_scenario()
    link = _link(scenario)
    assert link["channel"] == "mac_cost"
    assert link["from_market"] != link["to_market"]  # no self-link (R34)
    for market_id in (link["from_market"], link["to_market"]):
        assert _market_body(scenario, market_id)["price_unit"]
