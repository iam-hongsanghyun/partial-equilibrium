"""Solve dispatch (T3): scenario grouping, approach routing, output assembly.

``run_simulation``, ``_rename_markets``, ``run_simulation_from_config``, and
``run_simulation_from_file`` moved VERBATIM from ``solvers/simulation.py`` in
the engine work order (v1 O8 / v2 O12, ``docs/feature-modules-plan.md``);
``ets/solvers/simulation.py`` re-exports them so every old import path keeps
working. The competitive path solver (``solve_scenario_path``) stays in
``solvers/simulation.py`` until the competitive feature move (v1 O10 /
v2 O14) and is imported lazily inside ``run_simulation`` — alongside the
other approach solvers — so no module-level cycle arises with the
solvers-tier re-exports of this module's names.

PURE REFACTOR (EI-2, ``docs/invest-feedback-plan.md`` D2): the per-approach
solve invocation ``run_simulation`` used to build inline is now
``_path_solver_for`` — a closure factory that captures the exact same
kwargs derivation from a scenario's first market (``m0``) and returns a
``ordered_markets -> path`` callable. Zero behaviour change: calling
``_path_solver_for(approach, m0, transmission_lambda=...)(ordered_markets)``
runs the identical branch body, with identical lazy imports, that used to
sit directly in ``run_simulation``'s if/elif ladder. This exists so a later
order (EI-5, ``engine/feedback.py``) can re-invoke the SAME approach's full
path solve on successive vintaged market lists without re-deriving or
drifting from the wiring literals — the closure is the one place they live.
The ``"all"`` comparison branch is NOT routed through the factory (it fans
a scenario out over three differently-renamed market lists, not one
``ordered_markets`` thread) and stays inline, unchanged.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from ..config_io import build_markets_from_config, iter_market_bodies, load_config

# Aliased to the pre-move underscore names so the bodies below stay verbatim.
from ..core.ledger import (
    collect_path_results as _collect_path_results,
    market_year_sort_key as _market_year_sort_key,
)

# Adoption-state (de)serialization for the D2-5 cyclic-SCC investment FLOOR.
# core.protocols is T0 (never a feature runtime), so this eager import loads no
# feature module — activation scoping stays intact (tests/engine/test_lazy_activation.py).
from ..core.protocols import make_adoption_state, parse_adoption_state

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ..core.market import CarbonMarket
    from ..core.protocols import AdoptionState, LinkSpec
    from .scc import SCC

logger = logging.getLogger(__name__)


def _rename_markets(markets: list[CarbonMarket], suffix: str) -> list[CarbonMarket]:
    """Return shallow copies of markets with scenario_name suffixed."""
    renamed = []
    for m in markets:
        copy = deepcopy(m)
        copy.scenario_name = f"{m.scenario_name} [{suffix}]"
        renamed.append(copy)
    return renamed


def _hot_kwargs(m0: CarbonMarket) -> dict[str, float | int]:
    """Hotelling/transmission solver kwargs derived from a scenario's first market.

    Args:
        m0: First market of the scenario's chronologically sorted path.

    Returns:
        Keyword arguments for ``solve_hotelling_path``/``solve_transmission_path``.
    """
    return dict(
        discount_rate=float(getattr(m0, "discount_rate", 0.04) or 0.04),
        risk_premium=float(getattr(m0, "risk_premium", 0.0) or 0.0),
        max_bisection_iters=int(getattr(m0, "solver_hotelling_max_bisection_iters", 80) or 80),
        max_lambda_expansions=int(getattr(m0, "solver_hotelling_max_lambda_expansions", 20) or 20),
        convergence_tol=float(getattr(m0, "solver_hotelling_convergence_tol", 1e-4) or 1e-4),
    )


def _nash_kwargs(m0: CarbonMarket) -> dict[str, object]:
    """Nash-Cournot solver kwargs derived from a scenario's first market.

    Args:
        m0: First market of the scenario's chronologically sorted path.

    Returns:
        Keyword arguments for ``solve_nash_path``.
    """
    return dict(
        strategic_participants=list(getattr(m0, "nash_strategic_participants", None) or []) or None,
        price_step=float(getattr(m0, "solver_nash_price_step", 0.5) or 0.5),
        max_iters=int(getattr(m0, "solver_nash_max_iters", 120) or 120),
        convergence_tol=float(getattr(m0, "solver_nash_convergence_tol", 1e-3) or 1e-3),
    )


def _path_solver_for(
    approach: str,
    m0: CarbonMarket,
    *,
    transmission_lambda: float | None,
) -> Callable[[list[CarbonMarket]], list[dict]]:
    """Build the closure that runs one scenario's full per-approach path solve.

    PURE extraction of ``run_simulation``'s former inline if/elif ladder
    (everything except the ``"all"`` comparison fan-out, which the caller
    keeps handling separately). Every keyword argument the returned closure
    passes downstream is derived from ``m0`` exactly once, at closure-build
    time — identical to the pre-extraction inline reads — so
    ``_path_solver_for(approach, m0, transmission_lambda=lam)(ordered_markets)``
    is bit-identical to the old inline call for the same
    ``(approach, m0, ordered_markets)`` triple. This is what lets a later
    outer loop (``engine/feedback.py``, EI-5, ``docs/invest-feedback-plan.md``)
    re-invoke the SAME approach's full solve on successive vintaged market
    lists without re-deriving or drifting from the wiring literals below —
    the closure is the one and only place they live.

    Every ``features.*``/``.wiring`` import stays lazy INSIDE the returned
    closure's body (never at factory-build time), so building the closure
    never loads a feature runtime module — only calling it does. This
    preserves the activation-scoping contract
    (``tests/engine/test_lazy_activation.py``).

    Args:
        approach: The scenario's resolved ``model_approach``. ``"all"`` is
            handled entirely by the caller and is never passed here — if it
            were, this falls through to the competitive default, which is
            NOT what ``"all"`` means, so callers must keep excluding it.
        m0: First market of the scenario's chronologically sorted path.
        transmission_lambda: The scenario's forward-transmission λ after the
            caller's competitive-only gate and warning (``None`` when unset
            or ignored for a non-competitive approach). Passed in rather
            than re-derived so the caller's warning log fires exactly once
            per scenario, not once per solve invocation.

    Returns:
        A callable ``ordered_markets -> path`` (list of per-year result
        dicts, one row per market year) that runs the wired solver for
        ``approach``.
    """
    if transmission_lambda is not None:
        lam = float(transmission_lambda)
        hot_kwargs = _hot_kwargs(m0)

        def _solve_transmission(ordered_markets: list[CarbonMarket]) -> list[dict]:
            from .wiring import solve_transmission_path

            return solve_transmission_path(ordered_markets, lam=lam, **hot_kwargs)

        return _solve_transmission

    if approach == "banking":
        discount_rate = float(getattr(m0, "discount_rate", 0.055) or 0.055)
        risk_premium = float(getattr(m0, "risk_premium", 0.0) or 0.0)

        def _solve_banking(ordered_markets: list[CarbonMarket]) -> list[dict]:
            from .wiring import solve_banking_path

            return solve_banking_path(
                ordered_markets,
                discount_rate=discount_rate,
                risk_premium=risk_premium,
            )

        return _solve_banking

    if approach == "hotelling":
        hot_kwargs = _hot_kwargs(m0)

        def _solve_hotelling(ordered_markets: list[CarbonMarket]) -> list[dict]:
            from .wiring import solve_hotelling_path

            return solve_hotelling_path(ordered_markets, **hot_kwargs)

        return _solve_hotelling

    if approach == "nash_cournot":
        nash_kwargs = _nash_kwargs(m0)

        def _solve_nash(ordered_markets: list[CarbonMarket]) -> list[dict]:
            from .wiring import solve_nash_path

            return solve_nash_path(ordered_markets, **nash_kwargs)

        return _solve_nash

    def _solve_competitive(ordered_markets: list[CarbonMarket]) -> list[dict]:
        # Default: competitive (MSR handled inside solve_scenario_path)
        from .wiring import solve_scenario_path

        return solve_scenario_path(ordered_markets)

    return _solve_competitive


def _investment_configured(m0: CarbonMarket) -> bool:
    """Gate of the endogenous-investment feedback branch (spec D6 loud guard).

    The feature is ON iff BOTH halves of its configuration are present on
    the scenario's first market: the master flag
    (``investment_feedback_enabled``, scenario-level, default absent/False)
    AND at least one participant carrying ``adoption_specs``. A mismatch is
    a config error and raises — flagged options with the gate off must
    never be a silent ignore (spec D3.2/D6; the config door's builder-level
    guard, EI-6, mirrors this belt-and-braces).

    Args:
        m0: First market of the scenario's chronologically sorted path.

    Returns:
        True iff the flag is set AND specs are attached; False when neither
        is present (the byte-identical legacy path).

    Raises:
        ValueError: Flag true with zero specs, or specs attached with the
            flag false/absent.
    """
    enabled = bool(getattr(m0, "investment_feedback_enabled", False))
    has_specs = any(getattr(participant, "adoption_specs", ()) for participant in m0.participants)
    if enabled and not has_specs:
        raise ValueError(
            f"Scenario '{m0.scenario_name}': investment_feedback_enabled is true "
            "but no participant carries an adoption spec — flag one or more "
            "technology options with an investment_trigger block, or disable "
            "the feature (spec D6)."
        )
    if has_specs and not enabled:
        raise ValueError(
            f"Scenario '{m0.scenario_name}': adoption spec(s) are attached but "
            "investment_feedback_enabled is not set — enable the master gate "
            "or remove the investment_trigger flags; flagged options with the "
            "gate off are a loud error, never a silent ignore (spec D3.2/D6)."
        )
    return enabled and has_specs


def run_simulation(markets: list[CarbonMarket]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not markets:
        raise ValueError("At least one market scenario must be provided.")

    # Lazy imports to avoid circular dependency
    from .wiring import solve_hotelling_path, solve_nash_path, solve_scenario_path

    grouped_markets: dict[str, list[CarbonMarket]] = defaultdict(list)
    for market in markets:
        grouped_markets[market.scenario_name].append(market)

    scenario_summaries: list[dict[str, float | str]] = []
    participant_frames: list[pd.DataFrame] = []

    for scenario_name, scenario_markets in grouped_markets.items():
        ordered_markets = sorted(scenario_markets, key=_market_year_sort_key)
        approach = getattr(ordered_markets[0], "model_approach", "competitive") or "competitive"

        m0 = ordered_markets[0]

        transmission_lambda = getattr(m0, "forward_transmission_lambda", None)
        if transmission_lambda is not None and approach != "competitive":
            logger.warning(
                f"Scenario '{scenario_name}': forward_transmission_lambda is only "
                f"applied under model_approach='competitive' (got '{approach}'); "
                "ignoring the λ blend."
            )
            transmission_lambda = None

        # Endogenous-investment gate (EI-5, docs/invest-feedback-plan.md D2):
        # False on every scenario without BOTH the master flag and attached
        # adoption specs — the guard raises loudly on a half-configured
        # scenario and leaves fully unconfigured ones on the byte-identical
        # legacy path below.
        investment_on = _investment_configured(m0)

        if approach == "all":
            if investment_on:
                raise ValueError(
                    f"Scenario '{scenario_name}': endogenous investment feedback "
                    "is not supported under model_approach='all' — the "
                    "comparison fan-out solves three renamed market lists, not "
                    "one path the adoption loop could wrap. Pick a single "
                    "approach (competitive or banking, spec v1 coverage)."
                )
            # Not routed through _path_solver_for: fans one scenario out over
            # three differently-renamed market lists, not one ordered_markets
            # thread (transmission_lambda is always None here — "all" != the
            # competitive-only gate above always clears it — matching the
            # pre-extraction elif ladder's effective behaviour exactly).
            comp_markets = _rename_markets(ordered_markets, "Competitive")
            hot_markets = _rename_markets(ordered_markets, "Hotelling")
            nash_markets = _rename_markets(ordered_markets, "Nash-Cournot")

            comp_path = solve_scenario_path(comp_markets)
            hot_path = solve_hotelling_path(hot_markets, **_hot_kwargs(m0))
            nash_path = solve_nash_path(nash_markets, **_nash_kwargs(m0))

            for path, mkt_list in [
                (comp_path, comp_markets),
                (hot_path, hot_markets),
                (nash_path, nash_markets),
            ]:
                _collect_path_results(mkt_list, path, scenario_summaries, participant_frames)

        else:
            solver = _path_solver_for(approach, m0, transmission_lambda=transmission_lambda)
            if investment_on:
                # Lazy imports (activation scoping): only an investment-
                # configured scenario loads the feedback host and the
                # endogenous_investment runtime (tests/engine/
                # test_lazy_activation.py).
                from ..features.endogenous_investment.rule import InvestmentRule
                from .feedback import solve_with_investment_feedback

                # Declared config order for the spec D1.4 tie-break:
                # participant order, then per-participant spec (option)
                # order — the InvestmentRule default over this tuple.
                specs = tuple(
                    spec
                    for participant in m0.participants
                    for spec in getattr(participant, "adoption_specs", ())
                )
                r = float(getattr(m0, "discount_rate", 0.04) or 0.04)
                max_iters_raw = getattr(m0, "investment_max_iterations", None)

                def _fresh_rule(specs: tuple = specs, r: float = r) -> InvestmentRule:
                    # Early-bound defaults: a plain closure factory (one
                    # fresh rule per use — the PathFeedback lifecycle
                    # doctrine), immune to loop-variable rebinding.
                    return InvestmentRule(specs, r)

                path = solve_with_investment_feedback(
                    ordered_markets,
                    solver,
                    _fresh_rule,
                    specs,
                    scenario_discount_rate=r,
                    max_iterations=None if max_iters_raw is None else int(max_iters_raw),
                )
            else:
                path = solver(ordered_markets)
            _collect_path_results(ordered_markets, path, scenario_summaries, participant_frames)

    summary_df = pd.DataFrame.from_records(scenario_summaries)
    participant_df = pd.concat(participant_frames, ignore_index=True)
    return summary_df, participant_df


def _run_flat_config(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Solve today's flat (single-market) scenarios — the byte-identical legacy path.

    VERBATIM the pre-D1-3 body of ``run_simulation_from_config``: normalize,
    split plain vs policy-event scenarios, dispatch each. The multi-market
    partition in ``run_simulation_from_config`` only ever hands this function
    scenarios WITHOUT a ``markets`` key, so a config that carries no linked
    scenario reaches this path unchanged (39 goldens bit-identical — the
    legacy branch is untouched).

    Args:
        config: A config whose every scenario is flat (no ``markets`` key).

    Returns:
        ``(summary_df, participant_df)``.
    """
    from ..config_io import normalize_config
    from .events import solve_scenario_with_events

    normalized = normalize_config(deepcopy(config))
    plain = [s for s in normalized["scenarios"] if not s.get("policy_events")]
    evented = [s for s in normalized["scenarios"] if s.get("policy_events")]

    if not evented:
        return run_simulation(build_markets_from_config(normalized))

    frames: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    if plain:
        frames.append(run_simulation(build_markets_from_config({"scenarios": plain})))
    for scenario in evented:
        frames.append(solve_scenario_with_events(scenario))
    return (
        pd.concat([f[0] for f in frames], ignore_index=True),
        pd.concat([f[1] for f in frames], ignore_index=True),
    )


