"""Reporting host — base columns + staged reporter iteration (T0 kernel).

Emits the BASE participant and summary columns (the fixed schema every
scenario gets regardless of configuration) and iterates the reporters
attached to ``market`` (``core/market/model.py`` ``participant_reporters``,
``summary_reporters_pre_year``, ``summary_reporters_post_year`` —
``core/protocols.py`` ``ParticipantReporter`` / ``SummaryReporter``). This
module is the reporting HOST: it owns column order (dict insertion order),
never feature-specific column expressions — those live in the feature
plugin doors that attach to ``market`` (``config_io/builder.py:
build_market_from_year``; ``docs/feature-modules-plan.md`` PLAN v2
§"Two-door features", Arbitration outcomes O7).

Column order is a reviewed source literal, not incidental: the golden
baselines (``tests/test_golden_baselines.py``) and the column-order pin
(``tests/test_reporting_columns.py``) are column-order-sensitive.

    participant frame : base columns -> reporters (attach order) -> "Year"
    summary frame      : core keys -> pre-Year reporters -> "Year"
                          -> post-Year reporters -> per-participant tail
"""

from __future__ import annotations

from typing import Dict

import pandas as pd

from .model import CarbonMarket
from .clearing import _participant_outcome


def participant_results(
    market: CarbonMarket,
    equilibrium_price: float,
    bank_balances: dict[str, float] | None = None,
    expected_future_price: float = 0.0,
) -> pd.DataFrame:
    """Build the per-participant results frame for one solved market-year.

    Column order: the base columns below, then each attached
    ``market.participant_reporters`` in order (its ``columns()`` dict is
    merged in, insertion order is column order), then ``"Year"`` at the
    tail. Reporters are attach-always (``core/protocols.py``
    ``ParticipantReporter``): ``market.participant_reporters`` defaults to
    an empty tuple (base columns only, ``core/market/model.py``
    ``CarbonMarket`` docstring) and is populated by
    ``config_io/builder.py:build_market_from_year`` for every in-repo market.

    Args:
        market: The year's solved market.
        equilibrium_price: Solved allowance price [currency/tCO2], also
            passed to reporters as ``price``.
        bank_balances: Beginning-of-year bank balances by participant name
            [Mt CO2e], or ``None`` for a static (no-banking) year.
        expected_future_price: Expected next-year price [currency/tCO2]
            used by the compliance outcome's bank/borrow decision.

    Returns:
        One row per participant; columns per the order above.
    """
    records: list[Dict[str, float | str]] = []
    for participant in market.participants:
        outcome = _participant_outcome(
            market,
            participant,
            equilibrium_price,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        )
        record: Dict[str, float | str] = {
            "Scenario": market.scenario_name,
            "Participant": participant.name,
            "Sector Group": str(getattr(participant, "sector_group", "") or ""),
            "Chosen Technology": outcome.technology_name,
            "Technology Mix": "; ".join(
                f"{name}:{share:.4f}" for name, share in outcome.technology_mix
            ),
            "Initial Emissions": outcome.initial_emissions,
            "Free Allocation": outcome.free_allocation,
            "Abatement": outcome.abatement,
            "Residual Emissions": outcome.residual_emissions,
            "Allowance Buys": outcome.allowance_buys,
            "Allowance Sells": outcome.allowance_sells,
            "Penalty Emissions": outcome.penalty_emissions,
            "Net Allowances Traded": outcome.net_allowances_traded,
            "Starting Bank Balance": outcome.starting_bank_balance,
            "Ending Bank Balance": outcome.ending_bank_balance,
            "Banked Allowances": outcome.banked_allowances,
            "Borrowed Allowances": outcome.borrowed_allowances,
            "Expected Future Price": outcome.expected_future_price,
            "Fixed Technology Cost": outcome.fixed_cost,
            "Abatement Cost": outcome.abatement_cost,
            "Allowance Cost": outcome.allowance_cost,
            "Penalty Cost": outcome.penalty_cost,
            "Sales Revenue": outcome.sales_revenue,
            "Total Compliance Cost": outcome.total_cost,
        }
        for reporter in market.participant_reporters:
            record.update(
                reporter.columns(market, participant, outcome, equilibrium_price)
            )
        if market.year is not None:
            record["Year"] = market.year
        records.append(record)
    return pd.DataFrame.from_records(records)


