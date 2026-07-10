r"""Policy-event timeline: announcement-dated rule changes with re-solving.

Motivation (K-MSR working paper, Sections 4–5): announcement and execution of
a rule are different events, and which one moves the price depends on the
market's forward-transmission capacity. Under full arbitrage (banking, λ → 1)
the price responds at ANNOUNCEMENT — everything known is priced immediately
and nothing happens at execution. In a λ ≈ 0 market the price responds at
EXECUTION only — pre-announced events land as if they were news.

Rule *content* effective from year Y is expressible with per-year fields
(floors, cancellations) or ``msr_start_year`` / ``ccr_start_year``; but a
forward-looking solver still knows those rules from the first year. This
module adds the missing object: **information timing**. A policy event is a
dated config change the solver does not know about before its announcement
year:

    "policy_events": [
      {
        "announced": "2031",
        "changes":        { ...scenario-level fields... },
        "year_overrides": { "2031": {"cancelled_allowances": 16.0}, ... }
      }
    ]

Algorithm
---------
ASCII:
    segments = horizon split at each announcement year
    state    = (aggregate bank, MSR reserve pool) carried across splices
    for each segment, in order:
        config  = base + all events announced <= segment start
        solve the FULL REMAINING horizon from the segment start
        keep only the segment's years; inherit end-of-segment state

Each announcement therefore triggers a re-solve of the remaining horizon with
an expanded information set — the standard way to model policy surprises
(cf. Perino & Willner's reform-timing experiments; the late-2018 EUA
repricing in Kollenberg & Taschini 2019).

State carried across splices: ``banking_initial_bank`` (the aggregate bank at
the end of the pre-splice year) and ``msr_initial_reserve_mt`` (the decree
reserve pool). Participant-level bank balances are NOT carried — under the
banking approach the aggregate bank is the solver's state variable; under the
competitive approach nothing is carried (each year clears independently, so
an announcement without same-year execution changes nothing — which is
precisely the λ ≈ 0 result this module lets you demonstrate).
"""

from __future__ import annotations

import logging
import math
from copy import deepcopy

import pandas as pd

from ..core.protocols import SpliceCarrier
from ..features.banking.plugin import BANK_CARRIER
from ..features.msr.plugin import RESERVE_CARRIER

logger = logging.getLogger(__name__)


# ── SpliceCarrier wiring literal (binding Arbitration outcome on PLAN v2) ────
# Declarative form of the two state variables carried across event segments:
#
#   1. the aggregate bank — ALWAYS carried (predicate always-true). Provided
#      by the banking feature's plugin door (``features/banking/plugin.py``
#      since the banking move, v1 O9 / v2 O13).
#   2. the MSR reserve pool — carried only when the MSR ran in the finished
#      segment (the ``msr_ran_last_segment`` condition; a decree announced
#      mid-horizon with a pre-funded reserve keeps its funding). Provided by
#      the MSR feature's plugin door (``features/msr/plugin.py``).
#
# The solve loop below keeps its inline reads and stamps VERBATIM — the
# pre-funded-decree ordering is pinned by tests/test_policy_events.py and
# behaviour preservation outranks protocol purity (Arbitration outcomes);
# this literal is the reviewed declaration those inline lines implement.
# Literal order is stamp order (bank first, then the reserve pool).
SPLICE_CARRIERS: tuple[SpliceCarrier, ...] = (BANK_CARRIER, RESERVE_CARRIER)


def _year_num(label: object) -> float:
    try:
        return float(str(label))
    except (TypeError, ValueError):
        return math.nan


