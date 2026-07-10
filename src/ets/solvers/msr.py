"""
Market Stability Reserve (MSR) for ETS.

The MSR is a non-linear supply-adjustment mechanism that:
  - WITHHOLDS allowances from auction when the total banked volume is too high
    (excessive surplus → deflationary price pressure)
  - RELEASES previously withheld allowances when the bank is too low
    (shortage → inflationary price pressure)

Rule (applied before each year's auction):

    if total_bank > upper_threshold:
        withheld = min(msr_withhold_rate × auction_offered, auction_offered)
        reserve_pool += withheld
        effective_auction -= withheld

    elif total_bank < lower_threshold and reserve_pool > 0:
        released = min(msr_release_rate, reserve_pool)
        reserve_pool -= released
        effective_auction += released

The reserve_pool accumulates withheld allowances and persists across years.
Allowances cancelled by the MSR (if msr_cancel_excess=True) are permanently
removed once the pool exceeds msr_cancel_threshold.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

# MSR_DEFAULTS moved to core.defaults in O1 (still re-exported here so this
# module's surface is unchanged); the DECREE_* fallbacks joined in O6 when the
# decree rule moved here from solvers/banking.py.
from ..core.defaults import (  # noqa: F401
    DECREE_MSR_MAX_INTAKE_MT,
    DECREE_MSR_MAX_RELEASE_MT,
    DECREE_MSR_PRICE_BAND_HIGH,
    DECREE_MSR_PRICE_BAND_LOW,
    DECREE_MSR_SURPLUS_LOWER_RATIO,
    DECREE_MSR_SURPLUS_UPPER_RATIO,
    MSR_DEFAULTS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd

    from ..core.market.model import CarbonMarket
    from ..core.protocols import Observables

logger = logging.getLogger(__name__)


class MSRState:
    """
    Mutable state object carried across years for a single scenario.
    """

    def __init__(self, initial_reserve: float = 0.0) -> None:
        self.reserve_pool: float = float(initial_reserve)

    def apply(
        self,
        total_bank: float,
        auction_offered: float,
        upper_threshold: float,
        lower_threshold: float,
        withhold_rate: float,
        release_rate: float,
        cancel_excess: bool = False,
        cancel_threshold: float = 0.0,
        year_label: str = "",
    ) -> tuple[float, float, float]:
        """
        Apply MSR rule and return adjusted auction volume.

        Returns
        -------
        effective_auction : float   – auction supply after MSR adjustment
        withheld          : float   – Mt withheld this year (0 if no withholding)
        released          : float   – Mt released this year (0 if no release)
        """
        withheld = 0.0
        released = 0.0

        if total_bank > upper_threshold:
            withheld = min(withhold_rate * auction_offered, auction_offered)
            self.reserve_pool += withheld
            logger.debug(
                f"MSR [{year_label}]: bank={total_bank:.1f} > upper={upper_threshold:.1f} "
                f"→ withheld {withheld:.1f} Mt, pool now {self.reserve_pool:.1f} Mt"
            )

        elif total_bank < lower_threshold and self.reserve_pool > 0.0:
            released = min(release_rate, self.reserve_pool)
            self.reserve_pool -= released
            logger.debug(
                f"MSR [{year_label}]: bank={total_bank:.1f} < lower={lower_threshold:.1f} "
                f"→ released {released:.1f} Mt, pool now {self.reserve_pool:.1f} Mt"
            )

        # Optional: cancel allowances that have been in the pool too long
        if cancel_excess and self.reserve_pool > cancel_threshold:
            cancelled = self.reserve_pool - cancel_threshold
            self.reserve_pool = cancel_threshold
            logger.debug(
                f"MSR [{year_label}]: pool cancellation {cancelled:.1f} Mt "
                f"(pool > cancel_threshold {cancel_threshold:.1f})"
            )

        effective_auction = max(0.0, auction_offered - withheld + released)
        return effective_auction, withheld, released


class MSRCapRule:
    r"""Bank-threshold MSR as a ``CapRule`` on the competitive per-year pipeline.

    Implements ``ets.core.protocols.CapRule`` (work order O5). The rule body
    is lifted VERBATIM from the per-year MSR block of
    ``solvers/simulation.py:_simulate_path_details`` (the ``msr_active``
    gate + ``MSRState.apply`` call + the F1-fixed additive net adjustment),
    so injected and inline behaviour are bit-identical.

    Algorithm:
        LaTeX:
        $$ \Delta Q_t^{MSR} = r_t - w_t \qquad
           Q_t = \overline{Q}_t + \Delta Q_t^{CCR} + \Delta Q_t^{MSR} $$

        ASCII fallback:
            delta_q = released - withheld;  effective_carry += delta_q

        Symbols (units):
            w_t : MSR withholding from auction in year t   [Mt CO2e]
            r_t : MSR release from the reserve pool        [Mt CO2e]

    Gating: ``pre_clear`` requires the per-year ``msr_enabled`` flag AND
    ``year >= msr_start_year`` (non-numeric year labels leave the rule
    active). ``post_clear`` is a no-op — the bank the MSR reads is host
    state (beginning-of-year bank balances), not rule-recorded state.

    Lifecycle: stateful across years within one path evaluation (the
    ``MSRState`` reserve pool); construct a fresh instance per evaluation
    (see ``ets.core.protocols`` module docstring).
    """

    def __init__(self, msr_state: MSRState | None = None) -> None:
        self.msr_state = msr_state if msr_state is not None else MSRState()

    def pre_clear(
        self, market: CarbonMarket, state: Mapping[str, float]
    ) -> tuple[float, dict[str, float]]:
        """Withhold/release against the beginning-of-year bank; return the net.

        Args:
            market: The year's market (``msr_*`` fields).
            state: Beginning-of-year bank balances by participant [Mt CO2e].

        Returns:
            ``(msr_net, diagnostics)`` with ``msr_net = released - withheld``
            [Mt CO2e] and diagnostics keys ``msr_withheld`` / ``msr_released``
            / ``msr_pool``.
        """
        msr_withheld = 0.0
        msr_released = 0.0
        msr_pool = 0.0

        msr_active = getattr(market, "msr_enabled", False)
        if msr_active:
            try:
                msr_active = float(str(market.year)) >= float(
                    getattr(market, "msr_start_year", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                pass  # non-numeric year labels: rule active
        if msr_active:
            total_bank = sum(state.values())
            _, msr_withheld, msr_released = self.msr_state.apply(
                total_bank=total_bank,
                auction_offered=market.auction_offered,
                upper_threshold=float(
                    getattr(market, "msr_upper_threshold", MSR_DEFAULTS["msr_upper_threshold"])
                ),
                lower_threshold=float(
                    getattr(market, "msr_lower_threshold", MSR_DEFAULTS["msr_lower_threshold"])
                ),
                withhold_rate=float(
                    getattr(market, "msr_withhold_rate", MSR_DEFAULTS["msr_withhold_rate"])
                ),
                release_rate=float(
                    getattr(market, "msr_release_rate", MSR_DEFAULTS["msr_release_rate"])
                ),
                cancel_excess=bool(getattr(market, "msr_cancel_excess", False)),
                cancel_threshold=float(
                    getattr(market, "msr_cancel_threshold", MSR_DEFAULTS["msr_cancel_threshold"])
                ),
                year_label=str(market.year),
            )
            msr_pool = self.msr_state.reserve_pool

        # Inject the MSR net adjustment as carry-forward so solve_equilibrium
        # sees it (released adds to supply, withheld subtracts; the adjusted
        # auction volume returned by apply() is deliberately unused).
        # Compose additively with any CCR cap adjustment already applied:
        #   Q_t = Qbar + ΔQ_t^CCR + ΔQ_t^MSR   (F1 fix, blocks-composition-rules §0)
        msr_net = msr_released - msr_withheld
        return msr_net, {
            "msr_withheld": msr_withheld,
            "msr_released": msr_released,
            "msr_pool": msr_pool,
        }

    def post_clear(self, market: CarbonMarket, participant_df: pd.DataFrame) -> None:
        """No-op: the MSR reads host bank state, not rule-recorded state."""


# ──────────────────────────────────────────────────────────────────────────────
# SupplyRule implementations for the banking fixed point (work order O6).
# Bodies lifted VERBATIM from solvers/banking.py's _supply_schedule branches
# so injected and inline behaviour are bit-identical (F4 golden gate).
# ──────────────────────────────────────────────────────────────────────────────


def _free_allocation_total(market: CarbonMarket) -> float:
    """Total free allocation of a year [Mt CO2e] (as in the banking host)."""
    return float(sum(p.free_allocation for p in market.participants))


def _msr_start_active(market: CarbonMarket, msr_start: float) -> bool:
    """Per-year start gate against a CONSTRUCTION-time threshold.

    The threshold is read from the scenario's FIRST market by the banking
    wiring (``banking._default_supply_rule_factories``) — the banking path's
    m0-only read, unlike the competitive path's per-year read in
    ``MSRCapRule.pre_clear`` (documented F2-family asymmetry; see the
    factory-builder). Lifted verbatim from ``_supply_schedule``'s
    ``_msr_active`` closure.

    Args:
        market: The year's market (only ``year`` is read).
        msr_start: Start-year threshold [calendar year]; 0.0 means always on.

    Returns:
        True when the rule is active in the market's year.
    """
    try:
        return float(str(market.year)) >= msr_start
    except (TypeError, ValueError):
        return True  # non-numeric year labels: rule active


def _decree_msr_action(
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
    ``_decree_msr_action`` (both lifted verbatim), so injected and inline
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
        intake, release = _decree_msr_action(
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


class ThresholdMSRSupplyRule:
    r"""Bank-threshold MSR as a ``SupplyRule`` inside the banking fixed point.

    Implements ``ets.core.protocols.SupplyRule`` (work order O6). The body is
    the bank-threshold branch of ``solvers/banking.py:_supply_schedule``
    lifted verbatim, with the ``getattr`` fallbacks sourced from
    ``core.defaults.MSR_DEFAULTS`` byte-identically (the O1 fix — default
    values are typed exactly once in the codebase, never re-typed here).

    Output semantics: supply REPLACEMENT (see the protocol) —

    Algorithm:
        LaTeX:
        $$ S_t^{\mathrm{eff}} = A_t^{\mathrm{free}} +
           \max\!\big(0,\; Q_t^{\mathrm{auction}} - w_t + r_t\big) $$
        with
        $$ w_t = \min(\gamma Q_t^{\mathrm{auction}},\, Q_t^{\mathrm{auction}})
           \;\text{ if } B_{t-1} > \overline{B}, \qquad
           r_t = \min(\rho,\, R_{t-1}) \;\text{ if } B_{t-1} < \underline{B} $$

        ASCII fallback:
            bank > upper  -> withhold rate*auction into the pool
            bank < lower  -> release min(release_rate, pool)
            supply = free_alloc + max(0, auction - withheld + released)

        Symbols (units):
            S_t_eff     : circulating supply after the rule        [Mt CO2e]
            A_t_free    : total free allocation of year t          [Mt CO2e]
            Q_t_auction : scheduled auction volume of year t       [Mt CO2e]
            B_{t-1}     : beginning-of-year aggregate bank         [Mt CO2e]
            Bbar, Bund  : upper / lower bank thresholds            [Mt CO2e]
            gamma       : withhold rate [1/yr, share of auction]
            rho         : release rate                             [Mt CO2e/yr]
            w_t, r_t    : withholding / release in year t          [Mt CO2e]
            R_{t-1}     : reserve pool at start of year t          [Mt CO2e]

    The rule reads only ``Observables.begin_bank`` (the solver's aggregate
    bank carried into the year) — never same-iteration outcomes (F4).

    NO initial reserve, EVER: ``msr_initial_reserve_mt`` funds only the
    decree rule (R7, ``docs/blocks-composition-rules.md``); the threshold
    pool starts empty on every construction. This is also why a policy-event
    splice RESETS a bank-threshold pool per segment while a decree carries
    its reserve (``docs/banking-equilibrium.md``).

    Lifecycle: stateful across years within one schedule evaluation (the
    ``MSRState`` reserve pool), PURE across evaluations — construct fresh
    per evaluation via a ``SupplyRuleFactory``.
    """

    def __init__(self, start_year: float = 0.0) -> None:
        """Configure the threshold rule for one schedule evaluation.

        Args:
            start_year: First calendar year the rule is active
                (``msr_start_year`` read from the scenario's first market;
                0.0 means always on).
        """
        self.msr_state = MSRState()
        self.start_year = float(start_year)

    def apply(self, market: CarbonMarket, obs: Observables) -> tuple[float, dict[str, float]]:
        """Compute the year's replacement circulating supply under the rule.

        Args:
            market: The year's market (``msr_*`` threshold fields, auction
                volume, free allocation).
            obs: Lagged observables; only ``begin_bank`` is read.

        Returns:
            ``(supply, diagnostics)`` — supply [Mt CO2e] and the
            ``msr_withheld`` / ``msr_released`` / ``msr_pool`` keys.
        """
        if not _msr_start_active(market, self.start_year):
            return (
                _free_allocation_total(market) + float(market.auction_offered),
                {"msr_withheld": 0.0, "msr_released": 0.0, "msr_pool": 0.0},
            )
        adj_auction, withheld, released = self.msr_state.apply(
            total_bank=obs.begin_bank,
            auction_offered=float(market.auction_offered),
            upper_threshold=float(
                getattr(market, "msr_upper_threshold", MSR_DEFAULTS["msr_upper_threshold"])
            ),
            lower_threshold=float(
                getattr(market, "msr_lower_threshold", MSR_DEFAULTS["msr_lower_threshold"])
            ),
            withhold_rate=float(
                getattr(market, "msr_withhold_rate", MSR_DEFAULTS["msr_withhold_rate"])
            ),
            release_rate=float(
                getattr(market, "msr_release_rate", MSR_DEFAULTS["msr_release_rate"])
            ),
            cancel_excess=bool(getattr(market, "msr_cancel_excess", False)),
            cancel_threshold=float(
                getattr(market, "msr_cancel_threshold", MSR_DEFAULTS["msr_cancel_threshold"])
            ),
            year_label=str(market.year),
        )
        supply = _free_allocation_total(market) + adj_auction
        return supply, {
            "msr_withheld": withheld,
            "msr_released": released,
            "msr_pool": self.msr_state.reserve_pool,
        }
