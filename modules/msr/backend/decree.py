"""K-MSR draft-decree rule (T2 runtime, engine/host-facing).

``decree_msr_action`` (renamed from ``_decree_msr_action``) and
``DecreeSupplyRule``, moved VERBATIM from ``solvers/msr.py`` in the engine
work order (v1 O8 / v2 O12, ``docs/feature-modules-plan.md``). Wired by
``ets.engine.wiring`` — never imported by other features or by
``config_io``. The old underscore name stays importable from the
``ets/solvers/msr.py`` shim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.defaults import (
    DECREE_MSR_MAX_INTAKE_MT,
    DECREE_MSR_MAX_RELEASE_MT,
    DECREE_MSR_PRICE_BAND_HIGH,
    DECREE_MSR_PRICE_BAND_LOW,
    DECREE_MSR_SURPLUS_LOWER_RATIO,
    DECREE_MSR_SURPLUS_UPPER_RATIO,
)
from .rules import _free_allocation_total, _msr_start_active

if TYPE_CHECKING:
    from ...core.market.model import CarbonMarket
    from ...core.protocols import Observables


def decree_msr_action(
    market: CarbonMarket,
    mode: str,
    prev_price: float | None,
    prev_surplus_ratio: float | None,
    reserve_stock: float,
) -> tuple[float, float]:
    r"""K-MSR draft-decree action for one year: (intake, release) in Mt.

    Ports the decree parameterization published in the PLANiT K-ETS Outlook
    dashboard (kets-outlook ``src/lib/msr.ts``, K-ETS MSR policy: Phase-4
    reserve 85.277 Mt, price band 15,000–25,000 KRW, surplus-ratio band
    5 %–18 %, max intake/release 20 Mt/yr) and matching the K-MSR paper's P1
    ("absorb above a trigger, release 20 Mt/yr thereafter, no cancellation").

    Algorithm:
        ASCII: price signal   — prev_price >= high → release;
                                 prev_price <= low  → intake
               surplus signal — prev_surplus >= upper ratio → intake;
                                 prev_surplus <= lower ratio → release
               mode price_band / surplus_rule uses its own signal;
               hybrid takes the majority of the two signals (ties → neutral);
               release is capped by the reserve stock, intake by max_intake.

    Both signals read PREVIOUS-year state (the decree acts on observed
    outcomes); the first year is always neutral.

    Args:
        market: The year's market (carries the ``msr_*`` decree fields).
        mode: ``"price_band"`` | ``"surplus_rule"`` | ``"hybrid"``.
        prev_price: Previous year's solved price [currency/tCO2]; None in the
            first year.
        prev_surplus_ratio: Previous end-of-year bank over previous residual
            emissions [dimensionless]; None in the first year.
        reserve_stock: Reserve stock at the start of the year [Mt CO2e].

    Returns:
        ``(intake, release)`` in Mt CO2e; at most one is non-zero.
    """
    if prev_price is None or prev_surplus_ratio is None:
        return 0.0, 0.0

    high = float(getattr(market, "msr_price_band_high", DECREE_MSR_PRICE_BAND_HIGH))
    low = float(getattr(market, "msr_price_band_low", DECREE_MSR_PRICE_BAND_LOW))
    upper = float(getattr(market, "msr_surplus_upper_ratio", DECREE_MSR_SURPLUS_UPPER_RATIO))
    lower = float(getattr(market, "msr_surplus_lower_ratio", DECREE_MSR_SURPLUS_LOWER_RATIO))
    max_intake = float(getattr(market, "msr_max_intake_mt", DECREE_MSR_MAX_INTAKE_MT))
    max_release = float(getattr(market, "msr_max_release_mt", DECREE_MSR_MAX_RELEASE_MT))

    def price_signal() -> int:  # +1 release, -1 intake, 0 neutral
        if prev_price >= high:
            return 1
        if prev_price <= low:
            return -1
        return 0

    def surplus_signal() -> int:
        if prev_surplus_ratio <= lower:
            return 1
        if prev_surplus_ratio >= upper:
            return -1
        return 0

    if mode == "price_band":
        signal = price_signal()
    elif mode == "surplus_rule":
        signal = surplus_signal()
    else:  # hybrid: majority of the two signals, ties neutral
        total = price_signal() + surplus_signal()
        signal = 0 if total == 0 else (1 if total > 0 else -1)

    if signal > 0:
        return 0.0, min(max_release, max(0.0, reserve_stock))
    if signal < 0:
        return max_intake, 0.0
    return 0.0, 0.0


class DecreeSupplyRule:
    r"""K-MSR draft-decree MSR as a ``SupplyRule`` inside the banking fixed point.

    Implements ``ets.core.protocols.SupplyRule`` (work order O6). The body is
    the decree driver block of ``solvers/banking.py:_supply_schedule`` plus
    ``decree_msr_action`` (both lifted verbatim), so injected and inline
    behaviour are bit-identical.

    Output semantics: supply REPLACEMENT (see the protocol) —

    Algorithm:
        LaTeX:
        $$ S_t^{\mathrm{eff}} = A_t^{\mathrm{free}} + Q_t^{\mathrm{auction}}
           - w_t + r_t, \qquad R_t = R_{t-1} + w_t - r_t $$

        ASCII fallback:
            supply  = free_alloc + auction - intake + release
            reserve += intake - release      (release capped by the reserve)

        Symbols (units):
            S_t_eff     : circulating supply after the decree      [Mt CO2e]
            A_t_free    : total free allocation of year t          [Mt CO2e]
            Q_t_auction : scheduled auction volume of year t       [Mt CO2e]
            w_t, r_t    : decree intake / release in year t        [Mt CO2e]
            R_t         : decree reserve stock at end of year t    [Mt CO2e]

    Signals read only the lagged ``Observables`` computed by the banking
    host (previous solved price, previous surplus ratio); the first year is
    always neutral. ``initial_reserve_mt`` (scenario field
    ``msr_initial_reserve_mt``) funds ONLY this rule — never the
    bank-threshold rule (R7, ``docs/blocks-composition-rules.md``).

    Gating: the start-year threshold is fixed at CONSTRUCTION (the banking
    path reads ``msr_start_year`` from the first market only); a gated-off
    year returns the unadjusted supply with zero diagnostics.

    Lifecycle: stateful across years within one schedule evaluation (the
    reserve stock), PURE across evaluations — hosts construct a fresh
    instance per evaluation via a ``SupplyRuleFactory``
    (``ets.core.protocols`` module docstring; F4).
    """

    def __init__(
        self,
        mode: str,
        initial_reserve_mt: float = 0.0,
        start_year: float = 0.0,
    ) -> None:
        """Configure the decree rule for one schedule evaluation.

        Args:
            mode: ``"price_band"`` | ``"surplus_rule"`` | ``"hybrid"``.
            initial_reserve_mt: Pre-funded reserve stock [Mt CO2e]
                (``msr_initial_reserve_mt``; R7 — decree only).
            start_year: First calendar year the rule is active
                (``msr_start_year`` read from the scenario's first market;
                0.0 means always on).
        """
        self.mode = str(mode)
        self.reserve = float(initial_reserve_mt)
        self.start_year = float(start_year)

    def apply(self, market: CarbonMarket, obs: Observables) -> tuple[float, dict[str, float]]:
        """Compute the year's replacement circulating supply under the decree.

        Args:
            market: The year's market (``msr_*`` decree fields, auction
                volume, free allocation).
            obs: Lagged observables (previous solved price and surplus
                ratio; both ``None`` in a first year → neutral).

        Returns:
            ``(supply, diagnostics)`` — supply [Mt CO2e] and the
            ``msr_withheld`` / ``msr_released`` / ``msr_pool`` keys.
        """
        if not _msr_start_active(market, self.start_year):
            return (
                _free_allocation_total(market) + float(market.auction_offered),
                {"msr_withheld": 0.0, "msr_released": 0.0, "msr_pool": 0.0},
            )
        intake, release = decree_msr_action(
            market=market,
            mode=self.mode,
            prev_price=obs.prev_price,
            prev_surplus_ratio=obs.prev_surplus_ratio,
            reserve_stock=self.reserve,
        )
        self.reserve += intake - release
        supply = (
            _free_allocation_total(market)
            + float(market.auction_offered)
            - intake
            + release
        )
        return supply, {
            "msr_withheld": intake,
            "msr_released": release,
            "msr_pool": self.reserve,
        }
