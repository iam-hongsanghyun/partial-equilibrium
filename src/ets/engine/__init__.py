"""Composition engine (T3) — the sole importer of the feature tier.

Solve dispatch (``dispatch.py``), policy-event splicing (``events.py``), and
default rule wiring (``wiring.py``), per ``docs/feature-modules-plan.md`` §1
(tier table) and §2 (target tree). Created in the engine work order (v1 O8 /
v2 O12); ``ets/solvers/simulation.py`` and ``ets/solvers/events.py``
re-export the entry points so every old import path keeps working.
"""

from .dispatch import (
    run_simulation,
    run_simulation_from_config,
    run_simulation_from_file,
)
from .events import solve_scenario_with_events, validate_policy_events
from .wiring import (
    default_cap_rules,
    default_floor_rule_factory,
    default_friction,
    default_supply_rule_factories,
    solve_banking_path,
    solve_hotelling_path,
    solve_nash_path,
    solve_scenario_path,
    solve_transmission_path,
)

__all__ = [
    "default_cap_rules",
    "default_floor_rule_factory",
    "default_friction",
    "default_supply_rule_factories",
    "run_simulation",
    "run_simulation_from_config",
    "run_simulation_from_file",
    "solve_banking_path",
    "solve_hotelling_path",
    "solve_nash_path",
    "solve_scenario_path",
    "solve_scenario_with_events",
    "solve_transmission_path",
    "validate_policy_events",
]
