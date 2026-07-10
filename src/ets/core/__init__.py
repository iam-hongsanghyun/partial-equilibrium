"""T0 kernel of the ETS package (docs/feature-modules-plan.md §1).

Market primitives, participant model, costs, expectations, ledger, rule
protocols, policy defaults, paths, and logging live here. Kernel modules
import only the stdlib, third-party packages, and ``ets.core.*`` — enforced
by ``tests/test_module_isolation.py``.

The public surface grows as migration work orders land; import the
submodules directly (e.g. ``ets.core.defaults``).
"""
