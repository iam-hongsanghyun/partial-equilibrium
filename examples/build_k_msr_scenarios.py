"""Generate the four K-MSR paper scenarios as standalone, runnable configs.

Paper: PLANiT "Leading Carbon Prices to an Irreversible Industrial Transition"
(working paper, July 2026), calibrated to the K-ETS partial-equilibrium model
v1.0 in this repository.

This writes four self-contained example files plus a combined compare suite,
each loadable directly:

    python -m ets.cli --config examples/k_msr_P0_no_reserve.json
    python -m ets.cli --config examples/k_msr_P1_draft_decree.json
    python -m ets.cli --config examples/k_msr_A_reserve_price.json
    python -m ets.cli --config examples/k_msr_B_quantity_rule.json
    python -m ets.cli --config examples/k_msr_compare_suite.json   # all four

Scenario map (paper Section 3):
    P0  no reserve, benchmark.
    P1  draft decree: reprofile supply within the cap (absorb early, release
        later), cumulative cap unchanged -> cap-neutral (waterbed).
    A   price rule: auction reserve price rising 22,750 -> 97,500 KRW by 2035,
        unsold volume cancelled in full.
    B   quantity rule: pre-announced absorption of 50% of auction volume from
        2035, cancelled in full.

Base calibration is the repo's "K-ETS Outlook — Base (current policy)".
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_FILE = HERE / "climate_solutions_k_ets_outlook.json"

RESERVE_2026, RESERVE_2035 = 22_750, 97_500
RESERVE_START, RESERVE_END = 2026, 2035


def base_years() -> list[dict]:
    cfg = json.load(open(BASE_FILE))
    return copy.deepcopy(cfg["scenarios"][0]["years"])


def as_competitive(years: list[dict]) -> list[dict]:
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


def reserve_price(year: int) -> int:
    if year >= RESERVE_END:
        return RESERVE_2035
    frac = (year - RESERVE_START) / (RESERVE_END - RESERVE_START)
    return round(RESERVE_2026 + (RESERVE_2035 - RESERVE_2026) * frac)


def make_p0() -> list[dict]:
    return as_competitive(base_years())


def make_p1() -> list[dict]:
    """Reprofile the cap: -15 Mt in 2028-2030, +15 Mt in 2031-2033.

    Cumulative cap over 2026-2040 is unchanged, so the reserve moves *when*
    allowances arrive, not *how many* cumulatively exist -> cap-neutral.
    """
    ys = as_competitive(base_years())
    absorb = 15.0
    for y in ys:
        yr = int(y["year"])
        if 2028 <= yr <= 2030:
            y["total_cap"] = float(y["total_cap"]) - absorb
        if 2031 <= yr <= 2033:
            y["total_cap"] = float(y["total_cap"]) + absorb
    return ys


def make_a() -> list[dict]:
    """Price rule: rising auction reserve price, unsold volume cancelled."""
    ys = as_competitive(base_years())
    for y in ys:
        y["auction_reserve_price"] = reserve_price(int(y["year"]))
        y["unsold_treatment"] = "cancel"
    return ys


B_CANCEL_PER_YEAR = 15.0  # Mt/yr pre-announced cancellation from 2035

def make_b() -> list[dict]:
    """Quantity rule: a pre-announced fixed quantity cancelled each year from 2035.

    The paper's rule B is "absorb 50% of auction volume from 2035, cancelled in
    full". In this calibration free allocation is 0, so the whole cap is
    auctioned and a literal 50% is far larger than total abatement capacity
    (the clearing price would run to the penalty ceiling — itself an instance of
    the paper's scale wall). We therefore represent the quantity-rule archetype
    with a feasible pre-committed volume (15 Mt/yr), which is what the engine can
    clear; the point it illustrates — a quantity commitment moves the level in
    uncontrolled MAC-step jumps, unlike the smoothly pinned price floor of rule
    A — is unchanged.
    """
    ys = as_competitive(base_years())
    for y in ys:
        if int(y["year"]) >= 2035:
            y["cancelled_allowances"] = B_CANCEL_PER_YEAR
    return ys


def scenario(name: str, years: list[dict], extra: dict | None = None) -> dict:
    s = {
        "name": name,
        "model_approach": "competitive",
        "discount_rate": 0.055,
        "solver_penalty_price_multiplier": 1.05,
        "years": years,
    }
    if extra:
        s.update(extra)
    return s


def main() -> None:
    specs = {
        "k_msr_P0_no_reserve.json": scenario("P0 — no reserve (benchmark)", make_p0()),
        "k_msr_P1_draft_decree.json": scenario("P1 — draft decree (reprofile, cap-neutral)", make_p1()),
        "k_msr_A_reserve_price.json": scenario("A — reserve price 22,750→97,500 + cancel", make_a()),
        "k_msr_B_quantity_rule.json": scenario("B — quantity rule (cancel 50% from 2035)", make_b()),
    }
    for fname, scen in specs.items():
        json.dump({"scenarios": [scen]}, open(HERE / fname, "w"), ensure_ascii=False, indent=2)
        print(f"wrote {fname}  ({len(scen['years'])} years, "
              f"{len(scen['years'][0]['participants'])} sectors)")

    suite = {"scenarios": [
        scenario("P0 — no reserve (benchmark)", make_p0()),
        scenario("P1 — draft decree (reprofile, cap-neutral)", make_p1()),
        scenario("A — reserve price 22,750→97,500 + cancel", make_a()),
        scenario("B — quantity rule (cancel 50% from 2035)", make_b()),
    ]}
    json.dump(suite, open(HERE / "k_msr_compare_suite.json", "w"), ensure_ascii=False, indent=2)
    print("wrote k_msr_compare_suite.json  (all four scenarios)")


if __name__ == "__main__":
    main()
