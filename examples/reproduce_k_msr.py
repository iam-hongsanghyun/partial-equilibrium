"""Reproduce the four-scenario design of the PLANiT K-MSR working paper.

Paper: "Leading Carbon Prices to an Irreversible Industrial Transition:
Instrument Choice for a Market Stability Reserve under Weak Forward
Transmission" (working paper, July 2026). The paper is calibrated to the
K-ETS partial-equilibrium model v1.0 (MAC curve + banking/Hotelling price
rule) — i.e. the engine in this repository.

This script re-runs, end to end, the paper's three headline results using the
repository's own K-ETS Outlook (Base) calibration as the benchmark path P0:

  Result 1 (cap-neutrality + scale wall, paper Section 4)
    - A reserve that reprofiles supply within the cap is level-neutral.
    - Permanent cancellation shifts the level, but the cancellable stock is
      too small to lead: retiring 155 Mt raises the 2035 price by only a
      fraction of the rise the H2-DRI threshold requires.

  Result 2/3 (a price rule leads the level, paper Sections 5-6)
    - An auction reserve price pre-announced to rise 22,750 -> 97,500 KRW by
      2035, with unsold volume cancelled, pins the realised price to the floor
      and reaches the (declining) steel activation threshold.

Run:
    PYTHONPATH=src python examples/reproduce_k_msr.py

Outputs (written next to this script):
    k_msr_results.csv        full price paths, one row per scenario-year
    k_msr_summary.md         the paper-style comparison tables
    k_msr_price_paths.png    chart of P0 vs A and the cancellation sweep
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd

from ets.simulation import run_simulation_from_config

HERE = Path(__file__).resolve().parent
BASE_FILE = HERE / "climate_solutions_k_ets_outlook.json"

# Paper anchors (Section 3-4, model v1.0). Used only for the comparison print.
PAPER = {
    "p0_2040": 67461,          # no-policy KAU by 2040 (KRW/tCO2)
    "steel_threshold_2035": 97500,  # H2-DRI break-even by 2035
    "reserve_2026": 22750,     # rule A auction reserve price, 2026
    "reserve_2035": 97500,     # rule A auction reserve price, 2035
    "required_rise_2035": 43055,    # KRW the 2035 threshold requires over P0
    # cancellation sweep: Mt -> % of the required 2035 rise it closes (paper)
    "cancel_pct": {32: 4.0, 64: 7.9, 96: 14.7, 128: 22.5, 155: 26.0},
}

RESERVE_START_YEAR, RESERVE_END_YEAR = 2026, 2035


def load_base_years() -> list[dict]:
    cfg = json.load(open(BASE_FILE))
    return copy.deepcopy(cfg["scenarios"][0]["years"])  # "Base (current policy)"


def as_competitive(years: list[dict]) -> list[dict]:
    """Recast the Hotelling Base years as a competitive, cap-cleared path.

    Free allocation is 0 in the Base calibration, so ``derive_from_cap`` makes
    the whole cap the auction volume and the clearing price depends only on
    BAU - cap (the Coase property the paper relies on).
    """
    ys = copy.deepcopy(years)
    for y in ys:
        y["auction_mode"] = "derive_from_cap"
        y["banking_allowed"] = False
        y["borrowing_allowed"] = False
        y["expectation_rule"] = "next_year_baseline"
        y["price_lower_bound"] = 0.0
        y["price_upper_bound"] = 300_000.0
        y.pop("carbon_budget", None)
    return ys


def run(name: str, years: list[dict], extra: dict | None = None) -> pd.DataFrame:
    scen = {
        "name": name,
        "model_approach": "competitive",
        "discount_rate": 0.055,
        "solver_penalty_price_multiplier": 1.05,
        "years": years,
    }
    if extra:
        scen.update(extra)
    summary, _ = run_simulation_from_config({"scenarios": [scen]})
    summary = summary[["Scenario", "Year", "Equilibrium Carbon Price"]].copy()
    summary["Scenario"] = name
    return summary


def reserve_price(year: int) -> float:
    """Rule A: auction reserve price rising 22,750 -> 97,500 by 2035, then held."""
    if year >= RESERVE_END_YEAR:
        return float(PAPER["reserve_2035"])
    frac = (year - RESERVE_START_YEAR) / (RESERVE_END_YEAR - RESERVE_START_YEAR)
    return round(PAPER["reserve_2026"] + (PAPER["reserve_2035"] - PAPER["reserve_2026"]) * frac)


def build_scenarios() -> dict[str, list[dict]]:
    base = load_base_years()
    scen: dict[str, list[dict]] = {}

    # P0 — no reserve, benchmark.
    scen["P0 (no reserve)"] = as_competitive(base)

    # A — price rule: rising auction reserve price, unsold volume cancelled.
    ys = as_competitive(base)
    for y in ys:
        y["auction_reserve_price"] = reserve_price(int(y["year"]))
        y["unsold_treatment"] = "cancel"
    scen["A (reserve price + cancel)"] = ys

    # P1 — reserve that reprofiles supply within the cap (absorb early, release
    # later), cumulative supply unchanged -> cap-neutral (waterbed). The builder
    # validates supply <= total_cap, so the reprofile is expressed on the cap
    # itself with ``derive_from_cap`` (as in k_msr_P1_draft_decree.json).
    ys = as_competitive(base)
    absorb = 15.0
    for y in ys:
        yr = int(y["year"])
        if 2028 <= yr <= 2030:
            y["total_cap"] = float(y["total_cap"]) - absorb   # absorb
        if 2031 <= yr <= 2033:
            y["total_cap"] = float(y["total_cap"]) + absorb   # release the same total
    scen["P1 (reprofile, no cancel)"] = ys

    return scen


def cancellation_sweep(base_years: list[dict]) -> pd.DataFrame:
    """Retire Q Mt of the cancellable stock, spread evenly over 2027-2035."""
    rows = []
    p0 = run("P0", as_competitive(base_years))
    p0_2035 = float(p0.loc[p0.Year == "2035", "Equilibrium Carbon Price"].iloc[0])
    for Q in [16, 32, 64, 96, 128, 155]:
        ys = as_competitive(base_years)
        window = [y for y in ys if 2027 <= int(y["year"]) <= 2035]
        per = Q / len(window)
        for y in window:
            y["cancelled_allowances"] = per
        r = run(f"cancel_{Q}", ys)
        price_2035 = float(r.loc[r.Year == "2035", "Equilibrium Carbon Price"].iloc[0])
        rise = price_2035 - p0_2035
        rows.append(
            {
                "Cancelled (Mt)": Q,
                "2035 price (KRW)": round(price_2035),
                "Rise vs P0 (KRW)": round(rise),
                "% of required rise": round(100 * rise / PAPER["required_rise_2035"], 1),
                "Paper % (ref)": PAPER["cancel_pct"].get(Q, ""),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    base = load_base_years()

    # --- Four-scenario price paths -------------------------------------------
    scen = build_scenarios()
    frames = [run(name, years) for name, years in scen.items()]
    paths = pd.concat(frames, ignore_index=True)
    paths.to_csv(HERE / "k_msr_results.csv", index=False)

    wide = paths.pivot(index="Year", columns="Scenario",
                       values="Equilibrium Carbon Price").round(0).astype(int)
    wide = wide[list(scen.keys())]

    # --- Cancellation sweep ---------------------------------------------------
    sweep = cancellation_sweep(base)

    # --- Report ---------------------------------------------------------------
    lines = []
    lines.append("# K-MSR paper — reproduction on the K-ETS v1.0 engine\n")
    lines.append("## Price paths by scenario (KRW/tCO2)\n")
    lines.append(wide.to_markdown())
    p0_2040 = int(wide.loc["2040", "P0 (no reserve)"])
    a_2035 = int(wide.loc["2035", "A (reserve price + cancel)"])
    lines.append(
        f"\n- P0 2040 = {p0_2040:,} KRW  (paper: {PAPER['p0_2040']:,})"
        f"\n- A 2035 = {a_2035:,} KRW, hitting the steel threshold "
        f"{PAPER['steel_threshold_2035']:,}"
        "\n- P1 reprofiles supply within the cap and returns to the P0 level "
        "(cap-neutral / waterbed).\n"
    )
    lines.append("## Cancellation sweep — the scale wall (2035)\n")
    lines.append(sweep.to_markdown(index=False))
    lines.append(
        "\nRetiring the full ~155 Mt cancellable stock closes only a fraction "
        "of the rise the 2035 threshold requires: scarcity alone cannot lead "
        "the level — the leading instrument must act on the auction flow "
        "(a reserve price).\n"
    )
    report = "\n".join(lines)
    (HERE / "k_msr_summary.md").write_text(report)
    print(report)

    # --- Chart ----------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 5.2))
        years = [int(y) for y in wide.index]
        for col, style in [
            ("P0 (no reserve)", "o-"),
            ("A (reserve price + cancel)", "s-"),
            ("P1 (reprofile, no cancel)", "^--"),
        ]:
            ax.plot(years, wide[col].values, style, label=col, linewidth=2)
        ax.axhline(PAPER["steel_threshold_2035"], color="grey", ls=":",
                   label="H2-DRI steel threshold 2035 (97,500)")
        ax.set_xlabel("Year")
        ax.set_ylabel("Carbon price (KRW/tCO2)")
        ax.set_title("K-MSR reproduction: instrument choice and the price level")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(HERE / "k_msr_price_paths.png", dpi=140)
        print(f"\nChart written to {HERE / 'k_msr_price_paths.png'}")
    except Exception as exc:  # pragma: no cover
        print(f"[chart skipped: {exc}]")


if __name__ == "__main__":
    main()
