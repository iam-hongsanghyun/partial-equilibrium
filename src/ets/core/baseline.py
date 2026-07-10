"""Baseline (no-banking) per-year equilibrium prices (T0 kernel).

``compute_baseline_prices`` relocated VERBATIM from ``ets/solvers/__init__.py``
in the shim-arming order (v1 O13 / v2 O17, ``docs/feature-modules-plan.md``):
it is kernel math (a per-year static clearing map with no solver state), and
its move makes the whole ``ets.solvers`` package a pure re-export shim. The
old import path (``ets.solvers.compute_baseline_prices``) keeps working via
that shim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .market import CarbonMarket


def compute_baseline_prices(markets: list[CarbonMarket]) -> dict[str, float]:
    """Compute baseline (no-banking) equilibrium price for each year."""
    return {str(market.year): market.find_equilibrium_price() for market in markets}
