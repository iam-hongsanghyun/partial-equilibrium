"""Column-order pin — reporting-host regression test (O7 fast gate).

Guards the equivalence argument for O7 (CBAM/sectors/MSR-placeholder/
CCR-placeholder reporting extraction, `docs/feature-modules-plan.md` work
order O7): every column expression relocated to
`ets.features.{cbam,sectors,msr,ccr}.plugin` is VERBATIM, dict insertion
order is reproduced by the staged literal in
`config_io/builder.py`, and reporters are ATTACH-ALWAYS so an unconfigured
scenario keeps its zero-valued columns. `tests/test_golden_baselines.py`
proves cell VALUES are unchanged but does not check column ORDER (its
diff walks dict key sets, not sequences) — this file is the column-order
gate, and it runs in seconds instead of the ~11-minute full golden replay.

The pinned literals below were captured by running the THREE reference
scenarios through the CURRENT (pre-refactor) committed code, i.e.
`ets.run_simulation_from_file` on the unmodified `core/market/reporting.py`
that this work order rewrites into a host + attached reporters (same pin-
first-then-rewrite discipline as O6's anchors). A drift in either list means
the host's staged literal, a reporter's column dict, or the reporter
attachment order in `config_io/builder.py` no longer reproduces today's
column order.

Reference scenarios (chosen for coverage of the three attach-always
reporter families):
    climate_solutions_basic_linear    — no CBAM/sector config (neutral /
                                         zero-valued CBAM + MSR/CCR columns).
    climate_solutions_cbam_exposure   — CBAM jurisdictions configured (still
                                         only fixed-name columns for these
                                         three scenarios; no dynamic
                                         per-jurisdiction/ensemble columns).
    k_ets_subsector_decomposition     — sectors configured (sector aggregate
                                         + percentile columns exercised).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ets import run_simulation_from_file
from ets.core.costs import linear_abatement_factory
from ets.core.market import CarbonMarket
from ets.core.participant import MarketParticipant

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"

_PINNED_COLUMNS: dict[str, dict[str, list[str]]] = {
    "climate_solutions_basic_linear": {
        "summary_columns": [
            "Scenario",
            "Equilibrium Carbon Price",
            "Total Abatement",
            "Total Allowance Buys",
            "Total Allowance Sells",
            "Total Penalty Emissions",
            "Total Net Allowances Traded",
            "Auction Offered",
            "Auction Sold",
            "Unsold Allowances",
            "Auction Coverage Ratio",
            "Reserved Allowances",
            "Cancelled Allowances",
            "Unallocated Allowances",
            "Total Auction Revenue",
            "Total Starting Bank",
            "Total Ending Bank",
            "Total Banked Allowances",
            "Total Borrowed Allowances",
            "Expectation Rule",
            "Manual Expected Price",
            "Total Compliance Cost",
            "EUA Price",
            "CBAM Gap",
            "Total CBAM Liability",
            "Total Cost incl. CBAM",
            "MSR Withheld",
            "MSR Released",
            "MSR Reserve Pool",
            "CCR Cap Adjustment",
            "CCR Emissions Deviation",
            "CCR Cost Deviation",
            "Year",
            "Domestic Retained Revenue",
            "CBAM Foregone Revenue",
            "Potential Revenue if KAU=EUA",
            "Total Indirect Emissions",
            "Total Scope 2 CBAM Liability",
            "Steel_BlastFurnace Technology",
            "Steel_BlastFurnace Technology Mix",
            "Steel_BlastFurnace Abatement",
            "Steel_BlastFurnace Net Trade",
            "Steel_Hydrogen_DRI Technology",
            "Steel_Hydrogen_DRI Technology Mix",
            "Steel_Hydrogen_DRI Abatement",
            "Steel_Hydrogen_DRI Net Trade",
            "Coal_Generator Technology",
            "Coal_Generator Technology Mix",
            "Coal_Generator Abatement",
            "Coal_Generator Net Trade",
            "Renewable_Generator Technology",
            "Renewable_Generator Technology Mix",
            "Renewable_Generator Abatement",
            "Renewable_Generator Net Trade",
        ],
        "participant_columns": [
            "Scenario",
            "Participant",
            "Sector Group",
            "Chosen Technology",
            "Technology Mix",
            "Initial Emissions",
            "Free Allocation",
            "Abatement",
            "Residual Emissions",
            "Allowance Buys",
            "Allowance Sells",
            "Penalty Emissions",
            "Net Allowances Traded",
            "Starting Bank Balance",
            "Ending Bank Balance",
            "Banked Allowances",
            "Borrowed Allowances",
            "Expected Future Price",
            "Fixed Technology Cost",
            "Abatement Cost",
            "Allowance Cost",
            "Penalty Cost",
            "Sales Revenue",
            "Total Compliance Cost",
            "EUA Price",
            "CBAM Gap",
            "CBAM Export Share",
            "CBAM Liable Emissions",
            "CBAM Liability",
            "Total Cost incl. CBAM",
            "Electricity Consumption",
            "Grid Emission Factor",
            "Indirect Emissions",
            "Scope 2 CBAM Coverage",
            "Scope 2 CBAM Liability",
            "Year",
        ],
    },
    "climate_solutions_cbam_exposure": {
        "summary_columns": [
            "Scenario",
            "Equilibrium Carbon Price",
            "Total Abatement",
            "Total Allowance Buys",
            "Total Allowance Sells",
            "Total Penalty Emissions",
            "Total Net Allowances Traded",
            "Auction Offered",
            "Auction Sold",
            "Unsold Allowances",
            "Auction Coverage Ratio",
            "Reserved Allowances",
            "Cancelled Allowances",
            "Unallocated Allowances",
            "Total Auction Revenue",
            "Total Starting Bank",
            "Total Ending Bank",
            "Total Banked Allowances",
            "Total Borrowed Allowances",
            "Expectation Rule",
            "Manual Expected Price",
            "Total Compliance Cost",
            "EUA Price",
            "CBAM Gap",
            "Total CBAM Liability",
            "Total Cost incl. CBAM",
            "MSR Withheld",
            "MSR Released",
            "MSR Reserve Pool",
            "CCR Cap Adjustment",
            "CCR Emissions Deviation",
            "CCR Cost Deviation",
            "Year",
            "Domestic Retained Revenue",
            "CBAM Foregone Revenue",
            "Potential Revenue if KAU=EUA",
            "Total Indirect Emissions",
            "Total Scope 2 CBAM Liability",
            "Steel Technology",
            "Steel Technology Mix",
            "Steel Abatement",
            "Steel Net Trade",
            "Petrochemical Technology",
            "Petrochemical Technology Mix",
            "Petrochemical Abatement",
            "Petrochemical Net Trade",
            "Power Technology",
            "Power Technology Mix",
            "Power Abatement",
            "Power Net Trade",
        ],
        "participant_columns": [
            "Scenario",
            "Participant",
            "Sector Group",
            "Chosen Technology",
            "Technology Mix",
            "Initial Emissions",
            "Free Allocation",
            "Abatement",
            "Residual Emissions",
            "Allowance Buys",
            "Allowance Sells",
            "Penalty Emissions",
            "Net Allowances Traded",
            "Starting Bank Balance",
            "Ending Bank Balance",
            "Banked Allowances",
            "Borrowed Allowances",
            "Expected Future Price",
            "Fixed Technology Cost",
            "Abatement Cost",
            "Allowance Cost",
            "Penalty Cost",
            "Sales Revenue",
            "Total Compliance Cost",
            "EUA Price",
            "CBAM Gap",
            "CBAM Export Share",
            "CBAM Liable Emissions",
            "CBAM Liability",
            "Total Cost incl. CBAM",
            "Electricity Consumption",
            "Grid Emission Factor",
            "Indirect Emissions",
            "Scope 2 CBAM Coverage",
            "Scope 2 CBAM Liability",
            "Year",
        ],
    },
    "k_ets_subsector_decomposition": {
        "summary_columns": [
            "Scenario",
            "Equilibrium Carbon Price",
            "Total Abatement",
            "Total Allowance Buys",
            "Total Allowance Sells",
            "Total Penalty Emissions",
            "Total Net Allowances Traded",
            "Auction Offered",
            "Auction Sold",
            "Unsold Allowances",
            "Auction Coverage Ratio",
            "Reserved Allowances",
            "Cancelled Allowances",
            "Unallocated Allowances",
            "Total Auction Revenue",
            "Total Starting Bank",
            "Total Ending Bank",
            "Total Banked Allowances",
            "Total Borrowed Allowances",
            "Expectation Rule",
            "Manual Expected Price",
            "Total Compliance Cost",
            "EUA Price",
            "CBAM Gap",
            "Total CBAM Liability",
            "Total Cost incl. CBAM",
            "MSR Withheld",
            "MSR Released",
            "MSR Reserve Pool",
            "CCR Cap Adjustment",
            "CCR Emissions Deviation",
            "CCR Cost Deviation",
            "Year",
            "Domestic Retained Revenue",
            "CBAM Foregone Revenue",
            "Potential Revenue if KAU=EUA",
            "Total Indirect Emissions",
            "Total Scope 2 CBAM Liability",
            "Petrochemical:BTX Total Abatement",
            "Petrochemical:BTX Total Compliance Cost",
            "Petrochemical:BTX Total CBAM Liability",
            "Petrochemical:BTX Allowance Buys",
            "Petrochemical:BTX Allowance Cost",
            "Petrochemical:BTX Auction Revenue Share",
            "Petrochemical:BTX Indirect Emissions",
            "Petrochemical:BTX Scope 2 CBAM Liability",
            "Petrochemical:NCC Total Abatement",
            "Petrochemical:NCC Total Compliance Cost",
            "Petrochemical:NCC Total CBAM Liability",
            "Petrochemical:NCC Allowance Buys",
            "Petrochemical:NCC Allowance Cost",
            "Petrochemical:NCC Auction Revenue Share",
            "Petrochemical:NCC Indirect Emissions",
            "Petrochemical:NCC Scope 2 CBAM Liability",
            "Steel:EAF Total Abatement",
            "Steel:EAF Total Compliance Cost",
            "Steel:EAF Total CBAM Liability",
            "Steel:EAF Allowance Buys",
            "Steel:EAF Allowance Cost",
            "Steel:EAF Auction Revenue Share",
            "Steel:EAF Indirect Emissions",
            "Steel:EAF Scope 2 CBAM Liability",
            "Steel:Integrated Total Abatement",
            "Steel:Integrated Total Compliance Cost",
            "Steel:Integrated Total CBAM Liability",
            "Steel:Integrated Allowance Buys",
            "Steel:Integrated Allowance Cost",
            "Steel:Integrated Auction Revenue Share",
            "Steel:Integrated Indirect Emissions",
            "Steel:Integrated Scope 2 CBAM Liability",
            "Petrochemical:BTX P10 Compliance Cost",
            "Petrochemical:BTX P50 Compliance Cost",
            "Petrochemical:BTX P90 Compliance Cost",
            "Petrochemical:BTX Cost Std Dev",
            "Petrochemical:NCC P10 Compliance Cost",
            "Petrochemical:NCC P50 Compliance Cost",
            "Petrochemical:NCC P90 Compliance Cost",
            "Petrochemical:NCC Cost Std Dev",
            "Steel:EAF P10 Compliance Cost",
            "Steel:EAF P50 Compliance Cost",
            "Steel:EAF P90 Compliance Cost",
            "Steel:EAF Cost Std Dev",
            "Steel:Integrated P10 Compliance Cost",
            "Steel:Integrated P50 Compliance Cost",
            "Steel:Integrated P90 Compliance Cost",
            "Steel:Integrated Cost Std Dev",
            "POSCO_Pohang_BF Technology",
            "POSCO_Pohang_BF Technology Mix",
            "POSCO_Pohang_BF Abatement",
            "POSCO_Pohang_BF Net Trade",
            "POSCO_Gwangyang_BF Technology",
            "POSCO_Gwangyang_BF Technology Mix",
            "POSCO_Gwangyang_BF Abatement",
            "POSCO_Gwangyang_BF Net Trade",
            "Hyundai_Steel_EAF Technology",
            "Hyundai_Steel_EAF Technology Mix",
            "Hyundai_Steel_EAF Abatement",
            "Hyundai_Steel_EAF Net Trade",
            "SeAH_Steel_EAF Technology",
            "SeAH_Steel_EAF Technology Mix",
            "SeAH_Steel_EAF Abatement",
            "SeAH_Steel_EAF Net Trade",
            "LG_Chem_NCC Technology",
            "LG_Chem_NCC Technology Mix",
            "LG_Chem_NCC Abatement",
            "LG_Chem_NCC Net Trade",
            "Lotte_Chemical_NCC Technology",
            "Lotte_Chemical_NCC Technology Mix",
            "Lotte_Chemical_NCC Abatement",
            "Lotte_Chemical_NCC Net Trade",
            "SK_Innovation_BTX Technology",
            "SK_Innovation_BTX Technology Mix",
            "SK_Innovation_BTX Abatement",
            "SK_Innovation_BTX Net Trade",
            "Hanwha_Solutions_BTX Technology",
            "Hanwha_Solutions_BTX Technology Mix",
            "Hanwha_Solutions_BTX Abatement",
            "Hanwha_Solutions_BTX Net Trade",
        ],
        "participant_columns": [
            "Scenario",
            "Participant",
            "Sector Group",
            "Chosen Technology",
            "Technology Mix",
            "Initial Emissions",
            "Free Allocation",
            "Abatement",
            "Residual Emissions",
            "Allowance Buys",
            "Allowance Sells",
            "Penalty Emissions",
            "Net Allowances Traded",
            "Starting Bank Balance",
            "Ending Bank Balance",
            "Banked Allowances",
            "Borrowed Allowances",
            "Expected Future Price",
            "Fixed Technology Cost",
            "Abatement Cost",
            "Allowance Cost",
            "Penalty Cost",
            "Sales Revenue",
            "Total Compliance Cost",
            "EUA Price",
            "CBAM Gap",
            "CBAM Export Share",
            "CBAM Liable Emissions",
            "CBAM Liability",
            "Total Cost incl. CBAM",
            "Electricity Consumption",
            "Grid Emission Factor",
            "Indirect Emissions",
            "Scope 2 CBAM Coverage",
            "Scope 2 CBAM Liability",
            "Year",
        ],
    },
}


@pytest.mark.parametrize("scenario_name", sorted(_PINNED_COLUMNS))
def test_pinned_column_order(scenario_name: str) -> None:
    """The engine's participant/summary column order matches the pre-refactor pin."""
    config_path = EXAMPLES_DIR / f"{scenario_name}.json"
    assert config_path.exists(), f"Reference example missing: {config_path}"

    summary_df, participant_df = run_simulation_from_file(config_path)
    pinned = _PINNED_COLUMNS[scenario_name]

    assert list(participant_df.columns) == pinned["participant_columns"], (
        f"{scenario_name}: participant column order drifted from the O7 pin."
    )
    assert list(summary_df.columns) == pinned["summary_columns"], (
        f"{scenario_name}: summary column order drifted from the O7 pin."
    )


