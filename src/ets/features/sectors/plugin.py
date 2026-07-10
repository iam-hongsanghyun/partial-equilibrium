r"""Sectors plugin door — summary reporter attachment for the reporting host (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``ets.features.sectors``. Sectors today has no runtime module — it is
"attributes + aggregation + normalization" (v1 §1 "Features challenged /
merged"; v2 feature verdicts: "sectors (transform + summary reporter)" — the
build-time free-allocation transform is a separate O9 work order). This
reporter reads the ``"Sector Group"`` column ``config_io/builder.py`` stamps
onto each participant and the columns other attach-always reporters (CBAM)
write onto the participant frame; it never imports another feature.

``SectorSummaryReporter`` is relocated VERBATIM from the pre-refactor
``core/market/reporting.py`` results.py:247-278 (sector-group aggregate
rows, then the per-sector compliance-cost percentile distribution).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

    from ...core.market.model import CarbonMarket


class SectorSummaryReporter:
    r"""Sector-group aggregate columns and compliance-cost percentiles.

    Algorithm:
        LaTeX (per sector group :math:`g`, participants :math:`i \in g`):
        $$ \mathrm{AuctionRevenueShare}_g = R_{\mathrm{auction}} \cdot
           \frac{\sum_{i \in g} \mathrm{buys}_i}{\sum_i \mathrm{buys}_i} $$
        $$ P_{k,g} = \mathrm{percentile}\big(\{c_i : i \in g\},\, k\big),
           \quad k \in \{10, 50, 90\} $$
        $$ \sigma_g = \mathrm{std}\big(\{c_i : i \in g\}\big) $$

        ASCII fallback:
            sector_buys        = sum(buys_i for i in group g)
            total_buys         = sum(buys_i for i in all participants)
            auction_rev_share  = auction_rev * (sector_buys / total_buys)
            p10, p50, p90      = np.percentile(costs_g, [10, 50, 90])
            cost_std_dev       = np.std(costs_g)

        Symbols (units):
            R_auction    : scenario ``"Total Auction Revenue"``  [currency]
            buys_i       : participant i's ``"Allowance Buys"``  [Mt CO2e]
            c_i          : participant i's ``"Total Compliance Cost"``
                                                                    [currency]
            P_{k,g}      : group g's k-th percentile of c_i        [currency]
            sigma_g      : group g's compliance-cost std. dev.     [currency]

    Percentiles and the std. dev. are only computed for groups with >= 2
    participants (a percentile / std. dev. of one observation is not
    meaningful — the original guard, preserved verbatim).

    Reporters are ATTACH-ALWAYS (``core/protocols.py`` ``SummaryReporter``):
    a scenario without a ``"Sector Group"`` column contributes no columns
    (the original guard), which is the neutral (no sectors configured) case.
    """

    def contribute(
        self,
        summary: dict[str, float | str],
        market: "CarbonMarket",
        participant_df: "pd.DataFrame",
        price: float,
    ) -> None:
        """Append per-sector aggregate and percentile columns to the summary.

        Args:
            summary: The accumulating summary dict — read for
                ``"Total Auction Revenue"`` and mutated in place.
            market: The year's market (unused directly; kept for protocol
                conformance).
            participant_df: The year's solved participant results frame
                (must carry ``"Sector Group"`` for any columns to be added).
            price: The year's delivered allowance price [currency/tCO2]
                (unused directly).
        """
        # ── Sector-group aggregates ──────────────────────────────────────
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

        # ── Per-sector compliance cost distribution (P10, P50, P90) ──────
        if "Sector Group" in participant_df.columns:
            for sg, grp in participant_df.groupby("Sector Group"):
                if not sg or len(grp) < 2:
                    continue
                costs = grp["Total Compliance Cost"].values
                summary[f"{sg} P10 Compliance Cost"] = float(np.percentile(costs, 10))
                summary[f"{sg} P50 Compliance Cost"] = float(np.percentile(costs, 50))
                summary[f"{sg} P90 Compliance Cost"] = float(np.percentile(costs, 90))
                summary[f"{sg} Cost Std Dev"] = float(np.std(costs))
