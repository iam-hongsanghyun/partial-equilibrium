from __future__ import annotations

import logging
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import pandas as pd

from ..core.expectations import (
    build_expectation_specs,
    derive_expected_prices,
    expectation_sort_key,
)
from ..core.defaults import MSR_DEFAULTS
from ..core.market import CarbonMarket
from .msr import MSRState
from .ccr import CCRState
from ..config_io import build_markets_from_config, load_config

logger = logging.getLogger(__name__)


def _market_year_sort_key(market: CarbonMarket) -> tuple[float, str]:
    return expectation_sort_key(market.year)


def solve_scenario_path(
    ordered_markets: list[CarbonMarket],
    max_iterations: int | None = None,
    tolerance: float | None = None,
) -> list[dict]:
    # Use solver settings from the first market if not explicitly supplied
    if max_iterations is None:
        max_iterations = int(getattr(ordered_markets[0], "solver_competitive_max_iters", 25) or 25)
    if tolerance is None:
        tolerance = float(getattr(ordered_markets[0], "solver_competitive_tolerance", 1e-3) or 1e-3)
    if not ordered_markets:
        return []

    ordered_years = [str(market.year) for market in ordered_markets]
    baseline_prices = {
        str(market.year): market.find_equilibrium_price() for market in ordered_markets
    }
    expectation_specs = build_expectation_specs(ordered_markets)

    expected_prices = derive_expected_prices(
        ordered_years,
        expectation_specs,
        baseline_prices,
    )

    if any(spec.rule == "perfect_foresight" for spec in expectation_specs.values()):
        for _ in range(max_iterations):
            realized_prices = _simulate_realized_prices(
                ordered_markets,
                expected_prices,
            )
            updated_expected_prices = derive_expected_prices(
                ordered_years,
                expectation_specs,
                baseline_prices,
                realized_prices=realized_prices,
            )
            max_delta = max(
                abs(updated_expected_prices[year] - expected_prices.get(year, 0.0))
                for year in ordered_years
            )
            expected_prices = updated_expected_prices
            if max_delta <= tolerance:
                break

    msr_state = MSRState() if getattr(ordered_markets[0], "msr_enabled", False) else None
    ccr_state = CCRState() if getattr(ordered_markets[0], "ccr_enabled", False) else None
    return _simulate_path_details(
        ordered_markets, expected_prices, msr_state=msr_state, ccr_state=ccr_state
    )


def _simulate_realized_prices(
    ordered_markets: list[CarbonMarket],
    expected_prices: dict[str, float],
) -> dict[str, float]:
    # MSR / CCR are NOT applied in the inner convergence loop (prices only)
    details = _simulate_path_details(
        ordered_markets, expected_prices, msr_state=None, ccr_state=None
    )
    return {
        str(item["market"].year): float(item["equilibrium"]["price"])
        for item in details
    }