# ── Bare-CarbonMarket base-column contract (CarbonMarket docstring, O7) ──────
#
# A market built OUTSIDE config_io never attaches reporters
# (`participant_reporters` / `summary_reporters_pre_year` /
# `summary_reporters_post_year` all default to an empty tuple), so it must
# emit exactly the host's base columns — no CBAM, sector, or MSR/CCR
# columns. This is what makes "attach-always" a property of the
# CONFIGURATION (config_io's reviewed literal), not of the reporting host.

_BASE_PARTICIPANT_COLUMNS: list[str] = [
    "Scenario",
    "Participant",
    "Sector Group",
    "Chosen Technology",
    "Technology Mix",
    "Initial Emissions",
    "Free Allocation",
    "Abatement",
    "Residual Emissions",
    "Allowance Buys",
    "Allowance Sells",
    "Penalty Emissions",
    "Net Allowances Traded",
    "Starting Bank Balance",
    "Ending Bank Balance",
    "Banked Allowances",
    "Borrowed Allowances",
    "Expected Future Price",
    "Fixed Technology Cost",
    "Abatement Cost",
    "Allowance Cost",
    "Penalty Cost",
    "Sales Revenue",
    "Total Compliance Cost",
    "Year",
]

_BASE_SUMMARY_COLUMNS: list[str] = [
    "Scenario",
    "Equilibrium Carbon Price",
    "Total Abatement",
    "Total Allowance Buys",
    "Total Allowance Sells",
    "Total Penalty Emissions",
    "Total Net Allowances Traded",
    "Auction Offered",
    "Auction Sold",
    "Unsold Allowances",
    "Auction Coverage Ratio",
    "Reserved Allowances",
    "Cancelled Allowances",
    "Unallocated Allowances",
    "Total Auction Revenue",
    "Total Starting Bank",
    "Total Ending Bank",
    "Total Banked Allowances",
    "Total Borrowed Allowances",
    "Expectation Rule",
    "Manual Expected Price",
    "Total Compliance Cost",
    "Year",
    "P1 Technology",
    "P1 Technology Mix",
    "P1 Abatement",
    "P1 Net Trade",
]