def scenario_summary(
    market: CarbonMarket,
    equilibrium_price: float,
    bank_balances: dict[str, float] | None = None,
    expected_future_price: float = 0.0,
    auction_outcome: dict[str, float] | None = None,
    participant_df: pd.DataFrame | None = None,
) -> Dict[str, float | str]:
    """Build the scenario-summary record for one solved market-year.

    Column order (Arbitration outcomes, O7 — the staged literal reproduces
    the pre-refactor interleave EXACTLY):

        core keys -> summary_reporters_pre_year (in order) -> "Year"
        -> summary_reporters_post_year (in order) -> per-participant tail

    Each stage receives and mutates the SAME accumulating ``summary`` dict
    (``core/protocols.py`` ``SummaryReporter``) — later stages read earlier
    stages' columns (e.g. the CBAM revenue tracker reads ``"Total Auction
    Revenue"`` from the core keys and ``"Total CBAM Liability"`` from its
    own pre-Year stage). Reporters are attach-always: both reporter tuples
    default to empty (base columns only) and are populated by
    ``config_io/builder.py:build_market_from_year``.

    Args:
        market: The year's solved market.
        equilibrium_price: Solved allowance price [currency/tCO2].
        bank_balances: Beginning-of-year bank balances by participant name
            [Mt CO2e], forwarded to ``participant_results`` when
            ``participant_df`` is not already supplied.
        expected_future_price: Expected next-year price [currency/tCO2].
        auction_outcome: Solved auction outcome (offered/sold/unsold/
            coverage); defaults to a fully-subscribed auction at
            ``market.auction_offered`` when ``None``.
        participant_df: Already-solved participant frame, to avoid
            re-solving; computed via ``participant_results`` when ``None``.

    Returns:
        The scenario-summary record; key order per the staging above.
    """
    if participant_df is None:
        participant_df = participant_results(
            market,
            equilibrium_price,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        )
    if auction_outcome is None:
        auction_outcome = {
            "auction_offered": market.auction_offered,
            "auction_sold": market.auction_offered,
            "unsold_allowances": 0.0,
            "coverage_ratio": 1.0,
        }
    summary: Dict[str, float | str] = {
        "Scenario": market.scenario_name,
        "Equilibrium Carbon Price": equilibrium_price,
        "Total Abatement": float(participant_df["Abatement"].sum()),
        "Total Allowance Buys": float(participant_df["Allowance Buys"].sum()),
        "Total Allowance Sells": float(participant_df["Allowance Sells"].sum()),
        "Total Penalty Emissions": float(
            participant_df["Penalty Emissions"].sum()
        ),
        "Total Net Allowances Traded": float(
            participant_df["Net Allowances Traded"].sum()
        ),
        "Auction Offered": float(auction_outcome["auction_offered"]),
        "Auction Sold": float(auction_outcome["auction_sold"]),
        "Unsold Allowances": float(auction_outcome["unsold_allowances"]),
        "Auction Coverage Ratio": float(auction_outcome["coverage_ratio"]),
        "Reserved Allowances": market.reserved_allowances,
        "Cancelled Allowances": market.cancelled_allowances,
        "Unallocated Allowances": market.unallocated_allowances,
        "Total Auction Revenue": market.calculate_auction_revenue(
            equilibrium_price, float(auction_outcome["auction_sold"])
        ),
        "Total Starting Bank": float(participant_df["Starting Bank Balance"].sum()),
        "Total Ending Bank": float(participant_df["Ending Bank Balance"].sum()),
        "Total Banked Allowances": float(participant_df["Banked Allowances"].sum()),
        "Total Borrowed Allowances": float(
            participant_df["Borrowed Allowances"].sum()
        ),
        "Expectation Rule": market.expectation_rule,
        "Manual Expected Price": market.manual_expected_price,
        "Total Compliance Cost": float(
            participant_df["Total Compliance Cost"].sum()
        ),
    }

    # Stage A (pre-Year): attach-always feature aggregates (CBAM, then MSR
    # placeholders, then CCR placeholders — the reviewed literal in
    # config_io/builder.py).
    for reporter in market.summary_reporters_pre_year:
        reporter.contribute(summary, market, participant_df, equilibrium_price)

    # Year placement is per-host: mid-dict, after the pre-Year stage
    # (Arbitration outcomes, O7).
    if market.year is not None:
        summary["Year"] = market.year

    # Stage B (post-Year): CBAM revenue tracker + jurisdiction/ensemble/
    # scope-2 totals, then sector aggregates + percentiles.
    for reporter in market.summary_reporters_post_year:
        reporter.contribute(summary, market, participant_df, equilibrium_price)

    # Host per-participant tail (generic — not owned by any feature).
    for _, row in participant_df.iterrows():
        participant_name = str(row["Participant"])
        summary[f"{participant_name} Technology"] = str(row["Chosen Technology"])
        summary[f"{participant_name} Technology Mix"] = str(row.get("Technology Mix", ""))
        summary[f"{participant_name} Abatement"] = float(row["Abatement"])
        summary[f"{participant_name} Net Trade"] = float(
            row["Net Allowances Traded"]
        )
    return summary
