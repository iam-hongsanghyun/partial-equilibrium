# Backward-compatibility shim — re-exports from core.expectations.
# New location: src/ets/core/expectations.py.
import warnings

from ..core.expectations import (
    ALLOWED_EXPECTATION_RULES,
    ExpectationSpec,
    expectation_sort_key,
    validate_expectation_rule,
    build_expectation_specs,
    derive_expected_prices,
)

warnings.warn(
    "ets.solvers.expectations is deprecated; import from "
    "ets.core.expectations instead. Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "ALLOWED_EXPECTATION_RULES",
    "ExpectationSpec",
    "expectation_sort_key",
    "validate_expectation_rule",
    "build_expectation_specs",
    "derive_expected_prices",
]
