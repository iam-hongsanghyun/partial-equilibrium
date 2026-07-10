# Backward-compatibility shim — re-exports from core.expectations.
# New location: src/ets/core/expectations.py.
# DeprecationWarning arms in O13 (milestone 0.3.0) — see
# docs/feature-modules-plan.md §4.

from ..core.expectations import (
    ALLOWED_EXPECTATION_RULES,
    ExpectationSpec,
    expectation_sort_key,
    validate_expectation_rule,
    build_expectation_specs,
    derive_expected_prices,
)

__all__ = [
    "ALLOWED_EXPECTATION_RULES",
    "ExpectationSpec",
    "expectation_sort_key",
    "validate_expectation_rule",
    "build_expectation_specs",
    "derive_expected_prices",
]