def run_simulation_from_config(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Solve a config, routing linked (multi-market) scenarios to the DAG solver.

    Partition (D1-3): a scenario carrying a ``markets`` key is a multi-market
    (linked) scenario and is routed to :func:`solve_multi_market_scenario`;
    every other scenario is flat and stays on the byte-identical legacy path
    (:func:`_run_flat_config`). A config with NO markets-shaped scenario — every
    committed golden — is handed WHOLE to ``_run_flat_config``, so the single-
    market path is bit-for-bit unchanged (the multi-market path is only taken by
    a linked config, of which none ship yet).

    Args:
        config: A raw config dict with a ``scenarios`` list.

    Returns:
        ``(summary_df, participant_df)`` — flat results first, then each
        multi-market scenario in declaration order.

    Raises:
        ValueError: ``scenarios`` is not a list; or any downstream validation
            error (link validation, cycle, E7 events-on-multi-market, E8
            horizon).
    """
    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("Config must contain a 'scenarios' list.")

    multi = [s for s in scenarios if isinstance(s, dict) and "markets" in s]
    if not multi:
        # No linked scenario: the whole config down the untouched legacy path.
        return _run_flat_config(config)

    flat = [s for s in scenarios if not (isinstance(s, dict) and "markets" in s)]
    frames: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    if flat:
        frames.append(_run_flat_config({"scenarios": flat}))
    for scenario in multi:
        frames.append(solve_multi_market_scenario(scenario))
    return (
        pd.concat([f[0] for f in frames], ignore_index=True),
        pd.concat([f[1] for f in frames], ignore_index=True),
    )


def _build_leg_markets(body: dict, composite_scenario_name: str) -> list[CarbonMarket]:
    """Build one market's ``CarbonMarket`` list under the composite scenario name.

    Wraps the already-normalized market ``body`` back into a single-scenario
    config keyed by the composite grouping name ``"{scenario} :: {market_id}"``
    (the ``_rename_markets`` suffix precedent) and hands it to
    ``build_markets_from_config`` — REUSING the whole builder pipeline (meta
    derivation, per-year construction, investment-spec stamping) rather than
    duplicating it. ``build_markets_from_config`` re-normalizes; the body is
    already normalized and normalization is idempotent (the legacy path already
    double-normalizes: ``normalize_config`` then ``build_markets_from_config``).

    Args:
        body: A normalized market body (from ``iter_market_bodies``).
        composite_scenario_name: ``"{scenario_name} :: {market_id}"``.

    Returns:
        The market's per-year ``CarbonMarket`` objects.
    """
    synthetic = {"scenarios": [{"name": composite_scenario_name, **body, "policy_events": []}]}
    return build_markets_from_config(synthetic)


def _solve_market_leg(
    shifted_markets: list[CarbonMarket], composite_scenario_name: str, market_id: str
) -> tuple[list[CarbonMarket], list[dict]]:
    """Solve ONE market of a chain — mirrors ``run_simulation``'s per-scenario body.

    Runs the SAME per-approach solve ``run_simulation`` runs for a single
    scenario (the ``_path_solver_for`` closure, UNTOUCHED), with the SAME
    investment-feedback wrapping — PER-MARKET, in topological order
    (block-triangular: one-way links make sequential per-market fixed points
    compose exactly to the chain equilibrium, spec §7 E4). ``model_approach
    "all"`` is rejected inside a multi-market scenario (the comparison fan-out
    is not one ``ordered_markets`` thread a link/adoption loop could wrap).

    Args:
        shifted_markets: The market's ``CarbonMarket`` list AFTER inbound-link
            application (link-shifted MACs / break-even thresholds).
        composite_scenario_name: For log/error attribution.
        market_id: For error attribution.

    Returns:
        ``(ordered_markets, path_details)`` — the chronologically sorted
        markets and the solved per-year detail dicts.

    Raises:
        ValueError: ``model_approach`` is ``"all"``; a half-configured
            investment scenario (via ``_investment_configured``); or a solve
            failure propagated from the wrapped path solver.
    """
    ordered_markets = sorted(shifted_markets, key=_market_year_sort_key)
    m0 = ordered_markets[0]
    approach = getattr(m0, "model_approach", "competitive") or "competitive"

    if approach == "all":
        raise ValueError(
            f"Scenario leg '{composite_scenario_name}' (market '{market_id}'): "
            "model_approach 'all' is not permitted inside a multi-market scenario "
            "— the comparison fan-out solves three renamed market lists, not one "
            "linkable/adoptable path. Pick a single approach per market."
        )

    transmission_lambda = getattr(m0, "forward_transmission_lambda", None)
    if transmission_lambda is not None and approach != "competitive":
        logger.warning(
            f"Scenario leg '{composite_scenario_name}': forward_transmission_lambda "
            f"is only applied under model_approach='competitive' (got '{approach}'); "
            "ignoring the λ blend."
        )
        transmission_lambda = None

    investment_on = _investment_configured(m0)
    solver = _path_solver_for(approach, m0, transmission_lambda=transmission_lambda)
    if investment_on:
        # Lazy imports (activation scoping) — identical to run_simulation.
        from ..features.endogenous_investment.rule import InvestmentRule
        from .feedback import solve_with_investment_feedback

        specs = tuple(
            spec
            for participant in m0.participants
            for spec in getattr(participant, "adoption_specs", ())
        )
        r = float(getattr(m0, "discount_rate", 0.04) or 0.04)
        max_iters_raw = getattr(m0, "investment_max_iterations", None)

        def _fresh_rule(specs: tuple = specs, r: float = r) -> InvestmentRule:
            return InvestmentRule(specs, r)

        path = solve_with_investment_feedback(
            ordered_markets,
            solver,
            _fresh_rule,
            specs,
            scenario_discount_rate=r,
            max_iterations=None if max_iters_raw is None else int(max_iters_raw),
        )
    else:
        path = solver(ordered_markets)
    return ordered_markets, path


def _delivered_path(path_details: list[dict]) -> dict[str, float]:
    """Extract ``{year_label: delivered_price}`` from a solved path (the E4 signal)."""
    return {str(item["market"].year): float(item["equilibrium"]["price"]) for item in path_details}


def _surface_leg_items(
    scenario_name: str,
    declared_ids: Sequence[str],
    leg_paths: Mapping[str, list[dict]],
) -> dict[str, dict[str, dict]]:
    """Group each market's solved path details into ``{composite: {year: item}}``.

    A REPORTING projection (no solve): re-keys the per-market solved detail lists
    already produced by the multi-market solve into the same shape the flat
    ``solve_scenario_path`` loop yields, so the web layer draws the identical
    121-point demand curve for a linked market as for a single one. Each ``item``
    is the untouched per-year bundle (``market`` — the link-shifted
    ``CarbonMarket`` at converged neighbor prices — ``equilibrium``,
    ``expected_future_price``, ``starting_bank_balances``, ``participant_df``).

    Keyed by the composite grouping name ``"{scenario} :: {market_id}"`` (the
    ``Scenario`` column both frames carry) and, within, by ``str(market.year)``
    — the exact string the participant frames carry in their ``"Year"`` column,
    so the web layer's per-(composite, year) lookup lands. REPORTED in
    declaration order (spec §3) to mirror the frames.

    Args:
        scenario_name: The scenario's grouping name.
        declared_ids: Market ids in declaration order (the reporting order).
        leg_paths: ``{market_id: [per-year detail dict, ...]}`` — the solved leg
            markets, one list per market (absent id ⇒ empty year map).

    Returns:
        ``{"{scenario} :: {market_id}": {year_label: item}}`` for every declared
        market id.
    """
    surfaced: dict[str, dict[str, dict]] = {}
    for market_id in declared_ids:
        composite = f"{scenario_name} :: {market_id}"
        surfaced[composite] = {
            str(item["market"].year): item for item in leg_paths.get(market_id, [])
        }
    return surfaced


def solve_multi_market_scenario(
    scenario: Mapping[str, object],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Solve one linked (multi-market) scenario — the reporting-frames surface.

    Thin 2-tuple wrapper over :func:`solve_multi_market_scenario_with_leg_items`
    (which does all the solving) that drops the third element — the surfaced
    solved leg-market bundle. Kept BYTE-IDENTICAL to the pre-enrichment public
    entry: every existing caller (``run_simulation_from_config``, the golden
    harness, the D2-3 dispatch tests) sees the exact same ``(summary_df,
    participant_df)`` pair. The web layer, which needs the per-market solved
    ``CarbonMarket`` objects to draw a real 121-point demand curve, calls the
    three-value function instead.

    Args:
        scenario: A raw multi-market scenario dict (``markets``/``links``; an
            optional ``joint_solver`` block tunes the cyclic outer loop).

    Returns:
        ``(summary_df, participant_df)`` — identical to
        :func:`solve_multi_market_scenario_with_leg_items`'s first two returns.

    Raises:
        ValueError: Every error the delegate raises (E7 events, E8 horizon,
            ``model_approach "all"``, link/body validation).
    """
    summary_df, participant_df, _leg_items = solve_multi_market_scenario_with_leg_items(scenario)
    return summary_df, participant_df


def solve_multi_market_scenario_with_leg_items(
    scenario: Mapping[str, object],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, dict]]]:
    """Solve one linked (multi-market) scenario — acyclic DAG or cyclic joint SCC.

    The D1-3 multi-market dispatch (``docs/platform-spec-d0-d1.md`` §2d, §3, §7),
    with the ONE D2-3 guarded branch (``docs/joint-equilibrium-plan.md`` §5):

    1. Guard policy events (E7): events × multi-market is deferred to D2.
    2. Read the normalized market bodies (``iter_market_bodies``) and build the
       ``LinkSpec`` graph (``engine.links.build_link_specs``).
    3. Enforce the E8 horizon strict-subset per link (at solve entry).
    4. Condense the market graph into SCCs (``engine.scc.condensation_order``).
       **All SCCs size-1 with no self-edge (acyclic) ⇒ the EXISTING D1 path runs
       VERBATIM** (``topological_market_order`` + per-market ``apply_inbound_links``
       + solve — byte-identical; the golden-inertness requirement). **Any cyclic
       SCC ⇒ the joint path** (:func:`_solve_cyclic_multi_market`): each cyclic
       SCC is handed to ``engine.joint.solve_joint_scc``; size-1 SCCs still solve
       as D1, in condensation order.
    5. (Acyclic path) Solve each market in topological order. BEFORE a market
       solves, apply its inbound links (``engine.links.apply_inbound_links``)
       reading the FINAL delivered paths of its already-solved ancestors — ONCE,
       before the path solve (spec §2d). Investment feedback wraps each market's
       solve PER MARKET (block-triangular, E4).
    6. Collect results under the composite grouping key ``"{scenario} ::
       {market_id}"`` so ``collect_path_results``/summary machinery is
       unmodified; stamp the guarded ``"Market"`` and link-diagnostic columns
       (E6). REPORT in DECLARATION order (spec §3), while SOLVING in
       condensation/topological order.

    Args:
        scenario: A raw multi-market scenario dict (``markets``/``links``; an
            optional ``joint_solver`` block tunes the cyclic outer loop).

    Returns:
        ``(summary_df, participant_df, leg_items)``:

        * ``summary_df``, ``participant_df`` — rows in declaration order of the
          markets, each summary row carrying the guarded ``"Market"`` column and,
          for a market with inbound links, per-(from,to) ``"Link ... Price In"``
          and per-(from,to,channel) ``"Link ... Input Shift"`` diagnostic columns.
          Cyclic-SCC market rows ALSO carry the four ``"Joint *"`` columns
          (key-presence guarded — acyclic rows never gain them). These two frames
          (and the solved prices / ``Joint *`` columns they carry) are UNCHANGED
          by the leg-item surfacing — it retains already-solved objects, it does
          not re-solve or perturb the solve.
        * ``leg_items`` — the ADDITIONAL surfaced structure (D-curve enrichment):
          ``{"{scenario} :: {market_id}": {year_label: item}}``, where each
          ``item`` is the solved per-year bundle matching
          :func:`~pe.engine.solve_scenario_path`'s yield (``market`` — the
          link-shifted ``CarbonMarket`` at the converged neighbor prices —
          ``equilibrium``, ``expected_future_price``, ``starting_bank_balances``,
          ``participant_df``). Same composite grouping key as the frames; the
          ``item["participant_df"]`` is the SAME object appended to
          ``participant_df``. Lets the web layer draw the identical 121-point
          demand curve it draws for a flat single-market run.

    Raises:
        ValueError: policy events present (E7); an E8 horizon violation;
            ``model_approach "all"`` in a market; or any link/body validation
            error. (A cycle is no longer an error — R34 flipped, D2-3.)
    """
    from .links import (
        apply_inbound_links,
        build_link_specs,
        check_horizon_alignment,
        topological_market_order,
    )
    from .scc import condensation_order

    scenario_name = str(
        scenario.get("name") or scenario.get("scenario_name") or "Multi-Market Scenario"
    ).strip()

    if scenario.get("policy_events"):
        raise ValueError(
            f"Scenario '{scenario_name}': policy_events on a multi-market scenario "
            "are deferred to D2 (E7) — per-market carriers × link re-application × "
            "cross-market announcement semantics is an open design problem. The "
            "natural first relaxation is events on SINK markets only (no outgoing "
            "links), where the existing splice machinery is already correct; until "
            "then, keep events single-market."
        )

    market_bodies = iter_market_bodies(scenario)
    # Multi-market scenarios always key every body by a non-None market_id (the
    # None key is the degenerate flat case, which the partition never routes
    # here); str() keeps the ids typed for the ordering/link machinery.
    declared_ids = [str(market_id) for market_id, _ in market_bodies]
    bodies_by_id = {str(market_id): body for market_id, body in market_bodies}

    links = build_link_specs(scenario)
    check_horizon_alignment(links, bodies_by_id)

    # The ONE D2-3 guarded branch (docs/joint-equilibrium-plan.md §5). Condense
    # the market graph: ANY cyclic SCC routes to the joint path; an all-acyclic
    # graph (every SCC size-1, no self-edge) falls through to the EXISTING D1
    # code below UNCHANGED — the golden-inertness requirement. condensation_order
    # is a pure read of the graph and does not touch the acyclic solve output.
    sccs = condensation_order(declared_ids, links)
    if any(scc.cyclic for scc in sccs):
        return _solve_cyclic_multi_market(
            scenario, scenario_name, sccs, declared_ids, bodies_by_id, links
        )

    topo_ids = topological_market_order(declared_ids, links)

    solved_delivered_paths: dict[str, dict[str, float]] = {}
    leg_summaries: dict[str, list[dict]] = {}
    leg_frames: dict[str, list[pd.DataFrame]] = {}
    # The solved per-year detail dicts per market — the link-shifted CarbonMarket
    # + equilibrium bundle a 121-point demand curve is drawn from. Retained here
    # (already in hand from the solve) and surfaced as the third return; touching
    # neither the summaries nor the frames above.
    leg_paths: dict[str, list[dict]] = {}

    for market_id in topo_ids:
        composite = f"{scenario_name} :: {market_id}"
        base_markets = _build_leg_markets(bodies_by_id[market_id], composite)
        inbound = [link for link in links if link.to_market == market_id]
        logger.debug(
            "Multi-market solve: market %r, inbound_links=%d, ancestors_solved=%d",
            market_id,
            len(inbound),
            len(solved_delivered_paths),
        )
        shifted = apply_inbound_links(market_id, base_markets, inbound, solved_delivered_paths)
        ordered, path = _solve_market_leg(shifted, composite, market_id)
        solved_delivered_paths[market_id] = _delivered_path(path)

        local_summaries: list[dict] = []
        local_frames: list[pd.DataFrame] = []
        _collect_path_results(ordered, path, local_summaries, local_frames)
        _stamp_multi_market_columns(
            local_summaries, path, market_id, inbound, solved_delivered_paths
        )
        leg_summaries[market_id] = local_summaries
        leg_frames[market_id] = local_frames
        leg_paths[market_id] = path

    # SOLVE topological, REPORT in declaration order (spec §3).
    scenario_summaries: list[dict] = []
    participant_frames: list[pd.DataFrame] = []
    for market_id in declared_ids:
        scenario_summaries.extend(leg_summaries[market_id])
        participant_frames.extend(leg_frames[market_id])

    summary_df = pd.DataFrame.from_records(scenario_summaries)
    participant_df = pd.concat(participant_frames, ignore_index=True)
    leg_items = _surface_leg_items(scenario_name, declared_ids, leg_paths)
    return summary_df, participant_df, leg_items


