"""banking plugin door — splice carrier for the policy-event segment host (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): field specs and attachable behaviour objects only; imports
``ets.core`` + stdlib. The banking runtime lives in this feature's
``window.py``/``solver.py``.
"""

from __future__ import annotations

from ...core.protocols import SpliceCarrier

# ── Splice-carrier declaration (binding Arbitration outcome on PLAN v2) ──────
# The aggregate bank is the banking solver's state variable and is ALWAYS
# carried across policy-event segments (predicate always-true) — physical
# state survives an announcement splice (``core.protocols.SpliceCarrier``;
# ``tests/test_policy_events.py`` pins the ordering). Defined in the engine
# literal at the engine order (v1 O8 / v2 O12) and moved to this plugin door
# with the banking feature move (v1 O9 / v2 O13). Consumed by the engine's
# segment host literal (``engine/events.py`` SPLICE_CARRIERS).
BANK_CARRIER = SpliceCarrier(
    column="Banking Aggregate Bank",
    config_field="banking_initial_bank",
    carry_if=lambda config: True,
)
