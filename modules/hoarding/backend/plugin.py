r"""hoarding plugin door — the ``Friction`` provider for structural hoarding (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2): this module
carries the hoarding feature's ONLY code — the per-year inflow reader,
implementing ``core.protocols.Friction``. ``HoardingInflow.inflow`` is the
banking solver's ``_hoarding_inflow`` lifted verbatim (work order O10).

THE HOST SET IS NOT HERE (Arbitration outcomes, O10, binding): the
``Friction`` protocol's contract IS the hoarding semantics, and everything
except the schedule read stays in the banking host — the static-year supply
reduction ``S_t − h_t``, the forced-static window-start constraint
``a > max{t : h_t > 0}``, the pre-window no-arbitrage prune exemption (the
documented λ ≈ 0 violation), and the accumulation of the hoarded volume
into the window budget (``incoming_bank = B_0 + Σ h_t``). See the
``Friction`` protocol docstring for the pinned semantics and
``solvers/banking.py`` for the host math.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...core.market.model import CarbonMarket


class HoardingInflow:
    r"""Exogenous hoarding inflow h_t read from the year's market (``Friction``).

    Reduced-form representation of structural hoarding in a λ ≈ 0 market
    (K-MSR paper §3–4: compliance entities bank against future tightening
    without pricing the carry — the registry banked-to-certified ratio rising
    0.03 → 0.17). Hoarded volume clears out of the year's supply (raising the
    static price), accumulates in the aggregate bank, and re-enters the
    window budget when the drawdown window opens — all HOST behaviour; this
    class only reads the schedule.

    Algorithm:
        ASCII: h_t = float(market.hoarding_inflow or 0.0)

        Symbols (units):
            h_t : hoarding inflow withdrawn from circulation in year t
                                                                 [Mt CO2e]

    Neutral behaviour is exact: an unconfigured market (field absent, None,
    or 0) yields ``0.0`` — the textbook equilibrium — so attaching this
    Friction to every banking solve changes nothing without
    ``hoarding_inflow`` fields (year field ``hoarding_inflow``; default 0).
    """

    def inflow(self, market: CarbonMarket) -> float:
        """Return the year's hoarding inflow h_t.

        Args:
            market: The year's market (year field ``hoarding_inflow``).

        Returns:
            Withdrawn volume h_t [Mt CO2e]; 0.0 when unconfigured.
        """
        return float(getattr(market, "hoarding_inflow", 0.0) or 0.0)