def _adoption_state_to_config(state: AdoptionState) -> list[dict[str, str]]:
    """Render an adoption state as the ``investment_initial_adoptions`` list form.

    The inverse of the field ``solve_with_investment_feedback`` reads as
    ``state_0`` (``getattr(m0, "investment_initial_adoptions")`` →
    ``parse_adoption_state``). Produces the SAME ``{participant, technology,
    adoption_year}`` records the splice carrier stamps across policy-event
    segments, so carrying the cyclic-SCC adoption floor reuses that landing
    field verbatim (``docs/joint-equilibrium.md`` §4 "reuse the splice-carrier
    FLOOR").

    Args:
        state: A canonical ``AdoptionState`` (normalized defensively).

    Returns:
        A list of ``{participant, technology, adoption_year}`` dicts; ``[]`` for
        the empty state (falsy → the feedback host treats it as no carry).
    """
    return [
        {
            "participant": event.participant_name,
            "technology": event.technology_name,
            "adoption_year": event.adoption_year,
        }
        for event in make_adoption_state(state)
    ]


def _final_adoption_state(path_details: list[dict]) -> AdoptionState:
    """Read back the adoption state a solved (investment-wrapped) path was under.

    The feedback host stamps ``investment_adoptions`` (a serialized state,
    effective THROUGH each row's year) on every detail row; the LAST row
    (latest year) carries the whole state, since every adoption year τ is a
    price-path year and so ≤ the horizon's last year. Rows without the key
    (investment not configured for this market) yield the empty state.

    Args:
        path_details: The solved per-year detail dicts (year order).

    Returns:
        The canonical ``AdoptionState`` the path was solved under (``()`` when
        no investment ran).
    """
    if path_details and "investment_adoptions" in path_details[-1]:
        return parse_adoption_state(path_details[-1]["investment_adoptions"])
    return ()