def _simulate_path_details(
    ordered_markets: list[CarbonMarket],
    expected_prices: dict[str, float],
    msr_state: MSRState | None = None,
    ccr_state: CCRState | None = None,
) -> list[dict]:
    bank_balances = {
        participant.name: 0.0 for participant in ordered_markets[0].participants
    }
    carry_forward_allowances = 0.0
    details: list[dict] = []

    for market in ordered_markets:
        expected_future_price = float(expected_prices.get(str(market.year), 0.0))
        starting_bank_balances = dict(bank_balances)

        # ── MSR: adjust auction supply before clearing ────────────────────
        msr_withheld = 0.0
        msr_released = 0.0
        msr_pool = 0.0
        ccr_adjustment = 0.0
        ccr_emissions_deviation = 0.0
        ccr_cost_deviation = 0.0
        effective_carry = carry_forward_allowances

        # ── CCR: adjust the per-period cap from lagged emissions / abatement
        # cost deviations (Benmir, Roman & Taschini 2025).  The adjustment is
        # injected as additional permit supply so the competitive clearing sees
        # the rule-adjusted cap Q_t = Qbar + ΔQ_t.
        ccr_active = ccr_state is not None and getattr(market, "ccr_enabled", False)
        if ccr_active:
            try:
                ccr_active = float(str(market.year)) >= float(
                    getattr(market, "ccr_start_year", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                pass  # non-numeric year labels: rule active
        if ccr_active:
            ccr_adjustment, ccr_emissions_deviation, ccr_cost_deviation = (
                ccr_state.cap_adjustment(
                    phi_emissions=float(getattr(market, "ccr_phi_emissions", 0.0)),
                    phi_abatement_cost=float(
                        getattr(market, "ccr_phi_abatement_cost", 0.0)
                    ),
                    reference_emissions=float(
                        getattr(market, "ccr_reference_emissions", 0.0)
                    ),
                    reference_abatement_cost=float(
                        getattr(market, "ccr_reference_abatement_cost", 0.0)
                    ),
                    year_label=str(market.year),
                )
            )
            effective_carry += ccr_adjustment

        msr_active = msr_state is not None and getattr(market, "msr_enabled", False)
        if msr_active:
            try:
                msr_active = float(str(market.year)) >= float(
                    getattr(market, "msr_start_year", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                pass  # non-numeric year labels: rule active
        if msr_active:
            total_bank = sum(bank_balances.values())
            _, msr_withheld, msr_released = msr_state.apply(
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
            msr_pool = msr_state.reserve_pool
            # Inject the MSR net adjustment as carry-forward so solve_equilibrium
            # sees it (released adds to supply, withheld subtracts; the adjusted
            # auction volume returned by apply() is deliberately unused).
            # Compose additively with any CCR cap adjustment already applied:
            #   Q_t = Qbar + ΔQ_t^CCR + ΔQ_t^MSR   (F1 fix, blocks-composition-rules §0)
            msr_net = msr_released - msr_withheld
            effective_carry += msr_net

        equilibrium = market.solve_equilibrium(
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
            carry_forward_in=effective_carry,
        )
        equilibrium_price = float(equilibrium["price"])
        participant_df = market.participant_results(
            equilibrium_price,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        )
        details.append(
            {
                "market": market,
                "expected_future_price": expected_future_price,
                "starting_bank_balances": starting_bank_balances,
                "equilibrium": equilibrium,
                "participant_df": participant_df,
                "msr_withheld": msr_withheld,
                "msr_released": msr_released,
                "msr_pool": msr_pool,
                "ccr_adjustment": ccr_adjustment,
                "ccr_emissions_deviation": ccr_emissions_deviation,
                "ccr_cost_deviation": ccr_cost_deviation,
            }
        )

        # ── CCR: record this year's realised aggregates as next year's signal
        if ccr_state is not None and getattr(market, "ccr_enabled", False):
            ccr_state.record(
                emissions=float(participant_df["Residual Emissions"].sum()),
                abatement_cost=float(participant_df["Abatement Cost"].sum()),
            )

        carry_forward_allowances = (
            float(equilibrium["unsold_allowances"])
            if market.unsold_treatment == "carry_forward"
            else 0.0
        )
        bank_balances = {
            str(row["Participant"]): float(row["Ending Bank Balance"])
            for _, row in participant_df.iterrows()
        }

    return details


def _collect_path_results(
    ordered_markets: list[CarbonMarket],
    path_details: list[dict],
    scenario_summaries: list,
    participant_frames: list,
) -> None:
    """Append results from a solved path into the accumulator lists."""
    for item in path_details:
        market = item["market"]
        expected_future_price = item["expected_future_price"]
        equilibrium = item["equilibrium"]
        equilibrium_price = float(equilibrium["price"])
        participant_df = item["participant_df"]
        summary = market.scenario_summary(
            equilibrium_price,
            expected_future_price=expected_future_price,
            auction_outcome=equilibrium,
            participant_df=participant_df,
        )
        # Patch in MSR stats from the simulation step
        summary["MSR Withheld"] = float(item.get("msr_withheld", 0.0))
        summary["MSR Released"] = float(item.get("msr_released", 0.0))
        summary["MSR Reserve Pool"] = float(item.get("msr_pool", 0.0))
        # Patch in CCR stats from the simulation step
        summary["CCR Cap Adjustment"] = float(item.get("ccr_adjustment", 0.0))
        summary["CCR Emissions Deviation"] = float(
            item.get("ccr_emissions_deviation", 0.0)
        )
        summary["CCR Cost Deviation"] = float(item.get("ccr_cost_deviation", 0.0))
        # Patch in banking-equilibrium diagnostics when present
        if "banking_aggregate_bank" in item:
            summary["Banking Aggregate Bank"] = float(item["banking_aggregate_bank"])
            summary["Banking Regime"] = str(item["banking_regime"])
            summary["Banking Window Start"] = int(item["banking_window_start"])
            summary["Banking Window End"] = int(item["banking_window_end"])
            summary["Banking Floor Cancelled"] = float(
                item["banking_floor_cancelled"]
            )
        # Patch in forward-transmission (λ-blend) diagnostics when present
        if "transmission_lambda" in item:
            summary["Forward Transmission Lambda"] = float(item["transmission_lambda"])
            summary["Static Component Price"] = float(item["static_component_price"])
            summary["Hotelling Component Price"] = float(
                item["hotelling_component_price"]
            )
            summary["Reserve Floor Price"] = float(item["reserve_floor_price"])
        scenario_summaries.append(summary)
        participant_frames.append(participant_df)


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
    from .hotelling import solve_hotelling_path
    from .nash import solve_nash_path

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
            from .transmission import solve_transmission_path

            path = solve_transmission_path(
                ordered_markets, lam=float(transmission_lambda), **_hot_kwargs()
            )
            _collect_path_results(ordered_markets, path, scenario_summaries, participant_frames)

        elif approach == "banking":
            from .banking import solve_banking_path

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
