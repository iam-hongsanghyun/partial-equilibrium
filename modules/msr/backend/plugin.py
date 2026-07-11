"""MSR plugin door — summary placeholder reporter + splice carrier (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``ets.features.msr`` today. The MSR runtime (decree rule, bank-threshold
rule) lives in this feature's ``state.py``/``rules.py``/``decree.py`` and
fills these columns' real values during simulation
(``core/ledger.py:collect_path_results``); this reporter only attaches the
zero-valued placeholder columns so the summary frame's schema is stable
regardless of whether MSR is configured (attach-always,
``core/protocols.py`` ``SummaryReporter``).

``MSRSummaryPlaceholderReporter`` is relocated VERBATIM from the
pre-refactor ``core/market/reporting.py`` results.py:215-217.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.protocols import SpliceCarrier

if TYPE_CHECKING:
    import pandas as pd

    from ...core.market.model import CarbonMarket


# ── Splice-carrier declaration (binding Arbitration outcome on PLAN v2) ──────
# The MSR reserve pool is carried across policy-event segments ONLY when the
# rule actually ran in the finished segment (the ``msr_ran_last_segment``
# condition): a decree announced mid-horizon with a pre-funded reserve
# (``msr_initial_reserve_mt`` in its changes) must KEEP that funding rather
# than have it overwritten by a stale carried pool — R7's decree-only funding
# read through the splice (``core.protocols.SpliceCarrier``;
# ``tests/test_policy_events.py`` pins the ordering). Consumed by the engine's
# segment host literal (``engine/events.py`` SPLICE_CARRIERS).
RESERVE_CARRIER = SpliceCarrier(
    column="MSR Reserve Pool",
    config_field="msr_initial_reserve_mt",
    carry_if=lambda config: bool(config.get("msr_enabled")),
)


class MSRSummaryPlaceholderReporter:
    """Zero-valued MSR aggregate placeholders, overwritten by the simulation loop.

    ``core/ledger.py:collect_path_results`` overwrites ``"MSR Withheld"``,
    ``"MSR Released"``, and ``"MSR Reserve Pool"`` in place with the year's
    realised MSR aggregates once the per-year pipeline runs the MSR cap rule; a
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
