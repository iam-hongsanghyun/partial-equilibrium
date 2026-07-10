r"""CBAM plugin door — reporter attachments for the reporting host (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``ets.features.cbam`` (the door rule). CBAM has no runtime module today — it
is reporting-only (feature verdicts v2: "cbam (reporters only; F6 becomes a
mechanically gated invariant)"; Arbitration outcomes, O7): CBAM liability is
a post-clearing diagnostic that reads the solved KAU price and the external
EUA reference price, never a price channel (F6). Imports ONLY
``ets.core.*`` and stdlib.

Every column expression below is relocated VERBATIM from the pre-refactor
``core/market/reporting.py`` (line ranges are the ones cited in the O7 work
order, which are unchanged since the O3 move from ``market/results.py``):

* ``CBAMParticipantReporter`` — the per-participant CBAM/EUA/scope-2 block,
  results.py:27-105 (liability + ensemble + scope-2 computation) and
  :134-146 (the columns dict, including the dynamic per-jurisdiction and
  EUA-ensemble keys).
* ``CBAMSummaryAggregatesReporter`` — the pre-Year CBAM aggregate columns,
  results.py:209-213.
* ``CBAMSummaryTotalsReporter`` — the post-Year revenue tracker, then
  per-jurisdiction totals, then EUA-ensemble totals (the order-sensitive
  ``col not in summary`` dedup — it reads the ACCUMULATING summary dict),
  then scope-2 totals, results.py:226-245 (Arbitration outcomes, O7: "cbam
  summary stage literal includes results.py:234-245 ... after the revenue
  tracker").

References:
    docs/feature-modules-plan.md — PLAN v2 §"Two-door features", "Feature
    verdicts v2"; Arbitration outcomes (O7 binding conditions).
    core/protocols.py — ``ParticipantReporter``, ``SummaryReporter``
    (the accumulating-summary staging doctrine).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from ...core.market.model import CarbonMarket
    from ...core.participant.models import ComplianceOutcome, MarketParticipant


class CBAMParticipantReporter:
    r"""Per-participant CBAM liability, EUA-ensemble, and scope-2 columns.

    Algorithm:
        LaTeX (single-jurisdiction / default reference price):
        $$ \mathrm{gap} = \max(0,\, P_{\mathrm{EUA}} - P_{\mathrm{KAU}}) $$
        $$ e_{\mathrm{liable}} = e_{\mathrm{res}} \cdot s_{\mathrm{export}}
           \cdot c_{\mathrm{cov}} $$
        $$ L_{\mathrm{CBAM}} = \mathrm{gap} \cdot e_{\mathrm{liable}} $$

        Multi-jurisdiction (when ``cbam_jurisdictions`` is non-empty, this
        REPLACES the single-jurisdiction fields; the displayed ``CBAM Gap``
        is the liability-weighted average across jurisdictions):
        $$ \mathrm{gap}_j = \max(0,\, P_j - P_{\mathrm{KAU}}), \quad
           e_{\mathrm{liable},j} = e_{\mathrm{res}} \cdot s_j \cdot c_j $$
        $$ L_{\mathrm{CBAM}} = \sum_j \mathrm{gap}_j \, e_{\mathrm{liable},j},
           \qquad \mathrm{gap} = \frac{L_{\mathrm{CBAM}}}
           {\sum_j e_{\mathrm{liable},j}} $$

        Scope 2 (indirect, electricity-based emissions; same gap logic,
        summed over jurisdictions when present):
        $$ e_{\mathrm{indirect}} = q_{\mathrm{elec}} \cdot f_{\mathrm{grid}} $$
        $$ L_{\mathrm{scope2}} = \mathrm{gap} \cdot e_{\mathrm{indirect}}
           \cdot s_{\mathrm{export}} \cdot c_{\mathrm{scope2}} $$

        ASCII fallback:
            gap           = max(0, P_eua - P_kau)
            liable_emis   = residual_emissions * export_share * coverage
            cbam_liab     = gap * liable_emis
            indirect_emis = electricity_consumption * grid_emission_factor
            scope2_liab   = gap * indirect_emis * export_share * scope2_cov

        Symbols (units):
            P_EUA, P_j     : external / jurisdiction-specific EUA reference
                              carbon price                    [currency/tCO2]
            P_KAU          : solved domestic (KAU) allowance price
                                                                [currency/tCO2]
            e_res          : participant residual emissions   [Mt CO2e]
            s_export, s_j  : CBAM export share, dimensionless (0-1)
            c_cov, c_j     : CBAM coverage ratio, dimensionless (0-1)
            e_indirect     : indirect (Scope 2) emissions      [Mt CO2e]
            q_elec         : electricity consumption           [MWh]
            f_grid         : grid emission factor              [tCO2/MWh]
            c_scope2       : scope-2 CBAM coverage, dimensionless (0-1)
            L_CBAM         : direct CBAM liability              [currency]
            L_scope2       : scope-2 CBAM liability              [currency]

    Reporters are ATTACH-ALWAYS (``core/protocols.py`` ``ParticipantReporter``):
    an unconfigured participant (no jurisdictions, zero export share) still
    emits every fixed-name column at its neutral (zero) value.
    """

    def columns(
        self,
        market: "CarbonMarket",
        participant: "MarketParticipant",
        outcome: "ComplianceOutcome",
        price: float,
    ) -> dict[str, float | str]:
        """Compute this participant-year's CBAM/EUA/scope-2 columns.

        Args:
            market: The year's market (``eua_price``, ``eua_prices``,
                ``eua_price_ensemble``).
            participant: The participant (CBAM exposure and scope-2 fields).
            outcome: The participant's solved compliance outcome
                (``residual_emissions``, ``total_cost``).
            price: The year's delivered allowance (KAU) price
                [currency/tCO2].

        Returns:
            Ordered mapping: ``EUA Price``, ``CBAM Gap``, ``CBAM Export
            Share``, ``CBAM Liable Emissions``, ``CBAM Liability``, ``Total
            Cost incl. CBAM``, ``Electricity Consumption``, ``Grid Emission
            Factor``, ``Indirect Emissions``, ``Scope 2 CBAM Coverage``,
            ``Scope 2 CBAM Liability``, then the dynamic per-jurisdiction
            (``CBAM Liability (<name>)``, ``CBAM Gap (<name>)``) and
            EUA-ensemble (``CBAM Liability (<name>)``) columns, present only
            when configured.
        """
        # ── CBAM liability ──────────────────────────────────────────────
        eua_price = float(getattr(market, "eua_price", 0.0) or 0.0)
        eua_prices = dict(getattr(market, "eua_prices", {}) or {})
        eua_price_ensemble = dict(getattr(market, "eua_price_ensemble", {}) or {})
        kau_price = float(price)

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

        return {
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


class CBAMSummaryAggregatesReporter:
    """Stage A (pre-Year): scenario-level CBAM aggregate columns.

    Reads the ``EUA Price``, ``CBAM Gap``, ``CBAM Liability``, and ``Total
    Cost incl. CBAM`` columns ``CBAMParticipantReporter`` wrote onto the
    participant frame (attach-always, so these are always present).
    """

    def contribute(
        self,
        summary: dict[str, float | str],
        market: "CarbonMarket",
        participant_df: "pd.DataFrame",
        price: float,
    ) -> None:
        """Append the CBAM aggregate columns to the accumulating summary.

        Args:
            summary: The accumulating summary dict, mutated in place.
            market: The year's market (``eua_price``).
            participant_df: The year's solved participant results frame.
            price: The year's delivered allowance price [currency/tCO2]
                (unused directly; the participant frame already carries the
                per-participant gap).
        """
        summary["EUA Price"] = float(getattr(market, "eua_price", 0.0) or 0.0)
        summary["CBAM Gap"] = (
            float(participant_df["CBAM Gap"].iloc[0]) if len(participant_df) else 0.0
        )
        summary["Total CBAM Liability"] = float(participant_df["CBAM Liability"].sum())
        summary["Total Cost incl. CBAM"] = float(
            participant_df["Total Cost incl. CBAM"].sum()
        )


class CBAMSummaryTotalsReporter:
    """Stage B (post-Year): CBAM revenue tracker, then jurisdiction/ensemble/scope-2 totals.

    Order-sensitive (``core/protocols.py`` ``SummaryReporter``): the revenue
    tracker reads ``"Total Auction Revenue"`` (a base summary key) and
    ``"Total CBAM Liability"`` (written by ``CBAMSummaryAggregatesReporter``
    in stage A); the EUA-ensemble loop's ``col not in summary`` dedup reads
    the summary dict as accumulated by the per-jurisdiction loop immediately
    before it, in the SAME ``contribute`` call — moving these three loops
    apart or reordering them changes the output (Arbitration outcomes, O7).
    """

    def contribute(
        self,
        summary: dict[str, float | str],
        market: "CarbonMarket",
        participant_df: "pd.DataFrame",
        price: float,
    ) -> None:
        """Append the revenue-tracker and totals columns to the summary.

        Args:
            summary: The ACCUMULATING summary dict — read for
                ``"Total Auction Revenue"`` / ``"Total CBAM Liability"`` and
                for the order-sensitive ``col not in summary`` dedup, then
                mutated in place.
            market: The year's market (unused directly; kept for protocol
                conformance).
            participant_df: The year's solved participant results frame.
            price: The year's delivered allowance price [currency/tCO2]
                (unused directly).
        """
        # ── Auction revenue reinvestment tracker ─────────────────────────
        auction_rev = float(summary.get("Total Auction Revenue", 0.0))
        cbam_liability = float(summary.get("Total CBAM Liability", 0.0))
        summary["Domestic Retained Revenue"] = auction_rev
        summary["CBAM Foregone Revenue"] = cbam_liability  # flows to EU instead of domestic fund
        summary["Potential Revenue if KAU=EUA"] = auction_rev + cbam_liability

        # ── Per-jurisdiction CBAM totals ──────────────────────────────────
        for col in participant_df.columns:
            if col.startswith("CBAM Liability (") or col.startswith("CBAM Gap ("):
                summary[f"Total {col}"] = float(participant_df[col].sum())

        # ── EUA ensemble totals ────────────────────────────────────────────
        for col in participant_df.columns:
            if col.startswith("CBAM Liability (") and col not in summary:
                summary[f"Total {col}"] = float(participant_df[col].sum())

        # ── Market-level Scope 2 / indirect totals ─────────────────────────
        summary["Total Indirect Emissions"] = (
            float(participant_df["Indirect Emissions"].sum())
            if "Indirect Emissions" in participant_df.columns
            else 0.0
        )
        summary["Total Scope 2 CBAM Liability"] = (
            float(participant_df["Scope 2 CBAM Liability"].sum())
            if "Scope 2 CBAM Liability" in participant_df.columns
            else 0.0
        )
