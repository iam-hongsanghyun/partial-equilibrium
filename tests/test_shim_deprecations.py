"""Deprecation-shim sweep (v1 O13 / v2 O17 — shim arming).

Two invariants, both fast (no solving, imports only):

1. EVERY backward-compatibility shim fires its own ``DeprecationWarning``
   exactly once per (re-)import, naming the canonical new location — the
   arming contract of the app-tier tidy order.
2. The supported import surface stays WARNING-CLEAN: ``import ets``,
   ``ets.engine``, ``ets.core``, ``ets.config_io``, ``ets.blocks``, and the
   Vercel chain ``ets.web.server`` must never traverse a warning shim
   (checked in a fresh interpreter with ``-W error::DeprecationWarning``,
   because this process has already imported and cached everything).

A shim's module body executes once per import, so re-firing its warning
requires evicting it from ``sys.modules`` and re-importing; parent packages
stay cached, so each check observes ONLY the target module's warning.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import warnings

import pytest

# shim module -> a phrase its warning must contain (the canonical new home).
SHIM_WARNINGS: dict[str, str] = {
    # flat shims (pre-existing, retargeted where the canonical home moved)
    "ets.simulation": "ets.engine",
    "ets.msr": "ets.features.msr",
    "ets.ccr": "ets.features.ccr",
    "ets.hotelling": "ets.engine",
    "ets.nash": "ets.engine",
    "ets.expectations": "ets.core.expectations",
    "ets.scenarios": "ets.config_io",
    "ets.server": "ets.web.server",
    "ets.webapp": "ets.web.handlers",
    "ets.config": "ets.core.paths",
    "ets.costs": "ets.core.costs",
    # shim packages
    "ets.market": "ets.core.market",
    "ets.market.core": "ets.core.market.model",
    "ets.market.equilibrium": "ets.core.market.clearing",
    "ets.market.results": "ets.core.market.reporting",
    "ets.participant": "ets.core.participant",
    "ets.participant.models": "ets.core.participant.models",
    "ets.participant.compliance": "ets.core.participant.compliance",
    "ets.participant.technology": "ets.core.participant.technology",
    # solvers tier (all pure shims since v1 O12-O13 / v2 O16-O17)
    "ets.solvers": "ets.engine",
    "ets.solvers.simulation": "ets.engine",
    "ets.solvers.banking": "ets.engine",
    "ets.solvers.hotelling": "ets.engine",
    "ets.solvers.nash": "ets.engine",
    "ets.solvers.transmission": "ets.engine",
    "ets.solvers.msr": "ets.features.msr",
    "ets.solvers.ccr": "ets.features.ccr",
    "ets.solvers.events": "ets.engine",
    "ets.solvers.expectations": "ets.core.expectations",
}

# The supported (non-shim) import surface that must stay warning-clean —
# includes the Vercel serving chain (api/index.py -> ets.web.server).
CLEAN_IMPORTS = (
    "ets",
    "ets.engine",
    "ets.core",
    "ets.config_io",
    "ets.blocks",
    "ets.web.server",
    "ets.coupling",
    "ets.analysis.batch",
    "ets.cli",
)


@pytest.mark.parametrize("module_name", sorted(SHIM_WARNINGS))
def test_shim_fires_its_deprecation_warning_exactly_once(module_name: str) -> None:
    """Re-importing a shim fires exactly one warning with the right text."""
    sys.modules.pop(module_name, None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module(module_name)

    own = [
        w
        for w in caught
        if issubclass(w.category, DeprecationWarning)
        and str(w.message).startswith(f"{module_name} is deprecated")
    ]
    assert len(own) == 1, (
        f"{module_name}: expected exactly one of its own DeprecationWarnings, "
        f"got {len(own)}: {[str(w.message) for w in caught]}"
    )
    message = str(own[0].message)
    assert SHIM_WARNINGS[module_name] in message, (
        f"{module_name}: warning must name the canonical home "
        f"{SHIM_WARNINGS[module_name]!r}; got: {message}"
    )
    assert "milestone" in message.lower(), (
        f"{module_name}: warning must state the removal milestone; got: {message}"
    )


def test_supported_import_surface_is_warning_clean() -> None:
    """The canonical import chains never traverse a warning shim.

    Runs in a fresh interpreter (this process has cached, already-warned
    modules) with DeprecationWarning escalated to an error — the Vercel path
    (api/index.py imports ets.web.server) is part of the chain.
    """
    code = "; ".join(f"import {m}" for m in CLEAN_IMPORTS)
    result = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "canonical import surface raised under -W error::DeprecationWarning:\n"
        f"{result.stderr}"
    )