def _enforce_floor_monotone(
    previous_floor: AdoptionState, new_state: AdoptionState, market_id: str
) -> None:
    r"""Assert the across-outer-sweep adoption FLOOR only grows (spec §4).

    The outer-loop analogue of ``feedback._enforce_monotone_one_flip``: an
    option adopted on an earlier sweep must stay adopted (superset) at its
    ORIGINAL decision year (no re-dating) on every later sweep — the monotone
    floor the economist's §4 termination argument rests on (adoptions
    accumulate, bounded by ΣN_i, then FREEZE → the outer loop becomes a pure
    price contraction).

    ECONOMIC JUDGMENT CALL (flagged for sign-off): this reuses the superset +
    no-redate legs of the Phase-1 host check but DROPS its "≤ one new pair per
    call" leg. That one-flip bound is a WITHIN-sweep invariant of the middle
    loop (``feedback.solve_with_investment_feedback`` enforces it there); ACROSS
    sweeps a market whose middle loop crosses several of its options' triggers
    at the sweep's fixed neighbor prices legitimately adds MORE than one
    adoption to its floor, so enforcing one-per-sweep here would false-positive
    on a multi-option market. §4 defines the floor as "monotone across outer
    iterations" and never bounds per-sweep additions, so the monotone (superset
    + no-redate) reading is the anchor; the one-flip counter stays where it
    belongs — inside the middle loop.

    Args:
        previous_floor: The market's accumulated floor entering this sweep.
        new_state: The adoption state this sweep's middle loop converged to.
        market_id: The SCC member id (for error attribution).

    Raises:
        ValueError: ``new_state`` drops or re-dates a pair in ``previous_floor``
            (a middle loop violating irreversibility — never repaired silently).
    """
    new_year_by_pair = {
        (event.participant_name, event.technology_name): event.adoption_year for event in new_state
    }
    for event in previous_floor:
        pair = (event.participant_name, event.technology_name)
        if pair not in new_year_by_pair:
            raise ValueError(
                f"joint investment: SCC member {market_id!r} DROPPED adopted pair "
                f"{pair} across an outer sweep — the adoption floor is monotone "
                "(once adopted, never un-adopted; docs/joint-equilibrium.md §4)."
            )
        if new_year_by_pair[pair] != event.adoption_year:
            raise ValueError(
                f"joint investment: SCC member {market_id!r} RE-DATED adopted pair "
                f"{pair} from {event.adoption_year!r} to {new_year_by_pair[pair]!r} "
                "across an outer sweep — adoption years are written once (§4)."
            )


