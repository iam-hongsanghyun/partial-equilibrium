"""Lazy, per-model feature activation (owner directive: ACTIVATION, not just layout).

Structurally the backend was already modular — isolated ``features/``
packages, an AST-enforced import-tier ratchet
(``tests/test_module_isolation.py``). ACTIVATION was not: importing
``ets.engine`` (or serving a single request) eagerly imported EVERY
feature's runtime solver/rule module regardless of the model actually being
solved, for two compounding reasons:

1. ``ets.engine.wiring`` imported every ``features.*.solver`` and every
   flag-gated rule class (``MSRCapRule``, ``CCRCapRule``,
   ``DecreeSupplyRule``, ``ThresholdMSRSupplyRule``) at MODULE scope, so
   merely importing ``ets.engine.wiring`` — which every scenario's dispatch
   does, regardless of ``model_approach`` — pulled in the competitive,
   banking, hotelling, Nash, and transmission solvers together.
2. The two-door features (``banking``, ``msr``, ``ccr``) executed their
   runtime submodules from their own package ``__init__.py``. Python always
   runs a package's ``__init__.py`` before any of its submodules, so
   importing just the always-eager config door (``ets.config_io`` imports
   ``ccr.plugin``/``msr.plugin``; ``ets.engine.events`` imports
   ``banking.plugin``/``msr.plugin`` for the ``SpliceCarrier`` literals —
   both are PLUGIN DOORS and correctly stay eager) dragged the RUNTIME
   (``rules.py``/``state.py``/``decree.py``/``solver.py``/``window.py``) in
   as a side effect of that import, not of solving anything.

The fix (this branch): every ``features.*`` runtime import in
``ets.engine.wiring`` moved to function-local scope, inside the branch
gated by the enable flag or approach that needs it; ``features.banking``,
``features.msr``, and ``features.ccr`` resolve their public surface lazily
via a PEP 562 module ``__getattr__`` instead of importing it at
package-init time. Plugin doors (``*.plugin`` — the config/reporting
contract ``config_io`` and ``engine.events`` read) are deliberately
UNCHANGED and stay eager; this suite asserts they may load without pulling
their sibling runtime module with them.

Algorithm:
    Not a numerical algorithm — a process-boundary system test. Imports are
    cached process-wide (``sys.modules``), so only a FRESH interpreter
    observes true first-import behaviour. For each case:
        1. Spawn ``sys.executable -c <code>`` running the scenario/import
           under test.
        2. Have the child process print every ``ets.features.*`` key of
           ``sys.modules`` (one per line) after it finishes.
        3. Parse the child's stdout into a set and assert it against the
           case's must-load / must-not-load partition of
           ``_ALL_RUNTIME_MODULES`` (``_assert_only``) — nothing here is a
           per-case special rule; every case checks the SAME universe of
           runtime modules, only the "loaded" partition changes.

References:
    ``docs/feature-modules-plan.md`` §1 (tier table; a lazy
    ``engine -> features`` import inside a function body is still the same
    T3->T2 edge the AST ratchet in ``tests/test_module_isolation.py``
    counts — activation scoping does not touch the import CONTRACT, only
    its EAGERNESS).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"

# The complete universe of feature RUNTIME modules this suite polices: the
# five approach solvers, the MSR/CCR rule runtimes (split by file, since
# `msr.decree` and `msr.state`/`ccr.state` are independently reachable), and
# banking's two attach-always injected siblings (hoarding's reader, the
# floor-cancellation rule) — none of these is a `plugin` config door, so
# none of them may load except when a scenario actually exercises the
# approach/flag that wires it in.
_ALL_RUNTIME_MODULES: frozenset[str] = frozenset(
    {
        "ets.features.banking.solver",
        "ets.features.banking.window",
        "ets.features.competitive.solver",
        "ets.features.hotelling.solver",
        "ets.features.nash_cournot.solver",
        "ets.features.transmission.solver",
        "ets.features.msr.rules",
        "ets.features.msr.decree",
        "ets.features.msr.state",
        "ets.features.ccr.rules",
        "ets.features.ccr.state",
        "ets.features.hoarding.plugin",
        "ets.features.price_controls.rules",
    }
)


def _feature_modules_loaded(code: str) -> frozenset[str]:
    """Run ``code`` in a fresh interpreter; return the ``ets.features.*`` it loaded.

    Spawns a subprocess (``sys.executable``, the current venv's interpreter
    — ``ets`` is installed editable so no ``PYTHONPATH`` massaging is
    needed) because ``sys.modules`` in THIS process already has everything
    cached from collection/earlier tests; only a fresh process observes
    which modules a given import/call graph actually touches.

    Args:
        code: A ``python -c`` program body. Must not print anything of its
            own — this helper appends the ``sys.modules`` dump statement.

    Returns:
        Every ``ets.features.*`` dotted module name present in
        ``sys.modules`` after ``code`` runs, one per line of the child's
        stdout.
    """
    program = (
        f"{code}\n"
        "import sys\n"
        "print('\\n'.join(sorted(m for m in sys.modules "
        "if m.startswith('ets.features'))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"subprocess failed (rc={result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return frozenset(line for line in result.stdout.splitlines() if line)


def _run_example_code(scenario_filename: str) -> str:
    """Return the ``python -c`` body that solves one ``examples/*.json`` scenario.

    Args:
        scenario_filename: File name under ``examples/`` (e.g.
            ``"climate_solutions_basic_linear.json"``).

    Returns:
        Source solving the scenario via ``ets.engine.run_simulation_from_file``
        — the entry point named in the owner directive.
    """
    config_path = EXAMPLES_DIR / scenario_filename
    assert config_path.exists(), f"example scenario missing: {config_path}"
    return (
        "from ets.engine import run_simulation_from_file\n"
        f"run_simulation_from_file(r{str(config_path)!r})\n"
    )


def _assert_only(loaded: frozenset[str], *, present: set[str]) -> None:
    """Assert exactly ``present`` (of ``_ALL_RUNTIME_MODULES``) loaded, nothing else.

    Args:
        loaded: The child process's full ``ets.features.*`` module set.
        present: The subset of ``_ALL_RUNTIME_MODULES`` this case expects to
            have loaded (possibly empty).
    """
    missing = present - loaded
    assert not missing, (
        f"expected runtime module(s) did not load: {sorted(missing)} "
        f"(loaded: {sorted(loaded)})"
    )
    forbidden = _ALL_RUNTIME_MODULES - present
    hit = loaded & forbidden
    assert not hit, f"unexpected feature runtime module(s) loaded: {sorted(hit)}"


def test_competitive_only_activates_only_the_competitive_solver() -> None:
    """A competitive-only scenario loads ``features.competitive.solver`` and
    nothing else in ``_ALL_RUNTIME_MODULES`` — not banking, hotelling, Nash,
    transmission, nor the (unconfigured) MSR/CCR rule runtimes.
    """
    loaded = _feature_modules_loaded(
        _run_example_code("climate_solutions_basic_linear.json")
    )
    _assert_only(loaded, present={"ets.features.competitive.solver"})


def test_banking_activates_the_banking_solver_not_hotelling() -> None:
    """A banking scenario (structural hoarding, MSR/CCR unconfigured) loads
    ``features.banking.{solver,window}`` and its two attach-always injected
    siblings (hoarding's reader, floor-cancellation) — but NOT
    ``features.hotelling.solver``: banking's endogenous-window regime
    search (``features/banking/window.py``, ``scipy.optimize.brentq`` on a
    closed-form observable) is pure kernel + same-feature math, never a
    cross-feature call into the Hotelling solver, despite both computing an
    exhaustible-resource-style price ramp.
    """
    loaded = _feature_modules_loaded(_run_example_code("k_ets_hoarding_basic.json"))
    _assert_only(
        loaded,
        present={
            "ets.features.banking.solver",
            "ets.features.banking.window",
            "ets.features.hoarding.plugin",
            "ets.features.price_controls.rules",
        },
    )


def test_import_ets_alone_activates_no_feature_runtime() -> None:
    """``import ets`` alone loads no feature runtime module whatsoever.

    ``ets/__init__.py`` imports ``ets.engine`` (for ``run_simulation`` et
    al.), which imports ``ets.engine.events`` (for the policy-event
    splicer), whose ``SpliceCarrier`` literals eagerly import
    ``features.banking.plugin`` and ``features.msr.plugin`` — plugin doors,
    correctly eager — and ``ets.engine.dispatch`` imports ``ets.config_io``,
    whose builder eagerly imports six features' ``plugin`` doors (cbam,
    ccr, elastic_baseline, msr, oba, sectors) plus
    ``price_controls.plugin`` for the trajectory arms — all config/reporting
    contract surface, correctly eager. None of that is a runtime module.
    """
    loaded = _feature_modules_loaded("import ets\n")
    _assert_only(loaded, present=set())
