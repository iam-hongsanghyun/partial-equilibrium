"""Default rule wiring (T3): today's exact per-approach defaults, as reviewed literals.

The TRANSITIONAL default factory-builders moved here from the solver hosts in
the engine work order (v1 O8 / v2 O12, ``docs/feature-modules-plan.md``):
``default_supply_rule_factories`` and ``default_friction`` verbatim from
``solvers/banking.py``; ``default_cap_rules`` expresses the per-approach
cap-rule composition the hosts construct today. The engine wires FACTORIES,
never shared instances (``ets.core.protocols`` lifecycle doctrine): every
call of a ``default_*`` builder returns fresh rule instances or zero-argument
constructors, so no rule state can leak between scenarios, solver
invocations, or fixed-point iterations.

F2 FREEZE (binding): the per-approach variants below reproduce the
documented MSR/CCR inconsistencies of the current solvers EXACTLY
(``docs/blocks-composition-rules.md`` F2, R8, R9, R16; economist item 5d).
Harmonising any of them is a math change requiring economist sign-off and
new golden baselines — out of scope for every migration order.

Also home (transitionally) to the feature-class re-exports the LEGACY
banking host consumes via lazy import (``HoardingInflow``,
``DeliveredFloor``, ``FloorCancellationRule``) — the engine is the sole
importer of the feature tier, so ``solvers/banking.py`` reaches feature
classes only through this module until its own feature move (v1 O9 /
v2 O13).

LAZY, PER-MODEL FEATURE ACTIVATION (binding): every ``features.*`` runtime
import below is FUNCTION-LOCAL — inside the branch of ``default_cap_rules``
/ ``default_supply_rule_factories`` gated by the enable flag that needs it,
or inside the body of the per-approach ``solve_*`` entry point that a
scenario's ``model_approach`` actually selects. Importing this module (or
``ets.engine``, or ``ets`` itself) must load none of the feature runtimes;
only SOLVING a scenario with a given approach/flags loads that approach's
(and only that approach's) feature solver and rule modules. This is
activation scoping, not directory structure — the tier contract
(``tests/test_module_isolation.py``) is unaffected: a lazy
``features.*`` import inside a function body is still an engine->feature
edge the AST walker counts, so nothing here is exempt from tier law, only
from EAGER (module-import-time) execution. See
``tests/engine/test_lazy_activation.py`` for the ``sys.modules``
assertions this buys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ..core.market.model import CarbonMarket
    from ..core.protocols import CapRule, Friction, SupplyRuleFactory
    from ..features.banking.solver import FloorRule
    from ..features.hoarding.plugin import HoardingInflow
    from ..features.price_controls.plugin import DeliveredFloor
    from ..features.price_controls.rules import FloorCancellationRule

__all__ = [
    "DeliveredFloor",
    "FloorCancellationRule",
    "HoardingInflow",
    "default_cap_rules",
    "default_floor_rule_factory",
    "default_friction",
    "default_supply_rule_factories",
    "solve_banking_path",
    "solve_hotelling_path",
    "solve_nash_path",
    "solve_scenario_path",
    "solve_transmission_path",
]


def __getattr__(name: str) -> object:
    """PEP 562 lazy resolution of the re-exported feature classes.

    ``DeliveredFloor``, ``FloorCancellationRule``, and ``HoardingInflow``
    stay in ``__all__`` for backward-compatible attribute access
    (``ets.engine.wiring.DeliveredFloor`` et al.), but resolving them
    eagerly at module-import time would force-load their owning feature's
    runtime regardless of which model approach a caller actually solves.
    Nothing in this codebase imports them this way today (they are used
    internally, below) — this hook exists so the documented surface stays
    truthful without paying the eager-import cost.

    Args:
        name: Attribute requested on this module.

    Returns:
        The resolved class.

    Raises:
        AttributeError: ``name`` is not one of the three lazy re-exports.
    """
    if name == "DeliveredFloor":
        from ..features.price_controls.plugin import DeliveredFloor

        return DeliveredFloor
    if name == "FloorCancellationRule":
        from ..features.price_controls.rules import FloorCancellationRule

        return FloorCancellationRule
    if name == "HoardingInflow":
        from ..features.hoarding.plugin import HoardingInflow

        return HoardingInflow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def default_cap_rules(m0: CarbonMarket, approach: str) -> list[CapRule]:
    """Today's exact per-approach cap-rule wiring from ``m0``'s enable flags.

    Each call constructs FRESH rule instances — the call itself is the
    factory invocation (factories, never shared instances;
    ``ets.core.protocols``). Composition order within an approach is the
    reviewed wiring literal: CCR before MSR (F1).

    Args:
        m0: First market of the chronologically sorted scenario path.
        approach: The scenario's ``model_approach``.

    Returns:
        Cap rules in application order (possibly empty).
    """
    rules: list[CapRule] = []

    if approach == "competitive":
        # Competitive path: CCR before MSR (F1 wiring-literal order), each
        # rule attached iff its m0 enable flag; both rules then re-read
        # their per-year enable flag AND start-year gate inside pre_clear
        # (per-year-gated MSR + CCR). Identical composition to the retired
        # legacy-kwarg translation — equivalence pinned by
        # tests/test_cap_rule_injection.py.
        if bool(getattr(m0, "ccr_enabled", False)):
            from ..features.ccr import CCRCapRule

            rules.append(CCRCapRule())
        if bool(getattr(m0, "msr_enabled", False)):
            from ..features.msr import MSRCapRule

            rules.append(MSRCapRule())
        return rules

    if approach == "hotelling":
        # F2 FREEZE (docs/blocks-composition-rules.md F2, R8, R9 — DO NOT
        # HARMONISE without economist sign-off and new golden baselines):
        # the PRIMARY Hotelling path applies neither rule (its result rows
        # hardcode msr_* = 0.0; R8 — MSR + Hotelling cannot coexist), and
        # the CCR is competitive-only (R9). This branch reproduces the
        # COMPETITIVE-FALLBACK wiring only (features/hotelling/solver.py
        # ``_competitive_fallback``): a per-year-gated MSR iff
        # m0.msr_enabled, and NEVER a CCR — even when ccr_enabled is set.
        if bool(getattr(m0, "msr_enabled", False)):
            from ..features.msr import MSRCapRule

            rules.append(MSRCapRule())
        return rules

    if approach == "nash_cournot":
        # F2 FREEZE (docs/blocks-composition-rules.md F2, R9, R16): the
        # Nash path's MSR is NOT a CapRule — features/nash_cournot/solver.py
        # applies a raw MSRState inline, UNGATED (msr_start_year is
        # ignored, R16) and with its own literal getattr fallbacks; it
        # never constructs a CCR (R9). Faking it here as a
        # (start-year-gated) MSRCapRule would silently change solved
        # numbers, so the Nash binding below (``solve_nash_path``) injects
        # the duck-typed MSR STATE instead — bit-for-bit the retired inline
        # construction.
        return rules

    # banking composes SupplyRules inside its fixed point (see
    # default_supply_rule_factories); "all" fans out to the three
    # sub-approaches, each of which wires itself.
    return rules


def default_supply_rule_factories(m0: CarbonMarket) -> list[SupplyRuleFactory]:
    """Today's exact supply-rule wiring, derived from ``m0``'s ``msr_*`` flags.

    Moved VERBATIM from ``solvers/banking.py:_default_supply_rule_factories``
    (v1 O8 / v2 O12); the banking host keeps a thin compat delegate until its
    own feature move (v1 O9 / v2 O13).

    Mode dispatch is if/elif — a scenario gets EITHER the decree rule
    (``msr_mode`` in {``price_band``, ``surplus_rule``, ``hybrid``}) OR the
    bank-threshold rule, never both; ``msr_initial_reserve_mt`` funds ONLY
    the decree rule (R7, ``docs/blocks-composition-rules.md``).

    Args:
        m0: First market of the chronologically sorted scenario path.

    Returns:
        Zero or one ``SupplyRuleFactory`` in a list (empty when the MSR is
        disabled).
    """
    if not bool(getattr(m0, "msr_enabled", False)):
        return []
    msr_mode = str(getattr(m0, "msr_mode", "bank_threshold") or "bank_threshold")
    # The banking path reads msr_start_year from the FIRST market only
    # (scenario-level, m0-only start-year gate), while the competitive
    # path's MSRCapRule re-reads it per year. Documented F2-family
    # inconsistency (economist item 5d, docs/feature-modules-plan.md) —
    # DO NOT HARMONISE without economist sign-off and new golden baselines.
    msr_start = float(getattr(m0, "msr_start_year", 0.0) or 0.0)
    if msr_mode != "bank_threshold":
        from ..features.msr import DecreeSupplyRule

        initial_reserve = float(getattr(m0, "msr_initial_reserve_mt", 0.0) or 0.0)
        return [
            lambda: DecreeSupplyRule(
                mode=msr_mode,
                initial_reserve_mt=initial_reserve,
                start_year=msr_start,
            )
        ]
    from ..features.msr import ThresholdMSRSupplyRule

    return [lambda: ThresholdMSRSupplyRule(start_year=msr_start)]


def default_friction(ordered_markets: list[CarbonMarket]) -> Friction | None:
    """Today's exact hoarding wiring: the feature's reader when configured.

    Moved VERBATIM from ``solvers/banking.py:_default_friction`` (v1 O8 /
    v2 O12); the banking host keeps a thin compat delegate until its own
    feature move (v1 O9 / v2 O13). The gate expresses the wiring intent (the
    hoarding feature attaches only when a scenario configures it); ``None``
    is behaviour-identical to an attached reader on unconfigured markets,
    since ``HoardingInflow.inflow`` is 0.0 without ``hoarding_inflow``
    fields.

    Args:
        ordered_markets: Markets sorted chronologically.

    Returns:
        The hoarding ``Friction`` when any year has ``hoarding_inflow > 0``,
        else ``None`` (neutral).
    """
    if any(
        float(getattr(m, "hoarding_inflow", 0.0) or 0.0) > 0.0 for m in ordered_markets
    ):
        from ..features.hoarding.plugin import HoardingInflow

        return HoardingInflow()
    return None


def default_floor_rule_factory() -> Callable[[], FloorCancellationRule]:
    """Today's exact floor-cancellation default: the rule class as its own factory.

    ``solvers/banking.py`` defaulted ``floor_rule_factory`` to the
    ``FloorCancellationRule`` class itself (attach-always is exact — the
    rule returns the supply unchanged when no floor binds); this builder
    hands the same class to the host's dedicated slot.

    Returns:
        A zero-argument constructor of a fresh floor-cancellation rule per
        schedule evaluation.
    """
    from ..features.price_controls.rules import FloorCancellationRule

    return FloorCancellationRule


# ──────────────────────────────────────────────────────────────────────────────
# Engine-bound solve entry points — the feature solvers with today's default
# wiring injected (plan §4 O8 "engine-bound solve entry points"; features
# never resolve their own defaults, the engine does).
# ──────────────────────────────────────────────────────────────────────────────


def solve_banking_path(
    ordered_markets: list[CarbonMarket],
    discount_rate: float = 0.055,
    risk_premium: float = 0.0,
    initial_bank: float | None = None,
    strict_no_arbitrage: bool | None = None,
    supply_rule_factories: Sequence[SupplyRuleFactory] | None = None,
    floor_rule_factory: Callable[[], FloorRule] | None = None,
    friction: Friction | None = None,
) -> list[dict]:
    """Engine-bound banking solve: resolve default wiring, then delegate.

    Same public surface and behaviour as the pre-move
    ``solvers/banking.py:solve_banking_path`` (v1 O9 / v2 O13): ``None``
    injection parameters get today's exact defaults —
    ``default_supply_rule_factories`` (decree XOR bank-threshold from the
    first market's flags), ``default_floor_rule_factory``
    (``FloorCancellationRule``, attach-always exact), and the hoarding
    feature's reader as friction (attach-always: the pre-move window host
    attached the reader itself whenever it received ``None``, so wiring it
    unconditionally here is number-identical; ``default_friction`` remains
    the configured-only gate for callers who want the wiring intent
    explicit). The delivered-price overlay is always the reserve-price
    floor clip (``DeliveredFloor``, clip-LAST, F3).

    Args:
        ordered_markets: Markets sorted chronologically.
        discount_rate: Risk-free rate r [1/yr].
        risk_premium: Policy risk premium ρ added to r [1/yr].
        initial_bank: See the feature solver.
        strict_no_arbitrage: See the feature solver.
        supply_rule_factories: ``None`` → today's flag-derived default.
        floor_rule_factory: ``None`` → today's attach-always default.
        friction: ``None`` → the hoarding feature's reader (attach-always).

    Returns:
        Path details from ``features.banking.solver.solve_banking_path``.
    """
    # Lazy: only a scenario whose model_approach resolves to banking pays
    # for the banking runtime (scipy-backed window search) and its
    # attach-always siblings (hoarding, price-controls) loading at all.
    from ..features.banking.solver import solve_banking_path as _banking_solve_path
    from ..features.hoarding.plugin import HoardingInflow
    from ..features.price_controls.plugin import DeliveredFloor

    if not ordered_markets:
        # Replicated from the feature solver so default resolution below can
        # read the first market (identical message and exception type).
        raise ValueError("solve_banking_path requires at least one market.")
    if supply_rule_factories is None:
        supply_rule_factories = default_supply_rule_factories(ordered_markets[0])
    if floor_rule_factory is None:
        floor_rule_factory = default_floor_rule_factory()  # attach-always is exact
    if friction is None:
        friction = HoardingInflow()  # attach-always neutral: 0.0 when unconfigured
    return _banking_solve_path(
        ordered_markets,
        discount_rate=discount_rate,
        risk_premium=risk_premium,
        initial_bank=initial_bank,
        strict_no_arbitrage=strict_no_arbitrage,
        supply_rule_factories=supply_rule_factories,
        floor_rule_factory=floor_rule_factory,
        friction=friction,
        price_overlay=DeliveredFloor(),
    )


def solve_scenario_path(
    ordered_markets: list[CarbonMarket],
    max_iterations: int | None = None,
    tolerance: float | None = None,
) -> list[dict]:
    """Engine-bound competitive solve: wire today's default cap rules, delegate.

    Same public surface and behaviour as the pre-move
    ``solvers/simulation.py:solve_scenario_path`` (v1 O10 / v2 O14): the
    cap rules come from ``default_cap_rules(m0, "competitive")`` — CCR
    before MSR (F1), each rule iff its first-market enable flag, fresh
    instances per call (factories, never shared instances). The
    empty-markets guard keeps the pre-move surface exact: an empty list
    with explicit iteration settings returns ``[]`` from the feature
    before the rules would be read.

    Args:
        ordered_markets: Markets sorted chronologically.
        max_iterations: See the feature solver.
        tolerance: See the feature solver.

    Returns:
        Path details from ``features.competitive.solver.solve_scenario_path``.
    """
    from ..features.competitive.solver import solve_scenario_path as _competitive_solve_path

    cap_rules = (
        default_cap_rules(ordered_markets[0], "competitive") if ordered_markets else []
    )
    return _competitive_solve_path(
        ordered_markets,
        max_iterations=max_iterations,
        tolerance=tolerance,
        cap_rules=cap_rules,
    )


def solve_hotelling_path(ordered_markets, **hotelling_kwargs) -> list[dict]:
    """Engine-bound Hotelling solve: wire the fallback cap rules, delegate.

    Same public surface and behaviour as the pre-move
    ``solvers/hotelling.py:solve_hotelling_path`` (v1 O11 / v2 O15): the
    competitive-fallback cap rules come from ``default_cap_rules(m0,
    "hotelling")`` — the F2-frozen wiring (per-year-gated MSR iff
    ``m0.msr_enabled``, never a CCR; R8/R9); the primary Hotelling path
    applies no rules. Keyword arguments (``discount_rate``,
    ``risk_premium``, bisection settings) forward to the feature solver,
    whose defaults apply.

    Args:
        ordered_markets: Markets sorted chronologically.
        **hotelling_kwargs: See
            ``features.hotelling.solver.solve_hotelling_path``.

    Returns:
        Path details from the feature solver.
    """
    from ..features.hotelling.solver import solve_hotelling_path as _hotelling_solve_path

    cap_rules = (
        default_cap_rules(ordered_markets[0], "hotelling") if ordered_markets else []
    )
    return _hotelling_solve_path(ordered_markets, cap_rules=cap_rules, **hotelling_kwargs)


def solve_nash_path(ordered_markets, **nash_kwargs) -> list[dict]:
    """Engine-bound Nash-Cournot solve: wire the duck-typed MSR state, delegate.

    Same public surface and behaviour as the pre-move
    ``solvers/nash.py:solve_nash_path`` (v1 O11 / v2 O15): the injected
    state is ``MSRState()`` iff the first market enables the MSR — the
    retired inline construction, bit-for-bit. The APPLICATION stays inline
    in the feature solver and is F2-frozen: UNGATED (``msr_start_year``
    ignored, R16), literal getattr fallbacks, no CCR (R9) — see the
    ``default_cap_rules`` nash branch for why this is NOT a ``CapRule``.
    Keyword arguments (``strategic_participants``, ``price_step``, iteration
    settings) forward to the feature solver, whose defaults apply.

    Args:
        ordered_markets: Markets sorted chronologically.
        **nash_kwargs: See
            ``features.nash_cournot.solver.solve_nash_path``.

    Returns:
        Path details from the feature solver.
    """
    from ..features.nash_cournot.solver import solve_nash_path as _nash_solve_path

    msr_state = None
    if ordered_markets and getattr(ordered_markets[0], "msr_enabled", False):
        from ..features.msr import MSRState

        msr_state = MSRState()
    return _nash_solve_path(ordered_markets, msr_state=msr_state, **nash_kwargs)


def solve_transmission_path(ordered_markets, lam: float, **kwargs) -> list[dict]:
    """Engine-bound λ-blend solve: bind the component-path solvers, delegate.

    Same public surface and behaviour as the pre-move
    ``solvers/transmission.py:solve_transmission_path`` (v1 O12 / v2 O16):
    the static component is THIS module's RULE-CARRYING competitive binding
    (``solve_scenario_path`` — MSR/CCR per the first market's flags apply
    inside the competitive component only; economist item 5a) and the
    inter-temporal component is the Hotelling binding
    (``solve_hotelling_path``) — exactly the callables the pre-move lazy
    imports resolved to. The strip-floors → blend → clip-last order (F3)
    lives entirely inside the feature solver.

    Args:
        ordered_markets: Markets sorted chronologically.
        lam: Forward-transmission coefficient λ, dimensionless in [0, 1].
        **kwargs: ``discount_rate``, ``risk_premium``, and Hotelling
            bisection settings — see
            ``features.transmission.solver.solve_transmission_path``.

    Returns:
        Path details from the feature solver.
    """
    from ..features.transmission.solver import (
        solve_transmission_path as _transmission_solve_path,
    )

    return _transmission_solve_path(
        ordered_markets,
        lam,
        static_solver=solve_scenario_path,
        hotelling_solver=solve_hotelling_path,
        **kwargs,
    )
