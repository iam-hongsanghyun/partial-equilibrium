r"""Path-details ledger of the per-year simulation pipeline (T0 kernel).

Moved VERBATIM from ``solvers/simulation.py`` in the ledger work order
(``docs/feature-modules-plan.md`` §4 — v1 O7 / v2 O11 "ledger → kernel"):

* ``_simulate_path_details``  → ``simulate_path_details``
* ``_collect_path_results``   → ``collect_path_results``
* ``_market_year_sort_key``   → ``market_year_sort_key``

The underscore names remain importable from ``ets.solvers.simulation``
(re-exports; the flat ``ets.simulation`` shim resolves through them) until
the solvers compat surface retires.

SPLICE PIN (load-bearing, do not rename): the summary column names written
by ``collect_path_results`` — in particular ``"Banking Aggregate Bank"``
and ``"MSR Reserve Pool"`` — are read back by the policy-event splicer to
carry state across event segments; ``tests/test_policy_events.py`` pins
them byte-identically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .expectations import expectation_sort_key

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .market.model import CarbonMarket
    from .protocols import CapRule


def market_year_sort_key(market: CarbonMarket) -> tuple[float, str]:
    """Chronological sort key for a market's year label.

    Args:
        market: The market whose ``year`` label is keyed.

    Returns:
        The ``(numeric_year, label)`` tuple from ``expectation_sort_key``.
    """
    return expectation_sort_key(market.year)


def simulate_path_details(
    ordered_markets: list[CarbonMarket],
    expected_prices: dict[str, float],
    cap_rules: Sequence[CapRule] = (),
) -> list[dict]:
    """Simulate the competitive per-year path with injected cap rules.

    Supply operators (``CapRule``: CCR, MSR) act BEFORE each year's clearing
    and read only beginning-of-year state; after clearing they record
    realised aggregates as the next year's lagged signal (split gating —
    see ``ets.core.protocols.CapRule``). Composition is additive in list
    order (F1): ``effective_carry += delta_q_i``, CCR before MSR.

    The legacy ``msr_state=``/``ccr_state=`` kwargs (and their internal
    translation to rules) retired with the hotelling/nash feature move
    (v1 O11 / v2 O15): callers pass ``cap_rules`` explicitly — the engine
    wiring (``ets.engine.wiring.default_cap_rules``) builds today's default
    composition per approach.

    Args:
        ordered_markets: Markets sorted chronologically.
        expected_prices: Year label → expected future price [currency/tCO2].
        cap_rules: Cap rules applied in list order (wiring-literal order:
            CCR before MSR, F1). Default ``()`` is an explicitly rule-free
            path — behaviour-identical to the pre-retirement no-kwarg call
            (whose translation with no states also produced no rules).

    Returns:
        One details dict per year (market, equilibrium, participant frame,
        and the MSR/CCR diagnostics keys in their pinned order).
    """
    bank_balances = {
        participant.name: 0.0 for participant in ordered_markets[0].participants
    }
    carry_forward_allowances = 0.0
    details: list[dict] = []

    for market in ordered_markets:
        expected_future_price = float(expected_prices.get(str(market.year), 0.0))
        starting_bank_balances = dict(bank_balances)

        # ── Supply operators: cap rules adjust supply before clearing ─────
        # Zero-valued defaults in the pinned key order of the details dict
        # (golden baselines are column-order-sensitive).
        diagnostics: dict[str, float] = {
            "msr_withheld": 0.0,
            "msr_released": 0.0,
            "msr_pool": 0.0,
            "ccr_adjustment": 0.0,
            "ccr_emissions_deviation": 0.0,
            "ccr_cost_deviation": 0.0,
        }
        # Additive composition in wiring-literal order (CCR before MSR):
        #   Q_t = Qbar + ΔQ_t^CCR + ΔQ_t^MSR   (F1 fix, blocks-composition-rules §0)
        # Rules read only beginning-of-year state (previous bank; their own
        # lagged aggregates), never same-year outcomes.
        effective_carry = carry_forward_allowances
        for rule in cap_rules:
            delta_q, rule_diagnostics = rule.pre_clear(market, bank_balances)
            effective_carry += delta_q
            diagnostics.update(rule_diagnostics)

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
                "msr_withheld": diagnostics["msr_withheld"],
                "msr_released": diagnostics["msr_released"],
                "msr_pool": diagnostics["msr_pool"],
                "ccr_adjustment": diagnostics["ccr_adjustment"],
                "ccr_emissions_deviation": diagnostics["ccr_emissions_deviation"],
                "ccr_cost_deviation": diagnostics["ccr_cost_deviation"],
            }
        )

        # ── Post-clearing: rules record realised aggregates as the lagged
        # signal (flag-only gating — pre-start years accumulate history).
        for rule in cap_rules:
            rule.post_clear(market, participant_df)

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


def collect_path_results(
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
