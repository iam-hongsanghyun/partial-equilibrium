from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ALLOWED_EXPECTATION_RULES = {
    "myopic",
    "next_year_baseline",
    "perfect_foresight",
    "manual",
}


@dataclass(frozen=True)
class ExpectationSpec:
    rule: str
    manual_price: float | None = None


def expectation_sort_key(year: str | None) -> tuple[float, str]:
    try:
        return (float(year), str(year))
    except (TypeError, ValueError):
        return (float("inf"), str(year))


def validate_expectation_rule(rule: str, year_label: str) -> str:
    normalized = str(rule).strip()
    if normalized not in ALLOWED_EXPECTATION_RULES:
        raise ValueError(
            f"Year '{year_label}' expectation_rule must be one of "
            f"{', '.join(sorted(ALLOWED_EXPECTATION_RULES))}."
        )
    return normalized


def build_expectation_specs(markets: Iterable) -> dict[str, ExpectationSpec]:
    specs: dict[str, ExpectationSpec] = {}
    for market in markets:
        specs[str(market.year)] = ExpectationSpec(
            rule=market.expectation_rule,
            manual_price=market.manual_expected_price,
        )
    return specs


def derive_expected_prices(
    ordered_years: list[str],
    specs: dict[str, ExpectationSpec],
    baseline_prices: dict[str, float],
    realized_prices: dict[str, float] | None = None,
) -> dict[str, float]:
    expected_prices: dict[str, float] = {}
    realized_prices = realized_prices or {}
    for index, year in enumerate(ordered_years):
        spec = specs[year]
        next_year = ordered_years[index + 1] if index + 1 < len(ordered_years) else None

        if spec.rule == "manual":
            expected_prices[year] = float(spec.manual_price or 0.0)
        elif spec.rule == "myopic":
            expected_prices[year] = 0.0
        elif spec.rule == "perfect_foresight":
            expected_prices[year] = (
                float(realized_prices[next_year])
                if next_year is not None and next_year in realized_prices
                else 0.0
            )
        else:
            expected_prices[year] = (
                float(baseline_prices.get(next_year, 0.0)) if next_year is not None else 0.0
            )
    return expected_prices
