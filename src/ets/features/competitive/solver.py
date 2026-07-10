"""Competitive per-year path solver (T2 runtime, engine/host-facing).

``solve_scenario_path`` and its perfect-foresight helper
``_simulate_realized_prices`` moved VERBATIM from ``solvers/simulation.py``
in the competitive feature order (v1 O10 / v2 O14,
``docs/feature-modules-plan.md``), with the cap rules INJECTED (plan §2
"competitive/solver.py ← solve_scenario_path, _simulate_realized_prices
(+cap_rules)"): the engine-bound entry point
(``ets.engine.wiring.solve_scenario_path``, exported as
``ets.engine.solve_scenario_path``) constructs today's default rules from
the first market's flags (CCR before MSR, F1) and passes them in — this
feature imports only the kernel. ``ets/solvers/simulation.py`` remains as a
re-export shim of the engine-bound name.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...core.expectations import (
    build_expectation_specs,
    derive_expected_prices,
)
from ...core.ledger import simulate_path_details

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...core.market import CarbonMarket
    from ...core.protocols import CapRule

logger = logging.getLogger(__name__)


def solve_scenario_path(
    ordered_markets: list[CarbonMarket],
    max_iterations: int | None = None,
    tolerance: float | None = None,
    cap_rules: Sequence[CapRule] = (),
) -> list[dict]:
    """Solve the competitive per-year path with injected cap rules.

    Args:
        ordered_markets: Markets sorted chronologically.
        max_iterations: Perfect-foresight fixed-point iteration cap; ``None``
            reads the first market's solver settings.
        tolerance: Perfect-foresight price-convergence tolerance
            [currency/tCO2]; ``None`` reads the first market's settings.
        cap_rules: Cap rules applied on the FINAL path in list order
            (``core.protocols.CapRule``; CCR before MSR, F1). Injected by
            the engine-bound entry point from the scenario flags; the
            perfect-foresight inner loop stays rule-free regardless (R29).
            Default ``()`` solves a rule-free path.

    Returns:
        Path details from ``core.ledger.simulate_path_details``.
    """
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

    return simulate_path_details(
        ordered_markets,
        expected_prices,
        cap_rules=cap_rules,
    )


def _simulate_realized_prices(
    ordered_markets: list[CarbonMarket],
    expected_prices: dict[str, float],
) -> dict[str, float]:
    # MSR / CCR are NOT applied in the inner convergence loop (prices only):
    # perfect-foresight expectations are formed on the RULE-FREE path (R29,
    # docs/blocks-composition-rules.md), hence the explicit empty rule list.
    details = simulate_path_details(ordered_markets, expected_prices, cap_rules=())
    return {
        str(item["market"].year): float(item["equilibrium"]["price"])
        for item in details
    }