def _solve_scc_member(
    market_id: str,
    composite_scenario_name: str,
    bodies_by_id: Mapping[str, dict],
    links: Sequence[LinkSpec],
    delivered_paths: Mapping[str, Mapping[str, float]],
    *,
    adoption_floor: AdoptionState | None = None,
) -> tuple[list[CarbonMarket], list[dict], AdoptionState]:
    r"""Solve one SCC member against a combined delivered-paths map (D2-3/D2-5 seam).

    Builds the market's ``CarbonMarket`` list, applies its inbound links, and
    runs the SAME per-approach ``_solve_market_leg`` the acyclic D1 path runs.
    An inbound link whose source has NO delivered path yet in ``delivered_paths``
    (a not-yet-swept SCC sibling on the cold first sweep) is CUT — its ``phi·P``
    contribution is omitted — which reproduces the blessed V-D2-1 one-way seed
    (forward links normal, cycle-closing back-links cut,
    ``docs/joint-equilibrium.md`` §6). At the final converged re-solve every
    sibling price is present, so no link is cut.

    D2-5 investment nesting (``docs/joint-equilibrium.md`` §4, V-D2-4). When
    ``adoption_floor`` is given (the cyclic path, on every sweep after the
    first), it is stamped into ``investment_initial_adoptions`` on the built
    markets, so this sweep's investment MIDDLE loop
    (``feedback.solve_with_investment_feedback``, run inside ``_solve_market_leg``
    when the market is investment-configured) starts from the outer-accumulated
    FLOOR rather than the config seed — the reused splice-carrier landing field.
    The middle loop then runs Phase 1 verbatim against THIS sweep's neighbor
    prices (already compiled into the shifted markets by ``apply_inbound_links``),
    adopting only ABOVE the floor. The adoption state the path was solved under
    is returned as the third element so the caller can accumulate the floor.

    ``adoption_floor=None`` (the ACYCLIC path: size-1 SCC members, and the
    single-market ``_solve_market_leg`` route) leaves ``investment_initial_adoptions``
    at its config value — byte-identical to Phase 1 (proven by the acyclic
    inertness control test).

    Args:
        market_id: The SCC member being solved.
        composite_scenario_name: ``"{scenario} :: {market_id}"``.
        bodies_by_id: Normalized market bodies keyed by market id.
        links: The scenario's links (only this market's inbound ones apply).
        delivered_paths: ``{market_id: {year: price}}`` — the frozen upstream
            paths unioned with the SCC's in-flight working paths.
        adoption_floor: The outer-accumulated monotone adoption floor to seed
            this sweep's middle loop with (kw-only); ``None`` leaves the config
            seed untouched (the acyclic / Phase-1 path).

    Returns:
        ``(ordered_markets, path_details, final_state)`` — the first two as
        :func:`_solve_market_leg`; ``final_state`` is the adoption state the
        path was solved under (``()`` when no investment ran).
    """
    from .links import apply_inbound_links

    base_markets = _build_leg_markets(bodies_by_id[market_id], composite_scenario_name)
    if adoption_floor is not None:
        # Carry the outer-sweep floor into the middle loop via the SAME field the
        # splice carrier lands on (§4). Empty floor -> [] -> falsy -> config seed.
        seed = _adoption_state_to_config(adoption_floor)
        for market in base_markets:
            # setattr (not a typed attribute write): CarbonMarket carries the
            # investment fields dynamically — this file reads them via getattr,
            # so it writes via setattr symmetrically (no new mypy attr-defined).
            setattr(market, "investment_initial_adoptions", seed)  # noqa: B010
    inbound = [
        link
        for link in links
        if link.to_market == market_id and delivered_paths.get(link.from_market)
    ]
    shifted = apply_inbound_links(market_id, base_markets, inbound, delivered_paths)
    ordered, path = _solve_market_leg(shifted, composite_scenario_name, market_id)
    return ordered, path, _final_adoption_state(path)


