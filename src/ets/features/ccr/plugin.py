"""CCR plugin door — summary placeholder reporter for the reporting host (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``ets.features.ccr`` today. The CCR runtime (the Benmir-Roman-Taschini
carbon cap rule) still lives in ``ets/solvers/ccr.py`` and fills these
columns' real values during simulation (``solvers/simulation.py``); this
reporter only attaches the zero-valued placeholder columns so the summary
frame's schema is stable regardless of whether CCR is configured
(attach-always, ``core/protocols.py`` ``SummaryReporter``).

``CCRSummaryPlaceholderReporter`` is relocated VERBATIM from the
pre-refactor ``core/market/reporting.py`` results.py:219-221.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

    from ...core.market.model import CarbonMarket


class CCRSummaryPlaceholderReporter:
    """Zero-valued CCR aggregate placeholders, overwritten by the simulation loop.

    ``solvers/simulation.py`` overwrites ``"CCR Cap Adjustment"``, ``"CCR
    Emissions Deviation"``, and ``"CCR Cost Deviation"`` in place with the
    year's realised CCR aggregates once the per-year pipeline runs the CCR
    cap rule; a scenario with CCR disabled keeps these columns at their
    neutral value so the summary column set never depends on whether CCR is
    configured.
    """

    def contribute(
        self,
        summary: dict[str, float | str],
        market: "CarbonMarket",
        participant_df: "pd.DataFrame",
        price: float,
    ) -> None:
        """Append the CCR aggregate placeholder columns to the summary.

        Args:
            summary: The accumulating summary dict, mutated in place.
            market: The year's market (unused directly; kept for protocol
                conformance — CCR runtime state lives outside the reporting
                host).
            participant_df: The year's solved participant results frame
                (unused directly).
            price: The year's delivered allowance price [currency/tCO2]
                (unused directly).
        """
        summary["CCR Cap Adjustment"] = 0.0
        summary["CCR Emissions Deviation"] = 0.0
        summary["CCR Cost Deviation"] = 0.0
