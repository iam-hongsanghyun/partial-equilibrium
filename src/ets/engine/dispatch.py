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
"""

from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from ..config_io import build_markets_from_config, load_config

# Aliased to the pre-move underscore names so the bodies below stay verbatim.
from ..core.ledger import (
    collect_path_results as _collect_path_results,
    market_year_sort_key as _market_year_sort_key,
)

if TYPE_CHECKING:
    from ..core.market import CarbonMarket

logger = logging.getLogger(__name__)


def _rename_markets(markets: list[CarbonMarket], suffix: str) -> list[CarbonMarket]:
    """Return shallow copies of markets with scenario_name suffixed."""
    renamed = []
    for m in markets:
        copy = deepcopy(m)
        copy.scenario_name = f"{m.scenario_name} [{suffix}]"
        renamed.append(copy)
    return renamed


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

        def _hot_kwargs():
            return dict(
                discount_rate=float(getattr(m0, "discount_rate", 0.04) or 0.04),
                risk_premium=float(getattr(m0, "risk_premium", 0.0) or 0.0),
                max_bisection_iters=int(getattr(m0, "solver_hotelling_max_bisection_iters", 80) or 80),
                max_lambda_expansions=int(getattr(m0, "solver_hotelling_max_lambda_expansions", 20) or 20),
                convergence_tol=float(getattr(m0, "solver_hotelling_convergence_tol", 1e-4) or 1e-4),
            )

        def _nash_kwargs():
            return dict(
                strategic_participants=list(getattr(m0, "nash_strategic_participants", None) or []) or None,
                price_step=float(getattr(m0, "solver_nash_price_step", 0.5) or 0.5),
                max_iters=int(getattr(m0, "solver_nash_max_iters", 120) or 120),
                convergence_tol=float(getattr(m0, "solver_nash_convergence_tol", 1e-3) or 1e-3),
            )

        transmission_lambda = getattr(m0, "forward_transmission_lambda", None)
        if transmission_lambda is not None and approach != "competitive":
            logger.warning(
                f"Scenario '{scenario_name}': forward_transmission_lambda is only "
                f"applied under model_approach='competitive' (got '{approach}'); "
                "ignoring the λ blend."
            )
            transmission_lambda = None

        if transmission_lambda is not None:
            from .wiring import solve_transmission_path

            path = solve_transmission_path(
                ordered_markets, lam=float(transmission_lambda), **_hot_kwargs()
            )
            _collect_path_results(ordered_markets, path, scenario_summaries, participant_frames)

        elif approach == "banking":
            from .wiring import solve_banking_path

            path = solve_banking_path(
                ordered_markets,
                discount_rate=float(getattr(m0, "discount_rate", 0.055) or 0.055),
                risk_premium=float(getattr(m0, "risk_premium", 0.0) or 0.0),
            )
            _collect_path_results(ordered_markets, path, scenario_summaries, participant_frames)

        elif approach == "hotelling":
            path = solve_hotelling_path(ordered_markets, **_hot_kwargs())
            _collect_path_results(ordered_markets, path, scenario_summaries, participant_frames)

        elif approach == "nash_cournot":
            path = solve_nash_path(ordered_markets, **_nash_kwargs())
            _collect_path_results(ordered_markets, path, scenario_summaries, participant_frames)

        elif approach == "all":
            comp_markets = _rename_markets(ordered_markets, "Competitive")
            hot_markets  = _rename_markets(ordered_markets, "Hotelling")
            nash_markets = _rename_markets(ordered_markets, "Nash-Cournot")

            comp_path = solve_scenario_path(comp_markets)
            hot_path  = solve_hotelling_path(hot_markets, **_hot_kwargs())
            nash_path = solve_nash_path(nash_markets, **_nash_kwargs())

            for path, mkt_list in [(comp_path, comp_markets), (hot_path, hot_markets), (nash_path, nash_markets)]:
                _collect_path_results(mkt_list, path, scenario_summaries, participant_frames)

        else:
            # Default: competitive (MSR handled inside solve_scenario_path)
            path = solve_scenario_path(ordered_markets)
            _collect_path_results(ordered_markets, path, scenario_summaries, participant_frames)

    summary_df = pd.DataFrame.from_records(scenario_summaries)
    participant_df = pd.concat(participant_frames, ignore_index=True)
    return summary_df, participant_df


def run_simulation_from_config(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
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


def run_simulation_from_file(config_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return run_simulation_from_config(load_config(config_path))