def _solve_cyclic_scc(
    scc: SCC,
    scenario_name: str,
    bodies_by_id: Mapping[str, dict],
    links: Sequence[LinkSpec],
    solved_delivered_paths: dict[str, dict[str, float]],
    leg_summaries: dict[str, list[dict]],
    leg_frames: dict[str, list[pd.DataFrame]],
    leg_paths: dict[str, list[dict]],
    joint_settings: Mapping[str, object] | None,
) -> None:
    r"""Solve one cyclic SCC via the joint outer loop; collect + stamp its members.

    Hands the SCC to ``engine.joint.solve_joint_scc`` with an injected
    per-market closure (``_solve_scc_member`` combined with the frozen upstream
    paths and the SCC's in-flight working paths — the D2-3 hook, now carrying
    D2-5's investment MIDDLE loop). After convergence, freezes the fixed-point
    prices into ``solved_delivered_paths`` and RE-SOLVES each member once against
    those converged sibling prices AND the converged adoption floor to collect
    its full result frames (``T_m(P*) = P*`` at the fixed point,
    ``docs/joint-equilibrium.md`` §1), then stamps the four guarded ``Joint *``
    columns on every one of that member's rows.

    Algorithm:
        MIDDLE-inside-OUTER with adoption-as-outer-FLOOR (V-D2-4, §4). Let
        ``T_m`` be market m's investment-wrapped path solve (the Phase-1 middle
        loop) and ``A_m^{k}`` its accumulated adoption floor entering outer
        sweep k. Each sweep runs the middle loop from the floor against the
        current neighbor prices, then MONOTONELY accumulates:

        LaTeX:
        $$ \big(P_m^{k},\,A_m^{k}\big) \;=\; T_m\!\big(P_{n}^{\,\cdot};\,
             A_m^{k-1}\big), \qquad
           A_m^{k-1} \subseteq A_m^{k} \subseteq \bigcup_i N_i , $$
        $$ A_m^{k} \equiv A_m^{k-1}\ \forall m \;\Longrightarrow\;
           \text{floor frozen} \;\Rightarrow\; \text{outer loop is a pure}
           \text{ price contraction (eventually-continuous termination).} $$

        ASCII fallback:
            floor[m] = config seed (first sweep) ; monotone across sweeps
            each outer sweep k, each member m in sweep order:
                path_m = investment_wrapped_solve(m, neighbor prices, seed=floor[m])
                A_m    = adoption state path_m was solved under   # >= floor[m]
                assert A_m superset floor[m], no re-date          # host check
                floor[m] = A_m                                    # accumulate
            floor grows only finitely (bounded by union of N_i) then FREEZES;
            above the frozen floor joint.py's damped price contraction runs.

        Symbols (units):
            P_m^k     : member m's delivered price path at outer sweep k
                        [currency_m/unit_m]
            A_m^k     : member m's accumulated adoption floor at sweep k
                        (set of (participant, technology, τ) pairs) [-]
            N_i       : the flagged option set of participant i (adoption cap) [-]
            τ         : an adoption (decision) year label [yr]

    Args:
        scc: The cyclic SCC (``members`` in deterministic sweep order).
        scenario_name: The scenario's grouping name.
        bodies_by_id: Normalized market bodies keyed by market id.
        links: The scenario's links.
        solved_delivered_paths: Mutable ``{market_id: {year: price}}`` — read for
            frozen upstream paths, extended in place with the SCC's converged
            prices.
        leg_summaries: Mutable per-market summary rows (extended in place).
        leg_frames: Mutable per-market participant frames (extended in place).
        leg_paths: Mutable per-member solved detail lists (extended in place) —
            the reporting re-solve's link-shifted-CarbonMarket bundles at the
            converged prices, surfaced for the web demand curve. Written from the
            SAME ``path`` the frames are collected from, so it carries the
            converged fixed-point objects and nothing the frames do not.
        joint_settings: The normalized ``joint_solver`` settings, or ``None`` for
            the engine defaults (``docs/joint-equilibrium-plan.md`` §4).
    """
    from .joint import solve_joint_scc

    members = list(scc.members)

    # Per-member adoption FLOOR carried ACROSS outer sweeps (§4, V-D2-4):
    # monotone — an option adopted on sweep k stays adopted on sweep k+1. {} ⇒
    # the first sweep for each member seeds its middle loop from that member's
    # config ``investment_initial_adoptions`` (adoption_floor=None below), so a
    # cyclic member with no investment stays byte-identical to D2-3.
    adoption_floor: dict[str, AdoptionState] = {}

    def _solve_one_market(
        market_id: str, scc_working_paths: Mapping[str, Mapping[str, float]]
    ) -> Mapping[str, float]:
        # Union the frozen upstream paths (already-solved SCCs) with the SCC's
        # in-flight working paths, then solve this member (back-links to
        # not-yet-swept siblings are cut inside _solve_scc_member — the seed).
        combined = {**solved_delivered_paths, **scc_working_paths}
        composite = f"{scenario_name} :: {market_id}"
        prior = adoption_floor.get(market_id)  # None on the first sweep -> config seed
        _ordered, path, final_state = _solve_scc_member(
            market_id, composite, bodies_by_id, links, combined, adoption_floor=prior
        )
        # Monotone-across-sweeps host check + accumulate the floor (§4). The
        # middle loop seeded from the floor can only ADD, so this never shrinks;
        # the check is the belt-and-braces irreversibility guard.
        previous = adoption_floor.get(market_id, ())
        _enforce_floor_monotone(previous, final_state, market_id)
        adoption_floor[market_id] = final_state
        if len(final_state) != len(previous):
            logger.debug(
                "joint investment: member %r floor grew %d -> %d adopted pair(s)",
                market_id,
                len(previous),
                len(final_state),
            )
        return _delivered_path(path)

    settings = joint_settings or {}
    result = solve_joint_scc(
        members,
        _solve_one_market,
        links=links,
        relaxation=settings.get("relaxation"),  # type: ignore[arg-type]
        max_iterations=settings.get("max_iterations"),  # type: ignore[arg-type]
        tolerance=settings.get("tolerance"),  # type: ignore[arg-type]
    )

    # Freeze the converged fixed-point prices BEFORE the reporting re-solve, so
    # each member's link-diagnostic stamping reads every SIBLING's converged
    # price (spec §4: ex-post checks run against the converged joint vector).
    for member in members:
        solved_delivered_paths[member] = dict(result.market_paths[member])

    joint_cols = result.report_columns()
    for member in members:
        composite = f"{scenario_name} :: {member}"
        # Re-solve against the converged sibling prices AND the CONVERGED floor
        # (§4 PIN: ex-post checks run against the converged joint vector). At a
        # genuine fixed point the middle loop reproduces the floor (no new
        # crossing), so the reported price matches the joint price and the
        # reported adoptions are the equilibrium floor.
        ordered, path, _final = _solve_scc_member(
            member,
            composite,
            bodies_by_id,
            links,
            solved_delivered_paths,
            adoption_floor=adoption_floor.get(member),
        )
        local_summaries: list[dict] = []
        local_frames: list[pd.DataFrame] = []
        _collect_path_results(ordered, path, local_summaries, local_frames)
        inbound = [link for link in links if link.to_market == member]
        _stamp_multi_market_columns(local_summaries, path, member, inbound, solved_delivered_paths)
        for summary_row in local_summaries:  # the four Joint columns — cyclic rows ONLY
            summary_row.update(joint_cols)
        leg_summaries[member] = local_summaries
        leg_frames[member] = local_frames
        # Retain the converged-price re-solve's leg markets for the web demand
        # curve (same ``path`` the frames above were collected from).
        leg_paths[member] = path


