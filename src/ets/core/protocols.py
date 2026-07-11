r"""Rule and overlay protocols for the feature-module architecture (T0 kernel).

Structural contracts (``typing.Protocol``) between the composition engine and
the feature packages, per ``docs/feature-modules-plan.md`` (PLAN v2 §2
"Protocol family" and the binding Arbitration outcomes). This module defines
protocols ONLY — no rule logic lives here. Implementations live with their
mechanisms (e.g. ``MSRCapRule`` in the MSR module, ``CCRCapRule`` in the CCR
module) and are wired by the engine.

Rule lifecycle doctrine (binding, economist review of PLAN v2)
--------------------------------------------------------------
Rules are **stateful ACROSS YEARS within one evaluation** of a scenario path
(the MSR reserve pool persists year to year; the CCR carries last year's
realised emissions and abatement cost), but must be **PURE across solver
invocations and across fixed-point iterations**: re-evaluating the same
schedule twice from the same inputs must produce the same outputs.
Operationally:

* Hosts obtain a **fresh rule instance per schedule evaluation** — either by
  calling a factory (``CapRuleFactory`` / ``SupplyRuleFactory``) at the start
  of the evaluation, or by calling an implementation-provided ``reset()``
  before the first year. The engine wires FACTORIES, never shared instances,
  so no rule state can leak between scenarios, between solver invocations, or
  between iterations of a fixed-point loop.
* When a mechanism composes INSIDE a fixed-point path solve (bank-triggered
  MSR on the banking equilibrium; floor-with-cancellation feeding back into
  supply — F4, ``docs/blocks-composition-rules.md`` §0), the solver re-invokes
  the rule schedule each iteration on a freshly constructed/reset rule. The
  only mutable state that survives an iteration boundary is the host's own
  declared state (the supply schedule iterate), never hidden rule internals.
* Within one evaluation, rules read only **lagged / beginning-of-period
  state** (previous bank, previous price, previously realised emissions) —
  never same-period outcomes, which would be a simultaneity the per-year
  clearing cannot resolve.

Composition doctrine (order is economics, and it is explicit)
-------------------------------------------------------------
Supply operators act BEFORE clearing; price formation is the hub (one mode
per scenario); price overlays act AFTER clearing in a documented, tested
order (λ blend FIRST, floor clip LAST — F3). The wiring order of rules is a
reviewed source literal in the host, never a registry: CCR before MSR on the
competitive per-year pipeline (F1), MSR before floor-cancellation inside the
banking fixed point (``docs/blocks-composition-rules.md`` §2).

Path feedback (endogenous investment) sits OUTSIDE all of the above: an
outer loop around the FULL path solve — strictly outside the expectations
inner loop (R29) and outside ``solve_banking_path`` (spec D1.3). One fresh
``PathFeedback`` instance per outer iteration (factory-wired); the
host-owned ``AdoptionState`` is the only cross-iteration state; monotone
one-flip termination is HOST-enforced (spec D1.4). See ``PathFeedback``.

References:
    docs/feature-modules-plan.md — PLAN v2 §2 protocol family; Arbitration
    outcomes (O7-O10 binding conditions).
    docs/blocks-composition-rules.md — engine findings F1-F6, rules R1-R32.
    docs/forward-transmission.md — blend-then-clip (transmission immunity).
    docs/invest-feedback-spec.md — binding economic spec D1-D6 (adoption
    contracts); docs/invest-feedback-plan.md — "Kernel contracts".
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, runtime_checkable

if TYPE_CHECKING:
    import pandas as pd

    from .market.model import CarbonMarket
    from .participant.models import ComplianceOutcome, MarketParticipant

__all__ = [
    "AdoptionEvent",
    "AdoptionSpec",
    "AdoptionState",
    "CapRule",
    "CapRuleFactory",
    "DemandOverlay",
    "Friction",
    "Observables",
    "ParticipantReporter",
    "ParticipantTransform",
    "PathFeedback",
    "PathFeedbackFactory",
    "PriceOverlay",
    "SpliceCarrier",
    "SummaryReporter",
    "SupplyRule",
    "SupplyRuleFactory",
    "make_adoption_state",
    "parse_adoption_state",
    "serialize_adoption_state",
]


# ──────────────────────────────────────────────────────────────────────────────
# Supply operators — act BEFORE clearing, read only lagged state
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class CapRule(Protocol):
    r"""Per-year cap adjustment on the competitive per-year pipeline.

    A cap rule adjusts the quantity of permits the year's clearing sees
    (MSR withhold/release; the Benmir-Roman-Taschini carbon cap rule) and,
    after clearing, records realised aggregates as the next period's lagged
    signal.

    Composition is ADDITIVE in wiring-literal order (F1,
    ``docs/blocks-composition-rules.md`` §0 — fixed in Order 1b; the reviewed
    literal puts CCR before MSR):

    Algorithm:
        LaTeX:
        $$ Q_t \;=\; \overline{Q}_t \;+\; \sum_i \Delta Q_t^{(i)} $$

        ASCII fallback:
            effective_carry = carry_forward; for each rule i (in list order):
                effective_carry += delta_q_i

        Symbols (units):
            Q_t          : effective permit supply cleared in year t [Mt CO2e]
            Qbar_t       : scheduled supply (auction + carry-forward) [Mt CO2e]
            delta_q_i    : rule i's supply adjustment for year t      [Mt CO2e]
                           (MSR: released - withheld; CCR: ΔQ_t from the
                           lagged deviation rule)

    Gating is SPLIT, and the split is economics, not symmetry:

    * ``pre_clear`` is gated by the per-year enable flag AND the rule's
      start-year (``msr_start_year`` / ``ccr_start_year``): no supply
      adjustment before the mechanism legally exists.
    * ``post_clear`` is gated by the per-year enable flag ONLY — NO
      start-year condition. Pre-start years still accumulate the lagged
      signal (realised emissions e_{t-1} and abatement cost z_{t-1}), so the
      rule's first ACTIVE year prices the last pre-start year's outcomes
      instead of starting blind. This mirrors how a real regulator observes
      the market before the rule takes effect.

    Rules read only beginning-of-period state: the previous end-of-year bank
    (passed as ``state``) and their own recorded lagged aggregates — never
    same-period clearing outcomes.

    References:
        Benmir, G., Roman, J. and Taschini, L. (2025). "Weitzman meets
        Taylor: EU allowance price drivers and carbon cap rules." Grantham
        Research Institute Working Paper No. 421, LSE. (CCR)
        docs/blocks-composition-rules.md §0 F1, §2 item 1. (composition)
    """

    def pre_clear(
        self, market: CarbonMarket, state: Mapping[str, float]
    ) -> tuple[float, dict[str, float]]:
        """Compute the year's supply adjustment before clearing.

        Args:
            market: The year's market (carries the rule's per-year config
                fields and enable flag).
            state: Beginning-of-year bank balances by participant name
                [Mt CO2e] — LAGGED state (previous end-of-year balances).

        Returns:
            ``(delta_q, diagnostics)`` — the additive supply adjustment
            [Mt CO2e] (0.0 when the rule is gated off this year) and the
            rule's diagnostics columns (merged into the year's details row;
            key order is part of the contract — baselines are
            column-order-sensitive).
        """
        ...

    def post_clear(self, market: CarbonMarket, participant_df: pd.DataFrame) -> None:
        """Record realised aggregates as the next period's lagged signal.

        Gated by the per-year enable flag ONLY (no start-year condition —
        see class docstring). Must not mutate ``participant_df`` or the
        market; the only permitted side effect is the rule's own lagged
        state.

        Args:
            market: The year's market (per-year enable flag).
            participant_df: The year's solved participant results frame.
        """
        ...


@dataclass(frozen=True, kw_only=True)
class Observables:
    """Lagged observables a supply rule may condition on (frozen, keyword-only).

    One instance per (year, schedule-evaluation); constructed by the banking
    host from beginning-of-year state. All fields are keyword-only so the
    dataclass is EXTENSIBLE: later work orders add new observables as
    keyword-only fields WITH neutral defaults, never breaking existing
    constructor calls or reordering positional arguments.

    Attributes:
        begin_bank: Aggregate bank carried into the year [Mt CO2e]
            (previous end-of-year bank; the scenario's initial bank in the
            first year).
        prev_price: Previous year's solved allowance price [currency/tCO2];
            ``None`` in the first year (decree signals are neutral without
            history — banking host, ``_decree_msr_action``).
        prev_surplus_ratio: Previous end-of-year bank over previous realised
            emissions [dimensionless]; ``None`` in the first year.
        year_label: The year's label (e.g. ``"2031"``), for start-year gates
            and logging.
    """

    begin_bank: float
    prev_price: float | None = None
    prev_surplus_ratio: float | None = None
    year_label: str = ""


@runtime_checkable
class SupplyRule(Protocol):
    r"""Per-year circulating-supply rule inside the banking fixed point.

    Output semantics: **supply REPLACEMENT**, not a delta. The rule returns
    the year's full circulating supply after its adjustment (the banking
    host's schedule slot is overwritten):

    Algorithm:
        LaTeX:
        $$ S_t^{\mathrm{eff}} \;=\; f\big(\text{market}_t,\;
           \text{obs}_t\big) $$
        e.g. the threshold MSR:
        $$ S_t^{\mathrm{eff}} = A_t^{\mathrm{free}} +
           \max(0,\, Q_t^{\mathrm{auction}} - w_t + r_t) $$

        ASCII fallback:
            supplies[t] = rule.apply(markets[t], obs_t)[0]   (replacement)

        Symbols (units):
            S_t_eff      : circulating supply after the rule      [Mt CO2e]
            A_t_free     : total free allocation of year t        [Mt CO2e]
            Q_t_auction  : scheduled auction volume of year t     [Mt CO2e]
            w_t, r_t     : rule withholding / release in year t   [Mt CO2e]

    Evaluation timing (F4, binding): supply rules are evaluated INSIDE the
    banking fixed point only — the solver iterates window-solve ↔
    supply-schedule until the schedule is stable, and the rule is re-invoked
    on every iteration via a fresh instance or ``reset()`` (see module
    docstring). Moving rule evaluation outside the fixed point computes a
    DIFFERENT equilibrium; import isolation cannot detect that — only the
    golden gate can. Rules read only the lagged ``Observables``, never
    same-iteration outcomes.

    Wiring order inside the fixed point is a reviewed source literal:
    MSR first, floor-cancellation second (``docs/blocks-composition-rules.md``
    §2 item 3).

    References:
        Rubin (1996) JEEM 31(3); Schennach (2000) JEEM 40(3) — host
        equilibrium. PLANiT K-MSR working paper (July 2026) — decree rule.
        docs/blocks-composition-rules.md §0 F4.
    """

    def apply(self, market: CarbonMarket, obs: Observables) -> tuple[float, dict[str, float]]:
        """Compute the year's replacement circulating supply.

        Args:
            market: The year's market (rule config fields, auction volume,
                free allocation).
            obs: Lagged observables for the year (see ``Observables``).

        Returns:
            ``(supply, diagnostics)`` — the year's full circulating supply
            after the rule [Mt CO2e] (the unadjusted supply when the rule is
            gated off), and the rule's diagnostics columns.
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Price and demand overlays
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class PriceOverlay(Protocol):
    r"""Post-clearing transformation of the solved price (clip-LAST).

    Price overlays act AFTER price formation, in a documented, tested order:
    the λ blend is applied FIRST, the floor clip LAST. Clip-last is what
    makes the reserve-price floor transmission-immune (F3,
    ``docs/forward-transmission.md``; operation-order test in
    ``tests/test_transmission.py``) — clipping components before blending
    would deliver ``(1-λ)·F_t + λ·P_hot > F_t`` in floor-bound years, a
    different (wrong) object. A drawn composition graph must never reorder
    this.

    Algorithm:
        LaTeX:
        $$ P_t^{\mathrm{delivered}} = \max\big(P_t,\; F_t\big) $$

        ASCII fallback:
            delivered(price, market) = max(price, floor_t)   (floor overlay)

        Symbols (units):
            P_t : solved (possibly blended) price of year t  [currency/tCO2]
            F_t : the year's auction reserve price; 0 unset  [currency/tCO2]

    Overlays are attach-always: with the neutral configuration (floor 0) the
    overlay is exact, since ``max(p, 0) = p`` for every solved price
    ``p >= 0`` (Arbitration outcomes, O10).
    """

    def delivered(self, price: float, market: CarbonMarket) -> float:
        """Transform the solved price into the delivered price.

        Args:
            price: Solved price after price formation (and after any
                earlier overlay in the wiring literal) [currency/tCO2].
            market: The year's market (overlay config fields, e.g.
                ``auction_reserve_price``).

        Returns:
            Delivered price [currency/tCO2].
        """
        ...


