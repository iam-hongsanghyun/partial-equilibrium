"""MSR plugin door — summary placeholder reporter for the reporting host (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``ets.features.msr`` today. The MSR runtime (decree rule, bank-threshold
rule) still lives in ``ets/solvers/msr.py`` and fills these columns' real
values during simulation (``solvers/simulation.py``); this reporter only
attaches the zero-valued placeholder columns so the summary frame's schema
is stable regardless of whether MSR is configured (attach-always,
``core/protocols.py`` ``SummaryReporter``).

``MSRSummaryPlaceholderReporter`` is relocated VERBATIM from the
pre-refactor ``core/market/reporting.py`` results.py:215-217.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from ...core.market.model import CarbonMarket


class MSRSummaryPlaceholderReporter:
    """Zero-valued MSR aggregate placeholders, overwritten by the simulation loop.

    ``solvers/simulation.py`` overwrites ``"MSR Withheld"``, ``"MSR
    Released"``, and ``"MSR Reserve Pool"`` in place with the year's realised
    MSR aggregates once the per-year pipeline runs the MSR cap rule; a
    scenario with MSR disabled keeps these columns at their neutral value so
    the summary column set never depends on whether MSR is configured.
    """

    def contribute(
        self,
        summary: dict[str, float | str],
        market: "CarbonMarket",
        participant_df: "pd.DataFrame",
        price: float,
    ) -> None:
        """Append the MSR aggregate placeholder columns to the summary.

        Args:
            summary: The accumulating summary dict, mutated in place.
            market: The year's market (unused directly; kept for protocol
                conformance — MSR runtime state lives outside the reporting
                host).
            participant_df: The year's solved participant results frame
                (unused directly).
            price: The year's delivered allowance price [currency/tCO2]
                (unused directly).
        """
        summary["MSR Withheld"] = 0.0
        summary["MSR Released"] = 0.0
        summary["MSR Reserve Pool"] = 0.0
