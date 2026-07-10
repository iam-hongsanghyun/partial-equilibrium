from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .model import CarbonMarket
from .clearing import _participant_outcome


def participant_results(
    market: CarbonMarket,
    equilibrium_price: float,
    bank_balances: dict[str, float] | None = None,
    expected_future_price: float = 0.0,
) -> pd.DataFrame:
    records: list[Dict[str, float | str]] = []
    for participant in market.participants:
        outcome = _participant_outcome(
            market,
            participant,
            equilibrium_price,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        )
        # ── CBAM liability ──────────────────────────────────────────────
        eua_price = float(getattr(market, "eua_price", 0.0) or 0.0)
        eua_prices = dict(getattr(market, "eua_prices", {}) or {})
        eua_price_ensemble = dict(getattr(market, "eua_price_ensemble", {}) or {})
        kau_price = float(equilibrium_price)

        # Multi-jurisdiction CBAM —  if cbam_jurisdictions is non-empty, compute
        # per-jurisdiction liabilities and sum; otherwise fall back to single fields.
        jurisdictions = list(getattr(participant, "cbam_jurisdictions", None) or [])
        if jurisdictions:
            cbam_gap = 0.0  # aggregate gap (weighted, for display)
            cbam_export_share = 0.0
            cbam_liable_emissions = 0.0
            cbam_liability = 0.0
            jur_records: dict = {}
            for jur in jurisdictions:
                jname   = str(jur.get("name", ""))
                jshare  = float(jur.get("export_share", 0.0) or 0.0)
                jcov    = float(jur.get("coverage_ratio", 1.0) or 1.0)
                # Reference price: jurisdiction-specific override > eua_prices dict > eua_price (EU)
                jref    = float(jur.get("reference_price") or eua_prices.get(jname) or eua_price or 0.0)
                jgap    = max(0.0, jref - kau_price)
                jliable = outcome.residual_emissions * jshare * jcov
                jliab   = jgap * jliable
                cbam_export_share   += jshare
                cbam_liable_emissions += jliable
                cbam_liability      += jliab
                jur_records[f"CBAM Liability ({jname})"] = jliab
                jur_records[f"CBAM Gap ({jname})"]       = jgap
            cbam_gap = (cbam_liability / cbam_liable_emissions) if cbam_liable_emissions > 0 else 0.0
        else:
            cbam_gap          = max(0.0, eua_price - kau_price)
            cbam_export_share = float(getattr(participant, "cbam_export_share", 0.0) or 0.0)
            cbam_coverage     = float(getattr(participant, "cbam_coverage_ratio", 1.0) or 1.0)
            cbam_liable_emissions = outcome.residual_emissions * cbam_export_share * cbam_coverage
            cbam_liability    = cbam_gap * cbam_liable_emissions
            jur_records       = {}

        total_cost_incl_cbam = outcome.total_cost + cbam_liability

        # EUA ensemble — compute CBAM liability under each named EUA trajectory
        ensemble_records: dict = {}
        for ename, eprice in eua_price_ensemble.items():
            egap = max(0.0, float(eprice) - kau_price)
            if jurisdictions:
                eliab = sum(
                    egap * outcome.residual_emissions
                    * float(j.get("export_share", 0.0))
                    * float(j.get("coverage_ratio", 1.0))
                    for j in jurisdictions
                )
            else:
                eliab = egap * outcome.residual_emissions * cbam_export_share * float(
                    getattr(participant, "cbam_coverage_ratio", 1.0) or 1.0
                )
            ensemble_records[f"CBAM Liability ({ename})"] = eliab

        # ── Scope 2 / indirect emissions ────────────────────────────────
        elec  = float(getattr(participant, "electricity_consumption", 0.0) or 0.0)
        grid  = float(getattr(participant, "grid_emission_factor", 0.0) or 0.0)
        s2cov = float(getattr(participant, "scope2_cbam_coverage", 0.0) or 0.0)
        indirect_emissions = elec * grid

        # Scope 2 CBAM liability — uses same price gap logic as direct CBAM
        if jurisdictions:
            scope2_cbam_liability = sum(
                max(0.0, float(jur.get("reference_price") or eua_prices.get(str(jur.get("name", ""))) or eua_price or 0.0) - kau_price)
                * indirect_emissions
                * float(jur.get("export_share", 0.0))
                * s2cov
                for jur in jurisdictions
            )
        else:
            scope2_cbam_liability = (
                max(0.0, eua_price - kau_price)
                * indirect_emissions
                * cbam_export_share
                * s2cov
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
            "EUA Price": eua_price,
            "CBAM Gap": cbam_gap,
            "CBAM Export Share": cbam_export_share,
            "CBAM Liable Emissions": cbam_liable_emissions,
            "CBAM Liability": cbam_liability,
            "Total Cost incl. CBAM": total_cost_incl_cbam,
            "Electricity Consumption": elec,
            "Grid Emission Factor": grid,
            "Indirect Emissions": indirect_emissions,
            "Scope 2 CBAM Coverage": s2cov,
            "Scope 2 CBAM Liability": scope2_cbam_liability,
            **jur_records,
            **ensemble_records,
        }
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
        # ── CBAM aggregates ────────────────────────────────────────────
        "EUA Price": float(getattr(market, "eua_price", 0.0) or 0.0),
        "CBAM Gap": float(participant_df["CBAM Gap"].iloc[0]) if len(participant_df) else 0.0,
        "Total CBAM Liability": float(participant_df["CBAM Liability"].sum()),
        "Total Cost incl. CBAM": float(participant_df["Total Cost incl. CBAM"].sum()),
        # ── MSR aggregates (filled by simulation.py) ───────────────────
        "MSR Withheld": 0.0,
        "MSR Released": 0.0,
        "MSR Reserve Pool": 0.0,
        # ── CCR aggregates (filled by simulation.py) ───────────────────
        "CCR Cap Adjustment": 0.0,
        "CCR Emissions Deviation": 0.0,
        "CCR Cost Deviation": 0.0,
    }
    if market.year is not None:
        summary["Year"] = market.year

    # ── Auction revenue reinvestment tracker ─────────────────────────────
    auction_rev = float(summary.get("Total Auction Revenue", 0.0))
    cbam_liability = float(summary.get("Total CBAM Liability", 0.0))
    summary["Domestic Retained Revenue"] = auction_rev
    summary["CBAM Foregone Revenue"] = cbam_liability  # flows to EU instead of domestic fund
    summary["Potential Revenue if KAU=EUA"] = auction_rev + cbam_liability

    # ── Per-jurisdiction CBAM totals ─────────────────────────────────────
    for col in participant_df.columns:
        if col.startswith("CBAM Liability (") or col.startswith("CBAM Gap ("):
            summary[f"Total {col}"] = float(participant_df[col].sum())

    # ── EUA ensemble totals ──────────────────────────────────────────────
    for col in participant_df.columns:
        if col.startswith("CBAM Liability (") and col not in summary:
            summary[f"Total {col}"] = float(participant_df[col].sum())

    # ── Market-level Scope 2 / indirect totals ───────────────────────────
    summary["Total Indirect Emissions"] = float(participant_df["Indirect Emissions"].sum()) if "Indirect Emissions" in participant_df.columns else 0.0
    summary["Total Scope 2 CBAM Liability"] = float(participant_df["Scope 2 CBAM Liability"].sum()) if "Scope 2 CBAM Liability" in participant_df.columns else 0.0

    # ── Sector-group aggregates ──────────────────────────────────────────
    if "Sector Group" in participant_df.columns:
        for sg, grp in participant_df.groupby("Sector Group"):
            if not sg:
                continue
            summary[f"{sg} Total Abatement"]           = float(grp["Abatement"].sum())
            summary[f"{sg} Total Compliance Cost"]      = float(grp["Total Compliance Cost"].sum())
            summary[f"{sg} Total CBAM Liability"]       = float(grp["CBAM Liability"].sum())
            # Auction revenue attribution: sector's share of total allowance buys × auction price
            sector_buys = float(grp["Allowance Buys"].sum())
            total_buys  = float(participant_df["Allowance Buys"].sum())
            auction_rev = summary.get("Total Auction Revenue", 0.0)
            summary[f"{sg} Allowance Buys"]             = sector_buys
            summary[f"{sg} Allowance Cost"]             = float(grp["Allowance Cost"].sum())
            summary[f"{sg} Auction Revenue Share"]      = (
                float(auction_rev) * (sector_buys / total_buys) if total_buys > 0 else 0.0
            )
            # Scope 2 by sector
            if "Indirect Emissions" in grp.columns:
                summary[f"{sg} Indirect Emissions"]     = float(grp["Indirect Emissions"].sum())
                summary[f"{sg} Scope 2 CBAM Liability"] = float(grp["Scope 2 CBAM Liability"].sum())

    # ── Per-sector compliance cost distribution (P10, P50, P90) ──────────
    if "Sector Group" in participant_df.columns:
        for sg, grp in participant_df.groupby("Sector Group"):
            if not sg or len(grp) < 2:
                continue
            costs = grp["Total Compliance Cost"].values
            summary[f"{sg} P10 Compliance Cost"] = float(np.percentile(costs, 10))
            summary[f"{sg} P50 Compliance Cost"] = float(np.percentile(costs, 50))
            summary[f"{sg} P90 Compliance Cost"] = float(np.percentile(costs, 90))
            summary[f"{sg} Cost Std Dev"] = float(np.std(costs))

    for _, row in participant_df.iterrows():
        participant_name = str(row["Participant"])
        summary[f"{participant_name} Technology"] = str(row["Chosen Technology"])
        summary[f"{participant_name} Technology Mix"] = str(row.get("Technology Mix", ""))
        summary[f"{participant_name} Abatement"] = float(row["Abatement"])
        summary[f"{participant_name} Net Trade"] = float(
            row["Net Allowances Traded"]
        )
    return summary