def _solve_cyclic_multi_market(
    scenario: Mapping[str, object],
    scenario_name: str,
    sccs: Sequence[SCC],
    declared_ids: Sequence[str],
    bodies_by_id: Mapping[str, dict],
    links: Sequence[LinkSpec],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, dict]]]:
    """Solve a multi-market scenario containing >=1 cyclic SCC (the joint path).

    Walks the SCCs in condensation order (upstream first): a size-1 acyclic SCC
    solves EXACTLY as D1 (against already-solved upstream paths, NO ``Joint *``
    columns); a cyclic SCC goes through :func:`_solve_cyclic_scc`. Reports in
    declaration order (spec §3) while solving in condensation order. Only reached
    when the acyclic guard in :func:`solve_multi_market_scenario_with_leg_items`
    fails, so the all-acyclic golden path never enters here.

    Args:
        scenario: The raw multi-market scenario (read for the ``joint_solver``
            block; ``docs/joint-equilibrium-plan.md`` §4).
        scenario_name: The scenario's grouping name.
        sccs: The condensation order (``engine.scc.condensation_order``).
        declared_ids: Market ids in declaration order (the reporting order).
        bodies_by_id: Normalized market bodies keyed by market id.
        links: The scenario's links.

    Returns:
        ``(summary_df, participant_df, leg_items)`` — the frames in declaration
        order (cyclic-SCC rows carry the four ``Joint *`` columns, acyclic rows
        do not), plus the surfaced ``{composite: {year: item}}`` solved leg-market
        bundle (:func:`_surface_leg_items`); frames and prices unchanged by the
        surfacing.
    """
    from ..config_io import normalize_joint_solver

    joint_settings = normalize_joint_solver(
        scenario.get("joint_solver"),  # type: ignore[arg-type]
        label=f"Scenario '{scenario_name}'",
    )

    solved_delivered_paths: dict[str, dict[str, float]] = {}
    leg_summaries: dict[str, list[dict]] = {}
    leg_frames: dict[str, list[pd.DataFrame]] = {}
    # Solved per-year detail dicts per market (cyclic: from the converged-price
    # reporting re-solve; acyclic: from the D1 leg) — surfaced for the web curve.
    leg_paths: dict[str, list[dict]] = {}

    for scc in sccs:
        if scc.cyclic:
            _solve_cyclic_scc(
                scc,
                scenario_name,
                bodies_by_id,
                links,
                solved_delivered_paths,
                leg_summaries,
                leg_frames,
                leg_paths,
                joint_settings,
            )
            continue
        # Size-1 acyclic SCC — the byte-identical D1 leg (no Joint columns). No
        # adoption_floor (None) ⇒ Phase-1 investment runs exactly as today.
        (market_id,) = scc.members
        composite = f"{scenario_name} :: {market_id}"
        ordered, path, _final = _solve_scc_member(
            market_id, composite, bodies_by_id, links, solved_delivered_paths
        )
        solved_delivered_paths[market_id] = _delivered_path(path)
        local_summaries: list[dict] = []
        local_frames: list[pd.DataFrame] = []
        _collect_path_results(ordered, path, local_summaries, local_frames)
        inbound = [link for link in links if link.to_market == market_id]
        _stamp_multi_market_columns(
            local_summaries, path, market_id, inbound, solved_delivered_paths
        )
        leg_summaries[market_id] = local_summaries
        leg_frames[market_id] = local_frames
        leg_paths[market_id] = path

    # SOLVE in condensation order, REPORT in declaration order (spec §3).
    scenario_summaries: list[dict] = []
    participant_frames: list[pd.DataFrame] = []
    for market_id in declared_ids:
        scenario_summaries.extend(leg_summaries[market_id])
        participant_frames.extend(leg_frames[market_id])

    summary_df = pd.DataFrame.from_records(scenario_summaries)
    participant_df = pd.concat(participant_frames, ignore_index=True)
    leg_items = _surface_leg_items(scenario_name, declared_ids, leg_paths)
    return summary_df, participant_df, leg_items


