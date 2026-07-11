"""Bank-threshold MSR rules (T2 runtime, engine/host-facing).

``MSRCapRule`` (competitive per-year pipeline, ``core.protocols.CapRule``)
and ``ThresholdMSRSupplyRule`` (banking fixed point,
``core.protocols.SupplyRule``), moved VERBATIM from ``solvers/msr.py`` in
the engine work order (v1 O8 / v2 O12, ``docs/feature-modules-plan.md``).
The mutable ``MSRState`` lives in ``state.py``; the K-MSR draft-decree rule
in ``decree.py``. Wired by ``ets.engine.wiring`` — never imported by other
features or by ``config_io``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.defaults import MSR_DEFAULTS
from .state import MSRState

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd

    from ...core.market.model import CarbonMarket
    from ...core.protocols import Observables


class MSRCapRule:
    r"""Bank-threshold MSR as a ``CapRule`` on the competitive per-year pipeline.

    Implements ``ets.core.protocols.CapRule`` (work order O5). The rule body
    is lifted VERBATIM from the per-year MSR block of the competitive
    pipeline (now ``core/ledger.py:simulate_path_details``; the ``msr_active``
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
    wiring (``engine.wiring.default_supply_rule_factories``) — the banking
    path's m0-only read, unlike the competitive path's per-year read in
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