@runtime_checkable
class DemandOverlay(Protocol):
    r"""Price-elastic scaling of a participant's BAU baseline (Option A).

    Called INSIDE the compliance demand function at today's call site
    (``core/participant/models.py`` ``activity_multiplier``): the baseline
    emissions, abatement potential, and benchmarked free allocation all
    scale by the returned multiplier before the compliance optimisation.
    This is a demand-side channel, so unlike price overlays it feeds BACK
    into clearing — it is part of price formation, not a post-processing
    step.

    Algorithm:
        LaTeX:
        $$ m(P) = \max\!\left(0,\; 1 - \varepsilon\,
           \frac{P - P_{\mathrm{ref}}}{P_{\mathrm{ref}}}\right) $$

        ASCII fallback:
            m(P) = max(0, 1 - eps * (P - P_ref) / P_ref)

        Symbols (units):
            P     : carbon price                            [currency/tCO2]
            P_ref : reference (undistorted) carbon price    [currency/tCO2]
            eps   : output_price_elasticity, dimensionless, >= 0

    Neutral behaviour is ``1.0`` (no feedback); implementations must return
    1.0 when their channel is disabled (ε <= 0 or P_ref <= 0), so an
    attached-but-unconfigured overlay is a no-op.
    """

    def baseline_multiplier(self, price: float) -> float:
        """Return the baseline activity multiplier at a carbon price.

        Args:
            price: Carbon price P [currency/tCO2].

        Returns:
            Dimensionless multiplier m(P) >= 0; 1.0 means no feedback.
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Build-time participant transforms
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class ParticipantTransform(Protocol):
    """Pure build-time transform of a raw participant config dict.

    Runs in the config builder's per-year pipeline BEFORE participant
    objects are constructed, so dataclass validation sees final values
    (sector-derived allocation, trajectory patches, OBA overrides —
    ``config_io/builder.py``). Transforms compose as a reviewed source
    literal in today's order; the order is load-bearing and pinned:

    * OBA runs AFTER the trajectory patch (it reads the patched
      ``initial_emissions``, builder.py:419), and its overwrite of the
      sectors-written ``free_allocation_ratio`` (builder.py:389 vs :422) is
      a PINNED cross-feature coupling through the raw-dict medium —
      precedence OBA > sector > per-year (Arbitration outcomes, O9).

    Declared-fields discipline: every implementation MUST declare in its
    docstring exactly which raw-dict fields it reads and which it writes.
    Two transforms may couple only through declared fields; an undeclared
    read/write is a review error.

    Purity contract: ``apply`` never mutates ``raw`` (or ``meta``) — it
    returns a NEW dict (today's builder uses ``{**p, ...}`` copies).
    """

    def apply(
        self, raw: dict[str, Any], year_num: float, meta: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Transform one raw participant dict for one scenario year.

        Args:
            raw: The participant's raw config dict for this year. Must not
                be mutated.
            year_num: Numeric year (e.g. ``2031.0``) used by trajectory
                interpolation.
            meta: Scenario-level config mapping (read-only): sector
                definitions, trajectories, scenario fields.

        Returns:
            A new participant dict with this transform's declared writes
            applied (may be ``raw`` itself only if nothing changed).
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Market frictions
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class Friction(Protocol):
    r"""Exogenous per-year withdrawal of allowances from circulation (hoarding).

    THIS PROTOCOL'S CONTRACT IS THE HOARDING SEMANTICS — it does not promise
    a general friction hook (Arbitration outcomes, O10). The banking host
    owns the window-start math; the pinned semantics are:

    1. **Exogenous withdrawal.** ``inflow`` returns h_t [Mt CO2e], removed
       from the year's circulating supply before static clearing: the static
       year clears at ``S_t - h_t`` (banking host, static-year supply
       reduction), which RAISES the static price.
    2. **Forced static regime.** Hoarding years are static-regime years BY
       DEFINITION: the banking window never starts at or before a year with
       ``h_t > 0`` — the host enforces ``a > max{t : h_t > 0}``. The
       friction is meaningless inside an arbitrage window.
    3. **Inflow accrues to the window budget.** The hoarded volume is not
       cancelled: it accumulates in the aggregate bank (each static hoarding
       year adds exactly h_t) and re-enters the window budget when the
       drawdown window opens (``incoming_bank = initial_bank + Σ h_t``).
    4. **No-arbitrage prune exemption.** Transitions OUT of a hoarding year
       are exempt from the pre-window no-arbitrage check — hoarding is the
       DOCUMENTED λ ≈ 0 violation (K-MSR paper's reading of the KAU market:
       compliance entities bank against future tightening without pricing
       the carry), so a hoarding year is allowed to violate
       ``P_{t+1} <= (1+g) P_t``. Scenarios usually need
       ``banking_strict_no_arbitrage: false``.

    Algorithm:
        ASCII: static years  : clear e_t(p) = S_t - h_t
               window budget : B_a- = B_0 + sum_{t<a} h_t
               window start  : a > max{t : h_t > 0}

        Symbols (units):
            h_t  : hoarding inflow of year t                     [Mt CO2e]
            S_t  : circulating supply (free alloc + auction)     [Mt CO2e]
            B_a- : bank carried into the banking window          [Mt CO2e]
            g    : carry rate r + rho                            [1/yr]

    Neutral behaviour: ``0.0`` (no hoarding, textbook equilibrium).
    """

    def inflow(self, market: CarbonMarket) -> float:
        """Return the year's hoarding inflow h_t.

        Args:
            market: The year's market (friction config fields).

        Returns:
            Withdrawn volume h_t [Mt CO2e]; 0.0 when disabled.
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Reporting (post-clearing diagnostics — never a price channel, F6)
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class ParticipantReporter(Protocol):
    """Per-participant diagnostics columns for the participant results frame.

    Reporters are post-clearing overlays: they read the solved outcome and
    emit columns; they never feed back into price formation (F6 — CBAM is a
    reporting overlay, not a price channel; the mechanical invariant).

    Reporters are ATTACH-ALWAYS: every scenario gets every reporter, and an
    unconfigured reporter emits its columns with neutral (zero) values —
    this keeps the participant frame's column set, and therefore the golden
    baselines' column order, independent of scenario configuration.

    The returned dict is ORDERED: insertion order is column order, and hosts
    concatenate reporter dicts in a reviewed stage literal, so column order
    in the output frame is pinned by (literal order, dict order). Year
    placement is per-host (participant record tail — Arbitration outcomes,
    O7).
    """

    def columns(
        self,
        market: CarbonMarket,
        participant: MarketParticipant,
        outcome: ComplianceOutcome,
        price: float,
    ) -> dict[str, float | str]:
        """Compute this reporter's columns for one participant-year.

        Args:
            market: The year's market (reporter config, e.g. EUA prices).
            participant: The participant (reporter attributes, e.g. CBAM
                exposure fields).
            outcome: The participant's solved compliance outcome.
            price: The year's delivered allowance price [currency/tCO2].

        Returns:
            Ordered mapping of column name to value; neutral (zero) values
            when the reporter is unconfigured.
        """
        ...


@runtime_checkable
class SummaryReporter(Protocol):
    """One ordered stage of the scenario-summary assembly.

    Hosts hold a reviewed literal of stages and call them in order; each
    stage RECEIVES THE ACCUMULATING summary dict and appends its columns
    in place (insertion order is column order). Stages are NOT independent —
    they are order-sensitive by contract:

    * the EUA-ensemble totals stage deduplicates against columns already
      written by the per-jurisdiction stage via ``col not in summary``
      (``core/market/reporting.py``), so swapping those stages changes the
      output;
    * the CBAM totals stage runs after the revenue tracker (it reads
      ``Total Auction Revenue`` from the accumulating dict);
    * Year placement is per-host (summary mid-dict after the CCR
      placeholders — Arbitration outcomes, O7).

    Reporters are ATTACH-ALWAYS (see ``ParticipantReporter``): unconfigured
    scenarios keep zero-valued columns so the summary column set is stable.
    """

    def contribute(
        self,
        summary: dict[str, float | str],
        market: CarbonMarket,
        participant_df: pd.DataFrame,
        price: float,
    ) -> None:
        """Append this stage's columns to the accumulating summary.

        Args:
            summary: The ACCUMULATING summary dict — read for
                order-sensitive dedup (``col not in summary``) and mutated
                in place by appending this stage's columns.
            market: The year's market.
            participant_df: The year's solved participant results frame
                (read-only).
            price: The year's delivered allowance price [currency/tCO2].
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Policy-event splicing
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SpliceCarrier:
    """Declaration of one state variable carried across policy-event segments.

    Policy events re-solve the remaining horizon at each announcement and
    splice the kept segments (``solvers/events.py``); physical state must
    survive the splice. A carrier reads ``column`` from the LAST KEPT summary
    row of the finished segment and stamps it into ``config_field`` of the
    next segment's scenario config — but only when ``carry_if`` holds.

    ``carry_if`` is evaluated on the segment's scenario config as it stood
    when the segment was solved (BEFORE the next announcement's changes are
    applied). This encodes the ``msr_ran_last_segment`` condition: the MSR
    reserve pool is carried state only if the rule actually ran in the
    previous segment — a decree announced mid-horizon with a pre-funded
    reserve (``msr_initial_reserve_mt`` in its changes) must KEEP that
    funding rather than have it overwritten by a stale carried pool. The
    aggregate bank, by contrast, is always carried (its predicate is
    always-true).

    Attributes:
        column: Summary column holding the segment-final state (e.g.
            ``"Banking Aggregate Bank"``, ``"MSR Reserve Pool"``).
        config_field: Scenario config field to stamp on the next segment
            (e.g. ``"banking_initial_bank"``, ``"msr_initial_reserve_mt"``).
        carry_if: Predicate on the finished segment's scenario config; the
            carried value is stamped only when it returns ``True``.
    """

    column: str
    config_field: str
    carry_if: Callable[[Mapping[str, Any]], bool]


# ──────────────────────────────────────────────────────────────────────────────
# Endogenous investment — adoption contracts (outer loop around the full solve)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class AdoptionSpec:
    r"""Per-(participant, technology) irreversible-investment trigger declaration.

    One frozen spec per flagged (participant, technology) pair — the
    parameter half of the endogenous-investment feedback loop
    (``docs/invest-feedback-spec.md`` D2/D6; plan "Kernel contracts").
    The spec carries PARAMETERS ONLY: trigger evaluation lives in
    ``core.investment`` (the single source of the Dixit–Pindyck math —
    implementations call ``trigger_multiple``/``effective_volatility``/
    ``activation_year``, never re-derive), and adoption STATE lives in the
    host-owned ``AdoptionState``, never in the spec.

    Algorithm:
        The trigger rule this spec parameterizes (spec D2.1):

        LaTeX:
        $$ P^*_j(t) = M_j\,\theta_j(t), \qquad
           M_j = \frac{\beta(\sigma_{\mathrm{eff}}, r, y)}
                      {\beta(\sigma_{\mathrm{eff}}, r, y) - 1}, \qquad
           \sigma_{\mathrm{eff}} = (1 - q)\,\sigma $$

        ASCII fallback:
            P_star(t) = M * break_even(t)
            M = trigger_multiple(sigma_eff, r, y); sigma_eff = (1 - q) * sigma
            trigger_mode == "break_even"  =>  M = 1  (NPV activation dating)
            trigger_multiple_override set =>  M pinned directly (>= 1)

        Symbols (units):
            theta(t) : ``break_even`` — Marshallian break-even price,
                       scalar or {year label: value}     [currency/tCO2]
            sigma    : annualized price volatility        [1/sqrt(yr)]
            q        : ``credibility`` of the announced price schedule
                       in the binding region              [dimensionless, [0,1]]
            r        : ``discount_rate`` (None -> the scenario's
                       discount_rate at rule construction) [1/yr]
            y        : ``payout_yield`` — payout/convenience yield of
                       the completed project              [1/yr]
            M        : trigger multiple P*/theta          [dimensionless, >= 1]

    CERTAINTY LIMIT (spec D5 correction; K-MSR paper A.10): ``sigma = 0``
    gives ``M = r/y`` (≈ 1.83 at r = .055, y = .03), NOT 1 — the pure
    timing wedge survives under certainty because the deferred sunk outlay
    keeps appreciating. NPV break-even dating is ``trigger_mode =
    "break_even"``, a MODE, not the σ→0 limit. The interior credibility
    mapping ``sigma_eff = (1 - q) * sigma`` is linear-in-σ by DOCUMENTED
    MODELLING CHOICE: the paper defines only the endpoints (σ_eff(0) = σ,
    σ_eff(1) = 0) and records the interior as ambiguous (A.10; question
    recorded for the authors) — see ``core.investment.effective_volatility``.

    Attributes:
        participant_name: Name of the ``MarketParticipant`` this spec flags
            (matched by name; the participant object is never referenced).
        technology_name: Name of the flagged ``TechnologyOption`` on that
            participant (specs reference by name; ``TechnologyOption``
            itself is unchanged — plan "Kernel contracts").
        break_even: θ(t), Marshallian break-even price [currency/tCO2] —
            scalar, or {year label: value} for input-price-endogenous
            thresholds. REQUIRED, no default; values must be finite and
            > 0. Missing-year lookups raise at evaluation
            (``core.investment.activation_year`` semantics, spec D2.1).
        payout_yield: y [1/yr]. REQUIRED, no default — r/y is the
            certainty-limit hurdle; "a defaulted y is an economic constant
            hiding in a fallback" (spec D2.1). Must be finite and > 0.
        sigma: σ [1/sqrt(yr)], annualized volatility of the price the
            investor faces — an INPUT (e.g. the paper's pooled KAU estimate
            σ ≈ 0.48), never an engine output. Finite, >= 0. Default 0.0.
        credibility: q [dimensionless], probability the announced price
            schedule holds in the binding region. In [0, 1]. Default 0.0.
        discount_rate: r [1/yr], or ``None`` to inherit the scenario's
            ``discount_rate`` at rule construction. Finite and > 0 when
            set. The cross-field bound y < r required by the σ_eff = 0
            certainty limit is enforced at evaluation time by
            ``core.investment.beta_positive_root`` (r may be unknown here).
        trigger_mode: ``"dixit_pindyck"`` (default) or ``"break_even"``
            (M ≡ 1 — the paper's own activation dating, anchor V1a).
        trigger_multiple_override: Pins M directly, bypassing the
            fundamental quadratic (sensitivity/diagnostic use). >= 1 when
            set (and finite); ``None`` (default) computes M from
            (σ_eff, r, y).
        build_lag_years: L [yr], integer >= 0. Decision at τ (first
            crossing on the triggering iterate), capacity at τ + L; in
            [τ, τ+L) the participant is structurally unchanged and no cost
            is booked (spec D2.3). Default 0.

    Raises:
        ValueError: On any bound violation, naming the offending field and
            the rule it broke (loud validation — spec D6 ranges).
    """

    participant_name: str
    technology_name: str
    break_even: float | Mapping[str, float]
    payout_yield: float
    sigma: float = 0.0
    credibility: float = 0.0
    discount_rate: float | None = None
    trigger_mode: str = "dixit_pindyck"
    trigger_multiple_override: float | None = None
    build_lag_years: int = 0

    def __post_init__(self) -> None:
        label = f"AdoptionSpec({self.participant_name!r}, {self.technology_name!r})"
        if not isinstance(self.participant_name, str) or not self.participant_name:
            raise ValueError(f"{label}: participant_name must be a non-empty string.")
        if not isinstance(self.technology_name, str) or not self.technology_name:
            raise ValueError(f"{label}: technology_name must be a non-empty string.")
        if isinstance(self.break_even, Mapping):
            if not self.break_even:
                raise ValueError(
                    f"{label}: break_even mapping must be non-empty "
                    "(year label -> threshold [currency/tCO2])."
                )
            for year, value in self.break_even.items():
                if not isinstance(year, str) or not year:
                    raise ValueError(
                        f"{label}: break_even keys must be non-empty year "
                        f"labels (str), got {year!r}."
                    )
                if not (math.isfinite(value) and value > 0.0):
                    raise ValueError(
                        f"{label}: break_even[{year!r}] must be finite and "
                        f"> 0 [currency/tCO2], got {value!r}."
                    )
        elif not (math.isfinite(self.break_even) and self.break_even > 0.0):
            raise ValueError(
                f"{label}: break_even must be finite and > 0 "
                f"[currency/tCO2], got {self.break_even!r}."
            )
        if not (math.isfinite(self.payout_yield) and self.payout_yield > 0.0):
            raise ValueError(
                f"{label}: payout_yield must be finite and > 0 [1/yr], got {self.payout_yield!r}."
            )
        if not (math.isfinite(self.sigma) and self.sigma >= 0.0):
            raise ValueError(
                f"{label}: sigma must be finite and >= 0 [1/sqrt(yr)], got {self.sigma!r}."
            )
        if not 0.0 <= self.credibility <= 1.0:
            raise ValueError(f"{label}: credibility must be in [0, 1], got {self.credibility!r}.")
        if self.discount_rate is not None and not (
            math.isfinite(self.discount_rate) and self.discount_rate > 0.0
        ):
            raise ValueError(
                f"{label}: discount_rate must be finite and > 0 [1/yr] when "
                f"set (None inherits the scenario rate), got {self.discount_rate!r}."
            )
        if self.trigger_mode not in ("dixit_pindyck", "break_even"):
            raise ValueError(
                f"{label}: trigger_mode must be one of "
                f"{{'dixit_pindyck', 'break_even'}}, got {self.trigger_mode!r}."
            )
        if self.trigger_multiple_override is not None and not (
            math.isfinite(self.trigger_multiple_override) and self.trigger_multiple_override >= 1.0
        ):
            raise ValueError(
                f"{label}: trigger_multiple_override must be finite and >= 1 "
                f"when set, got {self.trigger_multiple_override!r}."
            )
        if isinstance(self.build_lag_years, bool) or not isinstance(self.build_lag_years, int):
            raise ValueError(
                f"{label}: build_lag_years must be an int (years), got {self.build_lag_years!r}."
            )
        if self.build_lag_years < 0:
            raise ValueError(
                f"{label}: build_lag_years must be >= 0, got {self.build_lag_years!r}."
            )


@dataclass(frozen=True, kw_only=True)
class AdoptionEvent:
    """One irreversible adoption: a (participant, technology) pair's flip year.

    ``adoption_year`` is the DECISION year τ — the first crossing on the
    triggering iterate (spec D2.3). State flips at τ (that is what carries
    across policy-event splices); capacity becomes effective at τ + L via
    the spec's ``build_lag_years``, which lives on ``AdoptionSpec``, not
    here — the event records only what happened, never how to vintage it.

    Attributes:
        participant_name: ``MarketParticipant.name`` of the adopter.
        technology_name: ``TechnologyOption.name`` of the adopted option.
        adoption_year: Year LABEL (e.g. ``"2032"``) — a string matching the
            ``market.year`` string semantics, never a numeric year.
    """

    participant_name: str
    technology_name: str
    adoption_year: str

    def __post_init__(self) -> None:
        for field_name in ("participant_name", "technology_name", "adoption_year"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"AdoptionEvent: {field_name} must be a non-empty string, got {value!r}."
                )


AdoptionState: TypeAlias = tuple[AdoptionEvent, ...]
"""Canonical adoption state: ``AdoptionEvent``s sorted by (participant, technology).

Value equality of the sorted tuple IS the outer loop's convergence test
(plan "Kernel contracts"; spec D1.4 — combinatorial termination, no damping
parameter, no outer tolerance). Construct via ``make_adoption_state``, never
by hand — the constructor enforces the sort AND the at-most-one-adoption-
per-pair irreversibility invariant (spec D2.4: one irreversible tranche per
(participant, technology))."""


def make_adoption_state(events: Iterable[AdoptionEvent]) -> AdoptionState:
    """Normalize events into the canonical, deterministic ``AdoptionState``.

    Sorts by ``(participant_name, technology_name)`` — the deterministic
    representation whose value equality is the outer loop's convergence
    test — and rejects duplicates of the same (participant, technology)
    pair: irreversibility permits AT MOST ONE adoption per pair (spec
    D2.4; incremental adoption is multiple flagged options, never repeated
    adoption of one).

    Args:
        events: Adoption events in any order.

    Returns:
        The sorted, duplicate-free tuple.

    Raises:
        ValueError: If two events share a (participant, technology) pair
            (even with the same year — one pair adopts once).
    """
    ordered = tuple(sorted(events, key=lambda e: (e.participant_name, e.technology_name)))
    seen: set[tuple[str, str]] = set()
    for event in ordered:
        pair = (event.participant_name, event.technology_name)
        if pair in seen:
            raise ValueError(
                f"adoption state: duplicate adoption for participant "
                f"{event.participant_name!r}, technology "
                f"{event.technology_name!r} — irreversibility permits at most "
                "ONE adoption per (participant, technology) pair (spec D2.4)."
            )
        seen.add(pair)
    return ordered


def serialize_adoption_state(state: AdoptionState) -> str:
    """Serialize an adoption state to deterministic JSON.

    The exact string the "Investment Adoptions" summary column carries and
    the splice carrier stamps across policy-event segments (spec D3.4):
    a sorted JSON array of ``{"participant", "technology", "adoption_year"}``
    objects, sorted keys, compact separators — byte-identical for equal
    states regardless of input event order (the input is re-normalized
    through ``make_adoption_state`` first).

    Args:
        state: Adoption state (any event order; normalized internally).

    Returns:
        Deterministic JSON string; ``"[]"`` for the empty state.
    """
    payload = [
        {
            "participant": event.participant_name,
            "technology": event.technology_name,
            "adoption_year": event.adoption_year,
        }
        for event in make_adoption_state(state)
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_adoption_state(payload: str | Sequence[Mapping[str, Any]]) -> AdoptionState:
    """Parse a serialized adoption state back into the canonical tuple.

    Accepts the JSON string ``serialize_adoption_state`` produces OR an
    already-parsed list of dicts — both the splice carrier's landing field
    and the ``investment_initial_adoptions`` config field (user-settable to
    pre-commit adoptions) land here. Round-trips with
    ``serialize_adoption_state`` exactly.

    Args:
        payload: JSON string, or a sequence of mappings each carrying
            ``"participant"``, ``"technology"``, and ``"adoption_year"``.

    Returns:
        The canonical sorted ``AdoptionState`` tuple.

    Raises:
        ValueError: On invalid JSON, a non-array payload, an entry missing
            a required key, or a duplicate (participant, technology) pair
            (via ``make_adoption_state``).
    """
    decoded: Any
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"adoption state: payload is not valid JSON: {exc}") from exc
    else:
        decoded = list(payload)
    if not isinstance(decoded, list):
        raise ValueError(
            "adoption state: expected a JSON array (or list) of "
            "{participant, technology, adoption_year} mappings, got "
            f"{type(decoded).__name__}."
        )
    events: list[AdoptionEvent] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"adoption state: entry {index} must be a mapping, got {type(item).__name__}."
            )
        missing = [key for key in ("participant", "technology", "adoption_year") if key not in item]
        if missing:
            raise ValueError(f"adoption state: entry {index} is missing key(s) {missing}.")
        events.append(
            AdoptionEvent(
                participant_name=str(item["participant"]),
                technology_name=str(item["technology"]),
                adoption_year=str(item["adoption_year"]),
            )
        )
    return make_adoption_state(events)


@runtime_checkable
class PathFeedback(Protocol):
    r"""Whole-path feedback operator: adoption around a FULL path solve.

    The path-feedback contract of the endogenous-investment outer loop
    (``engine/feedback.py``; plan "Outer loop", spec D1). Unlike supply
    rules (per-year, inside the fixed point, F4), a ``PathFeedback`` reads
    a WHOLE-HORIZON price path and rewrites the DEMAND SYSTEM itself, so it
    composes strictly OUTSIDE the existing solves: outside the expectations
    inner loop (R29 verbatim) and outside ``solve_banking_path`` (spec D1.3
    — each outer iteration re-runs the full inner solve, window search
    included).

    Algorithm:
        The host's outer loop (plan; spec D1.4):

        ASCII:
            state_0 = carried adoptions (splice/config); k = 0
            loop:
              markets_k = rule.apply(base_markets, state_k)   # vintaging
              path_k    = path_solver(markets_k)              # FULL solve
              P_k       = delivered price path of path_k
              proposal  = fresh_rule().propose(P_k, state_k, markets_k)
              host enforces: proposal ⊇ state_k, no re-dating,
                             at most ONE new flip (tie-break: earliest
                             crossing year → largest relative exceedance
                             → declared config order)
              if proposal == state_k: converged (final = path_k)
              state_{k+1} = proposal

        Convergence is value equality of the sorted ``AdoptionState`` tuple
        — combinatorial (≤ N_flagged + 1 iterations), no damping, no outer
        tolerance.

    Lifecycle doctrine (binding):

    * Instances are FRESH PER OUTER ITERATION — hosts wire a
      ``PathFeedbackFactory`` and construct a new instance each iteration;
      the host-owned ``AdoptionState`` is the ONLY state that crosses an
      iteration boundary. No hidden mutable state survives an iteration.
    * Monotone one-flip semantics are HOST-enforced (spec D1.4), never
      trusted to implementations: the host verifies the proposal is a
      superset of the current state, never re-dates an existing event, and
      adds at most one new event per iteration.
    * ``propose`` is evaluated on the DELIVERED price path ONLY (spec D1.2,
      not configurable): the post-overlay, floor-clipped path (clip-last,
      F3) of the previous outer iterate — never pre-clip prices (the
      auction reserve delivering the trigger is K-MSR Results 2–3), never
      the expectations module's one-year-ahead signals (double-counts
      waiting value the Dixit–Pindyck multiple already capitalizes).

    References:
        docs/invest-feedback-spec.md D1 (equilibrium concept), D2 (rule),
        D3 (vintaging). docs/invest-feedback-plan.md — "Kernel contracts",
        "Outer loop (engine/feedback.py)".
    """

    def propose(
        self,
        price_path: Mapping[str, float],
        state: AdoptionState,
        markets: Sequence[CarbonMarket],
    ) -> tuple[AdoptionState, dict[str, float]]:
        """Propose the next adoption state from a delivered price path.

        Args:
            price_path: Year label → DELIVERED price [currency/tCO2] of the
                previous outer iterate (post-overlay, floor-clipped — spec
                D1.2).
            state: The host-owned adoption state the iterate was solved
                under (canonical sorted tuple).
            markets: The (vintaged) markets the iterate solved — read-only
                context (year labels, declared config order for the
                tie-break). Never mutated.

        Returns:
            ``(proposal, metrics)`` — the proposed adoption state (a
            superset of ``state`` with at most one new event; the host
            re-verifies this, spec D1.4) and scalar diagnostics (e.g.
            crossing margins) merged into the feedback diagnostics.
        """
        ...

    def apply(
        self,
        ordered_markets: list[CarbonMarket],
        state: AdoptionState,
    ) -> list[CarbonMarket]:
        """Vintage an adoption state into the horizon's markets.

        Per-year availability gating (spec D2.5/D3.1): flagged options are
        REMOVED from the reversible choice set before τ + L and enter at
        their configured ``max_activity_share`` thereafter; utilization
        stays reversible (capex irreversible, dispatch reversible). MUST
        NOT mutate MAC blocks, ``initial_emissions``, or shared participant
        objects (spec D3); with no flagged specs and an empty state,
        implementations must return the SAME list object (identity — the
        off-by-default proof chain depends on it).

        Args:
            ordered_markets: The base horizon markets in year order.
            state: Adoptions to vintage in (canonical sorted tuple).

        Returns:
            A new list of markets with the gating applied (or
            ``ordered_markets`` itself in the neutral case).
        """
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Factories — what the engine actually wires (see module docstring)
# ──────────────────────────────────────────────────────────────────────────────

CapRuleFactory: TypeAlias = Callable[[], CapRule]
"""Zero-argument constructor of a fresh ``CapRule`` per schedule evaluation."""

SupplyRuleFactory: TypeAlias = Callable[[], SupplyRule]
"""Zero-argument constructor of a fresh ``SupplyRule`` per schedule evaluation."""

PathFeedbackFactory: TypeAlias = Callable[[], PathFeedback]
"""Zero-argument constructor of a fresh ``PathFeedback`` per OUTER iteration.

The engine wires the factory, never a shared instance — the host-owned
``AdoptionState`` is the only cross-iteration state (spec D1.4)."""