def _bare_market() -> CarbonMarket:
    """One participant, one bare `CarbonMarket` — no reporters attached."""
    participant = MarketParticipant(
        name="P1",
        initial_emissions=100.0,
        marginal_abatement_cost=linear_abatement_factory(max_abatement=50.0, cost_slope=2.0),
        free_allocation_ratio=0.5,
        penalty_price=100.0,
    )
    return CarbonMarket(
        participants=[participant],
        total_cap=100.0,
        auction_offered=50.0,
        scenario_name="bare-market-test",
        year="2030",
    )


def test_bare_market_participant_results_are_base_columns_only() -> None:
    """A `CarbonMarket()` built outside config_io emits base participant columns only."""
    market = _bare_market()
    assert market.participant_reporters == ()

    participant_df = market.participant_results(equilibrium_price=20.0)

    assert list(participant_df.columns) == _BASE_PARTICIPANT_COLUMNS


def test_bare_market_scenario_summary_is_base_columns_only() -> None:
    """A `CarbonMarket()` built outside config_io emits base summary columns only."""
    market = _bare_market()
    assert market.summary_reporters_pre_year == ()
    assert market.summary_reporters_post_year == ()

    participant_df = market.participant_results(equilibrium_price=20.0)
    summary = market.scenario_summary(equilibrium_price=20.0, participant_df=participant_df)

    assert list(summary.keys()) == _BASE_SUMMARY_COLUMNS