def validate_policy_events(scenario: dict) -> list[dict]:
    """Validate and chronologically sort a scenario's policy events.

    Args:
        scenario: Normalized scenario dict (must contain ``years``).

    Returns:
        Sorted list of event dicts (possibly empty).

    Raises:
        ValueError: On a malformed event or an announcement year outside the
            scenario horizon.
    """
    events = scenario.get("policy_events") or []
    if not events:
        return []
    year_labels = {str(y["year"]) for y in scenario.get("years", [])}
    validated = []
    for event in events:
        if not isinstance(event, dict) or "announced" not in event:
            raise ValueError(
                f"Scenario '{scenario.get('name')}': each policy event must be "
                "a dict with an 'announced' year."
            )
        announced = str(event["announced"])
        if announced not in year_labels:
            raise ValueError(
                f"Scenario '{scenario.get('name')}': policy event announced in "
                f"'{announced}', which is not a year of the scenario."
            )
        changes = event.get("changes") or {}
        year_overrides = event.get("year_overrides") or {}
        if not isinstance(changes, dict) or not isinstance(year_overrides, dict):
            raise ValueError(
                f"Scenario '{scenario.get('name')}': policy event 'changes' and "
                "'year_overrides' must be dicts."
            )
        unknown = set(year_overrides) - year_labels
        if unknown:
            raise ValueError(
                f"Scenario '{scenario.get('name')}': year_overrides for unknown "
                f"years {sorted(unknown)}."
            )
        validated.append(
            {"announced": announced, "changes": changes, "year_overrides": year_overrides}
        )
    validated.sort(key=lambda e: _year_num(e["announced"]))
    return validated


def solve_scenario_with_events(
    scenario: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Solve a scenario whose config changes at announcement dates.

    See the module docstring for semantics. The scenario is solved segment by
    segment; each segment solves the full remaining horizon (so
    forward-looking approaches price the newly announced rules immediately)
    and keeps only the years before the next announcement.

    Args:
        scenario: Normalized scenario dict containing ``policy_events``.

    Returns:
        ``(summary_df, participant_df)`` spliced across segments, same shape
        as ``run_simulation`` output.
    """
    # Lazy imports to avoid circularity (dispatch → events → dispatch).
    from ..config_io import build_markets_from_config
    from .dispatch import run_simulation

    events = validate_policy_events(scenario)
    current = deepcopy(scenario)
    current.pop("policy_events", None)

    carried_bank = float(current.get("banking_initial_bank") or 0.0)
    carried_pool = float(current.get("msr_initial_reserve_mt") or 0.0)

    pending = list(events)
    seg_start = min(_year_num(y["year"]) for y in current["years"])
    summary_frames: list[pd.DataFrame] = []
    participant_frames: list[pd.DataFrame] = []

    while True:
        # The reserve pool is only a *carried* state if the rule ran in the
        # previous segment; a decree announced with a pre-funded reserve
        # (msr_initial_reserve_mt in its changes) must keep that funding.
        msr_ran_last_segment = bool(current.get("msr_enabled"))

        while pending and _year_num(pending[0]["announced"]) <= seg_start:
            event = pending.pop(0)
            current.update(event["changes"])
            for year in current["years"]:
                if str(year["year"]) in event["year_overrides"]:
                    year.update(event["year_overrides"][str(year["year"])])
            logger.debug(
                f"Policy event announced {event['announced']}: applied "
                f"{sorted(event['changes'])} + year overrides for "
                f"{sorted(event['year_overrides'])}."
            )

        seg_end = _year_num(pending[0]["announced"]) if pending else math.inf

        seg_scenario = deepcopy(current)
        seg_scenario["banking_initial_bank"] = carried_bank
        if msr_ran_last_segment:
            seg_scenario["msr_initial_reserve_mt"] = carried_pool
        seg_scenario["years"] = [
            y for y in seg_scenario["years"] if _year_num(y["year"]) >= seg_start
        ]
        summary, participants = run_simulation(
            build_markets_from_config({"scenarios": [seg_scenario]})
        )

        year_nums = summary["Year"].map(_year_num)
        keep = summary[year_nums < seg_end]
        p_year_nums = participants["Year"].map(_year_num)
        participant_frames.append(participants[p_year_nums < seg_end])
        summary_frames.append(keep)

        if not pending:
            break

        last = keep.iloc[-1]
        if "Banking Aggregate Bank" in keep.columns and pd.notna(
            last["Banking Aggregate Bank"]
        ):
            carried_bank = float(last["Banking Aggregate Bank"])
        if "MSR Reserve Pool" in keep.columns and pd.notna(last["MSR Reserve Pool"]):
            carried_pool = float(last["MSR Reserve Pool"])
        seg_start = seg_end

    return (
        pd.concat(summary_frames, ignore_index=True),
        pd.concat(participant_frames, ignore_index=True),
    )