def _stamp_multi_market_columns(
    summaries: list[dict],
    path_details: list[dict],
    market_id: str,
    inbound_links: list,
    solved_delivered_paths: Mapping[str, Mapping[str, float]],
) -> None:
    """Stamp the guarded ``Market`` + per-link diagnostic columns onto summary rows.

    Multi-market-ONLY, key-presence-guarded (the D3 reporter-conditionality
    precedent — an always-on column fails goldens): ``collect_path_results``
    stays unmodified; these columns are appended to the summary dicts it
    produced (aligned by year — ``summaries`` and ``path_details`` are both in
    path order). E6 exact ASCII strings:

    * ``"Market"`` — the market id (every multi-market row).
    * ``"Link {from}->{to} Price In"`` — the source's delivered ``P_A(t)``, one
      column per ``(from, to)`` pair, deduped (two channels on a pair share it).
    * ``"Link {from}->{to} {channel} Input Shift"`` — ``phi·P_A(t)``, channel-
      qualified so two links on a pair with distinct channels never collide.

    Args:
        summaries: The market's summary rows (mutated in place — columns
            appended at the tail).
        path_details: The market's per-year detail dicts (same order as
            ``summaries``; source of each row's year label).
        market_id: The market id stamped into ``"Market"``.
        inbound_links: The market's inbound ``LinkSpec`` list (empty → only the
            ``"Market"`` column is stamped).
        solved_delivered_paths: ``{market_id: {year: delivered_price}}`` — read
            for each inbound link's source ``P_A(t)``.
    """
    for summary_row, item in zip(summaries, path_details, strict=True):
        summary_row["Market"] = market_id
        year = str(item["market"].year)
        priced_pairs: set[tuple[str, str]] = set()
        for link in inbound_links:
            price_in = float(solved_delivered_paths[link.from_market][year])
            pair = (link.from_market, link.to_market)
            if pair not in priced_pairs:
                summary_row[f"Link {link.from_market}->{link.to_market} Price In"] = price_in
                priced_pairs.add(pair)
            shift_col = f"Link {link.from_market}->{link.to_market} {link.channel} Input Shift"
            summary_row[shift_col] = float(link.phi) * price_in


def run_simulation_from_file(config_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return run_simulation_from_config(load_config(config_path))
