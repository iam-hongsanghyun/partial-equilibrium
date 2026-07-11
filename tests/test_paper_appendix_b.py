"""Reproduction scoreboard: K-MSR paper Appendix B anchors vs this repository.

Every test asserts one published anchor from the paper's Appendix B
("Numerical verification") against a fresh solve on the repository's shipped
calibration (v0.6) under the banking equilibrium solver with the paper's
carried-in bank (89 Mt) and r = 5.5 %.

Verdict convention:
- plain assert           → PASS: reproduced within the stated tolerance.
- xfail(strict=True)     → documented miss with its driver in the reason;
                           if calibration work closes it, the xfail fails and
                           the win must be promoted to a plain assert.

Paper values: PLANiT K-MSR working paper (July 2026), Appendix B; transcribed
in docs/k-msr-vs-repo-comparison.md.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from pe.config_io import build_markets_from_config
from pe.engine import solve_banking_path

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

PAPER = {
    "p0_2026": 22_691.0,
    "p0_2030": 41_355.0,
    "p0_2035_cancellation_baseline": 54_445.0,
    "p0_2040": 67_461.0,
    "bank_2026": 89.0,
    "bank_peak": 114.0,
    "bank_peak_years": {2028, 2029},
    "bank_exhaustion_year": 2039,
    "discount_rate": 0.055,
}


@pytest.fixture(scope="module")
def p0_banking_path() -> dict[str, dict[str, float]]:
    """Solve the K-ETS Base P0 once under the banking equilibrium."""
    cfg = json.load(open(EXAMPLES / "k_msr_P0_no_reserve.json"))
    scen = copy.deepcopy(cfg["scenarios"][0])
    scen["model_approach"] = "banking"
    markets = build_markets_from_config({"scenarios": [scen]})
    path = solve_banking_path(
        markets,
        discount_rate=PAPER["discount_rate"],
        initial_bank=PAPER["bank_2026"],
    )
    return {
        "price": {str(i["market"].year): float(i["equilibrium"]["price"]) for i in path},
        "bank": {
            str(i["market"].year): float(i["banking_aggregate_bank"]) for i in path
        },
    }


# ── PASS: structure and terminal level ───────────────────────────────────────


def test_p0_2040_terminal_level(p0_banking_path):
    """Paper 67,461; v0.6 banking solve lands +0.5 % — the cumulative
    cap–BAU balance of the two calibration vintages nearly agrees."""
    np.testing.assert_allclose(
        p0_banking_path["price"]["2040"], PAPER["p0_2040"], rtol=7.5e-3
    )


def test_bank_exhausts_by_2039(p0_banking_path):
    """Paper: bank draws to zero by 2039. Tolerance 5 Mt — the discrete MAC
    leaves a residual because demand is a step correspondence."""
    assert p0_banking_path["bank"]["2039"] <= 5.0


def test_bank_peaks_in_2028_or_2029(p0_banking_path):
    bank = p0_banking_path["bank"]
    peak_year = max(bank, key=lambda y: bank[y])
    assert int(peak_year) in PAPER["bank_peak_years"]


def test_hotelling_carry_inside_window(p0_banking_path):
    """Within the banking window the path must rise at exactly r = 5.5 %/yr
    (the paper's A.1 no-arbitrage rule)."""
    price = p0_banking_path["price"]
    for year in range(2027, 2039):
        np.testing.assert_allclose(
            price[str(year + 1)] / price[str(year)],
            1.0 + PAPER["discount_rate"],
            rtol=1e-3,
        )


# ── Documented misses (drivers in the reasons) ───────────────────────────────


@pytest.mark.xfail(
    strict=True,
    reason="Driver: calibration vintage. v0.6 gives 40,511 (−2.0%); needs the "
    "unpublished v1.0 MAC/cap tables (Phase 0) to close below 1%.",
)
def test_p0_2030(p0_banking_path):
    np.testing.assert_allclose(
        p0_banking_path["price"]["2030"], PAPER["p0_2030"], rtol=1e-2
    )


@pytest.mark.xfail(
    strict=True,
    reason="Driver: calibration vintage. v0.6 gives 52,947 (−2.8%) for the "
    "cancellation-exercise baseline.",
)
def test_p0_2035_cancellation_baseline(p0_banking_path):
    np.testing.assert_allclose(
        p0_banking_path["price"]["2035"],
        PAPER["p0_2035_cancellation_baseline"],
        rtol=1e-2,
    )


@pytest.mark.xfail(
    strict=True,
    reason="Driver: spec + calibration. The paper's 2026 price sits on a "
    "hoarding-shaped static segment (rising ≈16%/yr while the bank grows — "
    "textbook no-arbitrage violated, the paper's own λ≈0 reading). The "
    "standard equilibrium opens the window in 2026 and prices 32,701. "
    "Representable via per-year hoarding_inflow once v1.0 MACs and the "
    "hoarding series are known (see modules/banking/doc/reference.md).",
)
def test_p0_2026(p0_banking_path):
    np.testing.assert_allclose(
        p0_banking_path["price"]["2026"], PAPER["p0_2026"], rtol=1e-2
    )


@pytest.mark.xfail(
    strict=True,
    reason="Driver: calibration vintage. v0.6 bank peaks at 130.3 Mt vs the "
    "paper's 114 Mt (+14%): early-year MAC steps put more surplus in the bank.",
)
def test_bank_peak_magnitude(p0_banking_path):
    bank = p0_banking_path["bank"]
    np.testing.assert_allclose(max(bank.values()), PAPER["bank_peak"], rtol=5e-2)
