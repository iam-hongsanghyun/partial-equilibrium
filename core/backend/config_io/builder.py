from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from ..core.costs import linear_abatement_factory, piecewise_abatement_factory
from ..core.participant import MarketParticipant, TechnologyOption
from ..core.market import CarbonMarket
from ..core.protocols import AdoptionSpec
from ..features.cbam.plugin import (
    CBAMParticipantReporter,
    CBAMSummaryAggregatesReporter,
    CBAMSummaryTotalsReporter,
)
from ..features.ccr.plugin import CCRSummaryPlaceholderReporter
from ..features.elastic_baseline.plugin import stamp_and_attach as _elastic_stamp_and_attach
from ..features.endogenous_investment.plugin import (
    attach_adoption_specs as _attach_adoption_specs,
    normalize_investment_trigger as _normalize_investment_trigger,
)
from ..features.market_links.plugin import validate_links
from ..features.msr.plugin import MSRSummaryPlaceholderReporter
from ..features.oba.plugin import OBABenchmarkAllocation
from ..features.price_controls.plugin import apply_price_bound_trajectories
from ..features.sectors.plugin import (
    SectorPoolAllocation,
    SectorSummaryReporter,
    derive_sector_pools,
)
from .normalize import (
    ALLOWED_MODEL_APPROACHES,
    normalize_year,
)
from .templates import blank_scenario, blank_year_config

if TYPE_CHECKING:
    from ..core.protocols import ParticipantReporter, SummaryReporter

# ── Reporting plugin attachment (PLAN v2 "Two-door features"; Arbitration ──
# outcomes O7): reviewed source literals composed here (never via registry
# mutation) and attached to every ``CarbonMarket`` at its single
# construction site, ``build_market_from_year`` below. Stage order
# reproduces the pre-refactor ``core/market/reporting.py`` interleave
# EXACTLY (participant reporters have only one member today; the two
# summary stages straddle the host's mid-dict "Year" insertion).
_PARTICIPANT_REPORTERS: tuple["ParticipantReporter", ...] = (CBAMParticipantReporter(),)
_SUMMARY_REPORTERS_PRE_YEAR: tuple["SummaryReporter", ...] = (
    CBAMSummaryAggregatesReporter(),
    MSRSummaryPlaceholderReporter(),
    CCRSummaryPlaceholderReporter(),
)
_SUMMARY_REPORTERS_POST_YEAR: tuple["SummaryReporter", ...] = (
    CBAMSummaryTotalsReporter(),
    SectorSummaryReporter(),
)


def _normalize_trajectory(raw: Any) -> dict:
    """Normalise a cap/price trajectory object, returning {} if empty/missing."""
    if not raw or not isinstance(raw, dict):
        return {}
    out: dict = {}
    for k in ("start_year", "end_year"):
        if raw.get(k) is not None:
            out[k] = str(raw[k])
    for k in ("start_value", "end_value"):
        try:
            out[k] = float(raw[k])
        except (KeyError, TypeError, ValueError):
            pass
    # Must have all four keys to be valid
    if not all(k in out for k in ("start_year", "end_year", "start_value", "end_value")):
        return {}
    return out


def _year_to_float(year_label: str) -> float:
    try:
        return float(year_label)
    except (TypeError, ValueError):
        return 0.0


def _interp_value(year_num: float, traj: dict) -> float | None:
    """Linearly interpolate a scalar value trajectory, or return None if disabled."""
    if not traj:
        return None
    t_start = _year_to_float(str(traj.get("start_year", "")))
    t_end   = _year_to_float(str(traj.get("end_year", "")))
    v_start = float(traj.get("start_value", 0.0))
    v_end   = float(traj.get("end_value", 0.0))
    if t_end <= t_start:
        return None
    if year_num <= t_start:
        return v_start
    if year_num >= t_end:
        return v_end
    frac = (year_num - t_start) / (t_end - t_start)
    return round(v_start + frac * (v_end - v_start), 6)


def _interp_ratio(year_num: float, traj: dict) -> float | None:
    """Return linearly interpolated free_allocation_ratio for a trajectory, or None."""
    t_start = _year_to_float(str(traj.get("start_year", "")))
    t_end   = _year_to_float(str(traj.get("end_year", "")))
    r_start = float(traj.get("start_ratio", 0.0) or 0.0)
    r_end   = float(traj.get("end_ratio",   0.0) or 0.0)
    if t_end <= t_start:
        return None
    if year_num <= t_start:
        return r_start
    if year_num >= t_end:
        return r_end
    frac = (year_num - t_start) / (t_end - t_start)
    return round(r_start + frac * (r_end - r_start), 6)


# ── Per-participant preparation pipeline (PLAN v2 O9; Arbitration outcomes) ──
# `ParticipantTransform` steps run in this EXACT order against every raw
# participant dict, before `MarketParticipant` objects are built, so
# dataclass validation sees final values: sector-pool allocation -> trajectory
# patch (host-generic) -> OBA. The order is load-bearing and pinned by
# `tests/test_builder_pipeline.py`, not just this literal: OBA reads the
# trajectory-PATCHED `initial_emissions` (it must run after the trajectory
# patch), and OBA's write to `free_allocation_ratio` OVERWRITES whatever the
# sectors step wrote for the same participant — a documented cross-feature
# coupling through the raw-dict medium (precedence OBA > sector > per-year).


def _patch_trajectories(
    raw: dict[str, Any], year_num: float, meta: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply ``initial_emissions_trajectory`` / ``grid_emission_factor_trajectory``.

    Algorithm:
        ASCII:
            initial_emissions    = interp(year_num, initial_emissions_trajectory)
                                    or unchanged
            grid_emission_factor = interp(year_num, grid_emission_factor_trajectory)
                                    or unchanged

    HOST-GENERIC (Arbitration outcomes, O9): every participant may carry
    either trajectory regardless of sector/OBA configuration — this is not
    feature economics, so it stays a builder-local function between the
    sectors and OBA transforms in ``_PARTICIPANT_TRANSFORMS``, rather than
    moving into a feature plugin. Declared fields: reads
    ``initial_emissions_trajectory``, ``grid_emission_factor_trajectory``;
    writes ``initial_emissions``, ``grid_emission_factor``.

    Args:
        raw: The participant's raw config dict for this year. Not mutated.
        year_num: Numeric scenario year, used by ``_interp_value``.
        meta: Unused; accepted for the pipeline's uniform call signature
            (matches ``core.protocols.ParticipantTransform.apply``).

    Returns:
        A new dict — always a shallow copy, even when neither trajectory is
        configured (the original loop's unconditional ``dict(p)``).
    """
    p = dict(raw)  # shallow copy to avoid mutating caller's data
    ie_traj = p.get("initial_emissions_trajectory") or {}
    if ie_traj:
        overridden = _interp_value(year_num, ie_traj)
        if overridden is not None:
            p["initial_emissions"] = max(0.0, overridden)
    gef_traj = p.get("grid_emission_factor_trajectory") or {}
    if gef_traj:
        overridden = _interp_value(year_num, gef_traj)
        if overridden is not None:
            p["grid_emission_factor"] = max(0.0, overridden)
    return p


_ParticipantTransformStep: TypeAlias = Callable[
    [dict[str, Any], float, Mapping[str, Any]], dict[str, Any]
]

_PARTICIPANT_TRANSFORMS: tuple[_ParticipantTransformStep, ...] = (
    SectorPoolAllocation().apply,
    _patch_trajectories,
    OBABenchmarkAllocation().apply,
)


def _normalize_sectors(raw_sectors: list) -> list:
    """Normalize and validate a list of sector objects."""
    if not raw_sectors:
        return []
    normalized = []
    for s in raw_sectors:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or "").strip()
        if not name:
            raise ValueError("Each sector must have a non-empty name.")
        normalized.append({
            "name": name,
            "cap_trajectory": _normalize_trajectory(s.get("cap_trajectory")),
            "auction_share_trajectory": _normalize_trajectory(s.get("auction_share_trajectory")),
            "carbon_budget": float(s.get("carbon_budget") or 0.0),
        })
    return normalized


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list):
        raise ValueError("Config must contain a 'scenarios' list.")
    return {"scenarios": [normalize_scenario(scenario) for scenario in scenarios]}


_ALLOWED_MSR_MODES = {"bank_threshold", "price_band", "surplus_rule", "hybrid"}

# D2 joint-solver outer-loop defaults (docs/joint-equilibrium-plan.md §4). MIRRORS
# ``pe.engine.joint.JOINT_DEFAULTS`` as bare literals — config_io (T1) may not
# import the engine (T3), so this is duplicated here exactly as ``validate.py``
# mirrors the link-channel whitelist under its own dependency law. The one
# source of truth for the RUNTIME defaults is still ``engine.joint``; this block
# only normalizes what a scenario DECLARES, and dispatch passes ``None`` for any
# absent setting so the engine's own default applies (the D1 COMPAT RULE: an
# absent ``joint_solver`` block means "no joint solver declared", never an
# injected default — the whole key is omitted from the normalized document).
_JOINT_SOLVER_DEFAULTS: dict[str, Any] = {
    # w — relaxation weight [dimensionless], (0, 1]; 0.5 damps the oscillatory band.
    "relaxation": 0.5,
    # per-market relative (dimensionless) convergence tolerance (§5 default 1e-4).
    "tolerance": 1e-4,
    # outer-sweep cap; the banking-cyclic worst-case rail (§6 V-D2-8: ~50 for ρ≈0.83).
    "max_iterations": 50,
    # sweep scheme; Gauss-Seidel is the v1 default (Jacobi is D3 — parallelism only).
    "sweep": "gauss_seidel",
    # warm-start seed; the D1 one-way seed (back-links cut) is the blessed default.
    "initial_guess": "one_way_seed",
}
_JOINT_SOLVER_ALLOWED_SWEEPS = {"gauss_seidel"}
_JOINT_SOLVER_ALLOWED_SEEDS = {"one_way_seed", "cold"}


def normalize_joint_solver(raw: Mapping[str, Any] | None, *, label: str) -> dict[str, Any] | None:
    """Normalize an optional scenario-level ``joint_solver`` block (D2-3, plan §4).

    The ONLY schema addition of D2. A cyclic SCC's outer damped-Gauss-Seidel loop
    (``pe.engine.joint.solve_joint_scc``) reads its settings here; every key is
    OPTIONAL and defaulted from :data:`_JOINT_SOLVER_DEFAULTS`. Absence is
    inertness: ``raw is None`` returns ``None`` and the caller emits NO
    ``joint_solver`` key, so a single-market / acyclic / D1 config normalizes
    byte-identically to today (the D1 COMPAT RULE, mirroring
    ``_OPTIONAL_MARKET_BODY_KEYS``). When present, every setting is validated
    with a loud ``ValueError`` — never a silent clamp.

    Args:
        raw: The raw ``joint_solver`` block (a mapping) or ``None`` when the
            scenario declares none.
        label: Error-message prefix, e.g. ``"Scenario 'S'"``.

    Returns:
        The normalized settings dict ``{relaxation, tolerance, max_iterations,
        sweep, initial_guess}`` (all keys present, defaulted), or ``None`` when
        ``raw`` is ``None``.

    Raises:
        ValueError: ``raw`` is not a mapping; ``relaxation`` outside ``(0, 1]``;
            non-positive ``tolerance``/``atol``; non-positive ``max_iterations``;
            an unknown ``sweep`` (only ``gauss_seidel`` in v1 — Jacobi is D3) or
            ``initial_guess``.
    """
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label}: joint_solver, if present, must be an object.")

    relaxation = float(raw.get("relaxation", _JOINT_SOLVER_DEFAULTS["relaxation"]))
    if not 0.0 < relaxation <= 1.0:
        raise ValueError(
            f"{label}: joint_solver.relaxation must be in (0, 1], got {relaxation}."
        )

    # ``tolerance`` is canonical; ``atol`` is accepted as an alias (plan §4).
    tol_raw = raw.get("tolerance", raw.get("atol", _JOINT_SOLVER_DEFAULTS["tolerance"]))
    tolerance = float(tol_raw)
    if tolerance <= 0.0:
        raise ValueError(
            f"{label}: joint_solver.tolerance (or atol) must be > 0, got {tolerance}."
        )

    max_iterations = int(raw.get("max_iterations", _JOINT_SOLVER_DEFAULTS["max_iterations"]))
    if max_iterations < 1:
        raise ValueError(
            f"{label}: joint_solver.max_iterations must be a positive integer, "
            f"got {max_iterations}."
        )

    sweep = str(raw.get("sweep", _JOINT_SOLVER_DEFAULTS["sweep"])).strip()
    if sweep not in _JOINT_SOLVER_ALLOWED_SWEEPS:
        raise ValueError(
            f"{label}: joint_solver.sweep must be one of "
            f"{sorted(_JOINT_SOLVER_ALLOWED_SWEEPS)} (Jacobi is D3), got '{sweep}'."
        )

    initial_guess = str(
        raw.get("initial_guess", _JOINT_SOLVER_DEFAULTS["initial_guess"])
    ).strip()
    if initial_guess not in _JOINT_SOLVER_ALLOWED_SEEDS:
        raise ValueError(
            f"{label}: joint_solver.initial_guess must be one of "
            f"{sorted(_JOINT_SOLVER_ALLOWED_SEEDS)}, got '{initial_guess}'."
        )

    return {
        "relaxation": relaxation,
        "tolerance": tolerance,
        "max_iterations": max_iterations,
        "sweep": sweep,
        "initial_guess": initial_guess,
    }


def _validated_msr_mode(scenario: dict[str, Any], label: str) -> str:
    mode = str(scenario.get("msr_mode") or "bank_threshold").strip()
    if mode not in _ALLOWED_MSR_MODES:
        raise ValueError(
            f"{label}: msr_mode must be one of "
            f"{sorted(_ALLOWED_MSR_MODES)}, got '{mode}'."
        )
    return mode


# D1 flow-vocabulary / link-unit pass-through keys (docs/platform-spec-d0-d1.md
# §5/§6): OPTIONAL on a market body, "default absent" — an absent key means
# "today's carbon labels", never an injected default value, so an example
# that never sets them normalizes to a dict with the key MISSING, exactly as
# it does today (byte-identical, D1 COMPAT RULE). Presence is validated
# (non-empty string) and preserved so a `markets:[...]` body — and any
# single-market scenario that already sets one of these ahead of D0-R2 —
# round-trips unchanged.
_OPTIONAL_MARKET_BODY_KEYS = ("flow_label", "flow_unit", "price_unit")

# Display-tier fallbacks for the two D0-R2 flow-vocabulary keys above — used
# ONLY by presentation callers (MCP compact.py's flow header today; the
# D0-R3 frontend chips next) when a scenario carries no flow_label/flow_unit.
# The kernel never reads these constants and normalize_scenario never injects
# them (see the comment above) — the "default" is a display convention, not a
# normalized value, so byte-identity of existing carbon-model output holds.
DEFAULT_FLOW_LABEL = "carbon"
DEFAULT_FLOW_UNIT = "tCO2e"


def _normalize_market_body(raw_body: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Normalize a market body — the scenario shape minus ``name``/``policy_events``.

    REUSED verbatim by both :func:`normalize_scenario` (legacy single-market
    path, byte-identical output) and ``config_io.markets.iter_market_bodies``
    (D1-1 multi-market accessor) — the ONE place market-body semantics
    (years/participants/model-approach/solver knobs/trajectories/...) are
    defined, per ``docs/platform-plan-d0-d1.md`` D1's COMPAT RULE ("A market
    body = today's scenario body minus name/policy_events... normalize_scenario
    internals reused per market").

    Args:
        raw_body: The market body's raw config dict (a whole raw scenario
            dict for the single-market caller; one ``markets[i]`` entry for
            the multi-market caller).
        label: Error-message prefix, e.g. ``"Scenario 'S'"`` or
            ``"Market 'steel'"`` — every ``ValueError`` this function raises
            is prefixed with it, so the single-market caller's wording stays
            byte-identical to before this function existed.

    Returns:
        The normalized body dict — every field ``normalize_scenario``
        returned before D1-1, minus ``name``/``policy_events``, plus any of
        ``flow_label``/``flow_unit``/``price_unit`` actually present in
        ``raw_body`` (D1 vocabulary, optional, no injected default).

    Raises:
        ValueError: Malformed/out-of-bound ``years``, ``sectors``,
            ``forward_transmission_lambda``, ``investment_max_iterations``,
            ``invest_credibility``, ``msr_mode``, or an empty-string
            ``flow_label``/``flow_unit``/``price_unit``.
    """
    # Product market (D3-3, docs/multi-commodity-plan.md §1/§6): a
    # ``model_approach: "product"`` body is a goods market, not a carbon
    # compliance flow — it is normalised ENTIRELY by the product_market plugin
    # door (the two-door config-facing surface), never the carbon year pipeline
    # below. Detected BEFORE ``blank_scenario`` so producer participants never
    # hit ``normalize_participant``. Golden-inert: no carbon body reaches this
    # branch. The import is function-local so a carbon-only config never loads
    # the product_market plugin.
    if str(raw_body.get("model_approach") or "").strip() == "product":
        from ..features.product_market.plugin import normalize_product_body

        return normalize_product_body(raw_body, label=label)

    scenario = blank_scenario()
    scenario.update(raw_body)

    years = scenario.get("years")
    if years is None:
        years = [_legacy_scenario_to_year(raw_body)]
    if not isinstance(years, list) or not years:
        raise ValueError(f"{label} must contain a non-empty 'years' list.")

    scenario["years"] = [normalize_year(item) for item in years]

    # Validate sector references in participants
    raw_sectors = scenario.get("sectors") or []
    if raw_sectors:
        sector_names = {str(s.get("name") or "").strip() for s in raw_sectors if isinstance(s, dict)}
        for year_item in scenario["years"]:
            for p in year_item.get("participants", []):
                sg = str(p.get("sector_group") or "")
                if sg and sg not in sector_names:
                    raise ValueError(
                        f"Participant '{p['name']}' has sector_group '{sg}' which does not "
                        f"match any defined sector. Defined sectors: {sorted(sector_names)}."
                    )

    model_approach = str(scenario.get("model_approach") or "competitive").strip()
    if model_approach not in ALLOWED_MODEL_APPROACHES:
        model_approach = "competitive"

    def _fval(key, default):
        try:
            return float(scenario.get(key) or default)
        except (TypeError, ValueError):
            return float(default)

    transmission_lambda = scenario.get("forward_transmission_lambda")
    if transmission_lambda is not None:
        transmission_lambda = float(transmission_lambda)
        if not 0.0 <= transmission_lambda <= 1.0:
            raise ValueError(
                f"{label}: forward_transmission_lambda must "
                f"be in [0, 1], got {transmission_lambda}."
            )

    # Endogenous-investment feedback (docs/invest-feedback-spec.md D6): the
    # master gate defaults FALSE (off-by-default proof chain); the safety
    # rail is left ``None`` when absent — the engine's own N_flagged + 1
    # default (``engine/feedback.py``) is NOT baked in here, per the plan.
    investment_max_iterations = scenario.get("investment_max_iterations")
    if investment_max_iterations is not None:
        investment_max_iterations = int(investment_max_iterations)
        if investment_max_iterations < 1:
            raise ValueError(
                f"{label}: investment_max_iterations must "
                f"be a positive integer safety rail, got {investment_max_iterations} "
                "(leave it unset for the engine's N_flagged + 1 default; spec D6)."
            )

    invest_credibility = scenario.get("invest_credibility")
    if invest_credibility is not None:
        invest_credibility = float(invest_credibility)
        if not 0.0 <= invest_credibility <= 1.0:
            raise ValueError(
                f"{label}: invest_credibility must be in "
                f"[0, 1], got {invest_credibility} (spec D2.2)."
            )

    body: dict[str, Any] = {
        "model_approach": model_approach,
        "discount_rate": _fval("discount_rate", 0.04),
        "risk_premium": _fval("risk_premium", 0.0),
        "forward_transmission_lambda": transmission_lambda,
        # Banking equilibrium (Rubin/Schennach)
        "banking_initial_bank": _fval("banking_initial_bank", 0.0),
        "banking_strict_no_arbitrage": bool(
            scenario.get("banking_strict_no_arbitrage", True)
        ),
        "banking_bank_tolerance": _fval("banking_bank_tolerance", 1e-6),
        "banking_supply_rule_max_iters": int(_fval("banking_supply_rule_max_iters", 25)),
        "banking_supply_rule_tolerance": _fval("banking_supply_rule_tolerance", 0.001),
        "reference_carbon_price": _fval("reference_carbon_price", 0.0),
        "nash_strategic_participants": list(scenario.get("nash_strategic_participants") or []),
        # Endogenous-investment feedback (docs/invest-feedback-spec.md D6) —
        # master gate off, safety rail unset (engine default), no pre-committed
        # adoptions, no scenario-wide credibility override.
        "investment_feedback_enabled": bool(scenario.get("investment_feedback_enabled", False)),
        "investment_max_iterations": investment_max_iterations,
        "investment_initial_adoptions": list(scenario.get("investment_initial_adoptions") or []),
        "invest_credibility": invest_credibility,
        # MSR
        "msr_enabled": bool(scenario.get("msr_enabled", False)),
        "msr_upper_threshold": _fval("msr_upper_threshold", 200.0),
        "msr_lower_threshold": _fval("msr_lower_threshold", 50.0),
        "msr_withhold_rate": _fval("msr_withhold_rate", 0.12),
        "msr_release_rate": _fval("msr_release_rate", 50.0),
        "msr_cancel_excess": bool(scenario.get("msr_cancel_excess", False)),
        "msr_cancel_threshold": _fval("msr_cancel_threshold", 400.0),
        # K-MSR decree modes (banking solver; kets-outlook msr.ts parameters)
        "msr_mode": _validated_msr_mode(scenario, label),
        "msr_price_band_high": _fval("msr_price_band_high", 25000.0),
        "msr_price_band_low": _fval("msr_price_band_low", 15000.0),
        "msr_surplus_upper_ratio": _fval("msr_surplus_upper_ratio", 0.18),
        "msr_surplus_lower_ratio": _fval("msr_surplus_lower_ratio", 0.05),
        "msr_max_intake_mt": _fval("msr_max_intake_mt", 20.0),
        "msr_max_release_mt": _fval("msr_max_release_mt", 20.0),
        "msr_initial_reserve_mt": _fval("msr_initial_reserve_mt", 0.0),
        "msr_start_year": _fval("msr_start_year", 0.0),
        "ccr_start_year": _fval("ccr_start_year", 0.0),
        # CCR (Carbon Cap Rule)
        "ccr_enabled": bool(scenario.get("ccr_enabled", False)),
        "ccr_phi_emissions": _fval("ccr_phi_emissions", 0.0),
        "ccr_phi_abatement_cost": _fval("ccr_phi_abatement_cost", 0.0),
        "ccr_reference_emissions": _fval("ccr_reference_emissions", 0.0),
        "ccr_reference_abatement_cost": _fval("ccr_reference_abatement_cost", 0.0),
        "solver_competitive_max_iters": int(_fval("solver_competitive_max_iters", 25)),
        "solver_competitive_tolerance": _fval("solver_competitive_tolerance", 0.001),
        "solver_hotelling_max_bisection_iters": int(_fval("solver_hotelling_max_bisection_iters", 80)),
        "solver_hotelling_max_lambda_expansions": int(_fval("solver_hotelling_max_lambda_expansions", 20)),
        "solver_hotelling_convergence_tol": _fval("solver_hotelling_convergence_tol", 0.0001),
        "solver_nash_price_step": _fval("solver_nash_price_step", 0.5),
        "solver_nash_max_iters": int(_fval("solver_nash_max_iters", 120)),
        "solver_nash_convergence_tol": _fval("solver_nash_convergence_tol", 0.001),
        "solver_penalty_price_multiplier": _fval("solver_penalty_price_multiplier", 1.25),
        "solver_hotelling_lambda_initial_low":   _fval("solver_hotelling_lambda_initial_low", 0.001),
        "solver_hotelling_lambda_initial_high":  _fval("solver_hotelling_lambda_initial_high", 20.0),
        "solver_hotelling_lambda_expand_factor": _fval("solver_hotelling_lambda_expand_factor", 3.0),
        "solver_price_bracket_expand_factor":    _fval("solver_price_bracket_expand_factor", 2.0),
        "solver_price_bracket_max_expansions":   int(_fval("solver_price_bracket_max_expansions", 10)),
        "solver_slsqp_max_iters":                int(_fval("solver_slsqp_max_iters", 400)),
        "solver_slsqp_ftol":                     _fval("solver_slsqp_ftol", 1e-9),
        "solver_nash_inner_xatol":               _fval("solver_nash_inner_xatol", 1e-4),
        "solver_calibration_xatol":              _fval("solver_calibration_xatol", 0.1),
        "solver_calibration_fatol":              _fval("solver_calibration_fatol", 0.01),
        "free_allocation_trajectories": list(scenario.get("free_allocation_trajectories") or []),
        "cap_trajectory": _normalize_trajectory(scenario.get("cap_trajectory")),
        "price_floor_trajectory": _normalize_trajectory(scenario.get("price_floor_trajectory")),
        "price_ceiling_trajectory": _normalize_trajectory(scenario.get("price_ceiling_trajectory")),
        "sectors": _normalize_sectors(scenario.get("sectors") or []),
        "years": scenario["years"],
    }
    for optional_key in _OPTIONAL_MARKET_BODY_KEYS:
        if optional_key in raw_body and raw_body[optional_key] is not None:
            value = str(raw_body[optional_key]).strip()
            if not value:
                raise ValueError(f"{label}: {optional_key}, if present, must be non-empty.")
            body[optional_key] = value

    # producer_ref (D3-4, docs/multi-commodity-spec.md §7 V-D3-3): a carbon market
    # body may reference the steel-body producer(s) — a build-time EMITTER VIEW
    # into the SAME param set (single source of truth). Carried through UNRESOLVED
    # here (raw ``{market, name?/names?}``) OR already RESOLVED
    # (``{market, producers_by_year}`` — the idempotent re-normalise pass); the
    # cross-market resolution itself lives in ``_normalize_markets_scenario``,
    # where every sibling body is in hand. Golden-inert: absent on every carbon
    # config, so the body normalises byte-identically without it.
    raw_producer_ref = raw_body.get("producer_ref")
    if raw_producer_ref is not None:
        if not isinstance(raw_producer_ref, Mapping):
            raise ValueError(f"{label}: producer_ref, if present, must be an object.")
        ref_market = str(raw_producer_ref.get("market", "")).strip()
        if not ref_market:
            raise ValueError(f"{label}: producer_ref requires a non-empty 'market' id.")
        body["producer_ref"] = dict(raw_producer_ref)
    return body


def _resolve_producer_refs(bodies_by_id: dict[str, dict[str, Any]], *, scenario_name: str) -> None:
    r"""Resolve every carbon body's ``producer_ref`` into a per-year emitter view (D3-4).

    The build-time producer_ref expansion (``docs/multi-commodity-spec.md`` §7
    V-D3-3): a carbon market body carrying ``{"producer_ref": {"market": "steel",
    "name"/"names": ...}}`` is expanded into a carbon-side EMITTER VIEW of the
    steel-body producer(s) — a REFERENCE to the SAME param set (single source of
    truth; the producer is authored ONCE in the steel body). The resolved form
    ``{"market": ref, "producers_by_year": {year: [producer_spec, ...]}}`` carries
    the referenced producers' normalised structural params PER YEAR, matched by
    year label, so the builder can materialise one
    :class:`~pe.core.participant.producer.MultiCommodityProducer` per view that
    computes ``e*`` on demand from the stamped price pair each sweep (never a
    cached copy, never solve-time injection). Idempotent: an already-resolved
    body (``producers_by_year`` present) is re-resolved deterministically to the
    same value; a body with no ``producer_ref`` is untouched.

    Args:
        bodies_by_id: The scenario's normalised market bodies, keyed by market id
            (mutated in place — resolved bodies gain ``producers_by_year``).
        scenario_name: For error attribution.

    Raises:
        ValueError: The referenced market is unknown or is not a product market;
            or a named producer is absent from a referenced year.
    """
    for market_id, body in bodies_by_id.items():
        ref = body.get("producer_ref")
        if not ref:
            continue
        ref_market = str(ref.get("market", "")).strip()
        if ref_market not in bodies_by_id:
            raise ValueError(
                f"Scenario '{scenario_name}' market '{market_id}': producer_ref points to "
                f"unknown market '{ref_market}' — known markets are {sorted(bodies_by_id)}."
            )
        product_body = bodies_by_id[ref_market]
        if str(product_body.get("model_approach") or "").strip() != "product":
            raise ValueError(
                f"Scenario '{scenario_name}' market '{market_id}': producer_ref must point "
                f"to a product market, but '{ref_market}' is "
                f"'{product_body.get('model_approach')}'."
            )
        # Optional name filter: ``names`` (list) or ``name`` (single); absent ⇒
        # every producer of the referenced market (the anchor's two firms).
        raw_names = ref.get("names")
        if raw_names is None and ref.get("name") is not None:
            raw_names = [ref["name"]]
        names_filter = [str(n) for n in raw_names] if raw_names is not None else None

        producers_by_year: dict[str, list[dict[str, Any]]] = {}
        for year_body in product_body.get("years") or []:
            year_label = str(year_body["year"])
            producers = list(year_body.get("producers") or [])
            if names_filter is not None:
                available = {str(p["name"]) for p in producers}
                missing = [n for n in names_filter if n not in available]
                if missing:
                    raise ValueError(
                        f"Scenario '{scenario_name}' market '{market_id}': producer_ref names "
                        f"producer(s) {missing} absent from market '{ref_market}' year "
                        f"'{year_label}' (available: {sorted(available)})."
                    )
                producers = [p for p in producers if str(p["name"]) in names_filter]
            producers_by_year[year_label] = producers

        resolved: dict[str, Any] = {"market": ref_market, "producers_by_year": producers_by_year}
        if names_filter is not None:
            resolved["names"] = names_filter
        body["producer_ref"] = resolved


def _normalize_markets_scenario(raw_scenario: dict[str, Any]) -> dict[str, Any]:
    """Normalize a ``markets``-shaped (multi-market, linked) scenario (D1-4).

    The GRAPH DISENTANGLEMENT counterpart of the flat single-market path
    (``docs/platform-plan-d0-d1.md`` D1): a scenario carrying ``markets``
    normalizes each entry through the SAME per-market internals
    (:func:`_normalize_market_body`) the flat path calls, then validates its
    ``links`` through the ``market_links`` plugin door
    (:func:`~pe.features.market_links.plugin.validate_links`). This is the
    ONE normalization of a multi-market scenario — ``config_io.markets.
    iter_market_bodies`` (the D1-1 accessor) delegates here rather than
    duplicating the walk (D1-1's own inline logic retired in D1-4, now that
    the guard this function replaces is gone).

    Args:
        raw_scenario: A raw scenario dict carrying a ``markets`` key
            (``docs/platform-spec-d0-d1.md`` §6).

    Returns:
        ``{"name": ..., "markets": [{"market_id": ..., **normalized body},
        ...], "links": [...normalized links...]}`` — every market body
        normalized via :func:`_normalize_market_body`; every link
        normalized via ``validate_links`` (spec §2, §6).

    Raises:
        ValueError: Empty/non-list/malformed ``markets``; a missing, empty,
            or duplicate ``market_id``; any per-market body validation
            error; or any link validation error (``validate_links``).
    """
    name = str(raw_scenario.get("name", "New Scenario")).strip()
    if not name:
        raise ValueError("Each scenario must have a non-empty name.")

    raw_markets = raw_scenario.get("markets")
    if not isinstance(raw_markets, list) or not raw_markets:
        raise ValueError(f"Scenario '{name}': 'markets' must be a non-empty list.")

    ordered_ids: list[str] = []
    bodies_by_id: dict[str, dict[str, Any]] = {}
    for index, raw_market in enumerate(raw_markets):
        if not isinstance(raw_market, dict):
            raise ValueError(f"Scenario '{name}' markets[{index}] must be an object.")
        market_id = str(raw_market.get("market_id", "")).strip()
        if not market_id:
            raise ValueError(f"Scenario '{name}' markets[{index}] must have a non-empty 'market_id'.")
        if market_id in bodies_by_id:
            raise ValueError(f"Scenario '{name}' markets contains duplicate market_id '{market_id}'.")
        body = _normalize_market_body(raw_market, label=f"Market '{market_id}'")
        bodies_by_id[market_id] = body
        ordered_ids.append(market_id)

    # producer_ref expansion (D3-4): resolve every carbon body's ``producer_ref``
    # against its referenced product body NOW that all siblings are in hand — the
    # BUILD-TIME emitter-view expansion (single source of truth, V-D3-3). A no-op
    # for every scenario without a producer_ref, so the ``markets`` list below is
    # byte-identical for all committed configs.
    _resolve_producer_refs(bodies_by_id, scenario_name=name)

    markets: list[dict[str, Any]] = [
        {"market_id": market_id, **bodies_by_id[market_id]} for market_id in ordered_ids
    ]

    links = validate_links(raw_scenario.get("links") or [], bodies_by_id)

    normalized: dict[str, Any] = {"name": name, "markets": markets, "links": links}
    # D2 joint-solver block (plan §4) — emitted ONLY when the scenario declares
    # one, so an acyclic / D1 multi-market config stays byte-identical (the D1
    # COMPAT RULE; mirrors the _OPTIONAL_MARKET_BODY_KEYS "default absent" pattern).
    if raw_scenario.get("joint_solver") is not None:
        normalized["joint_solver"] = normalize_joint_solver(
            raw_scenario["joint_solver"], label=f"Scenario '{name}'"
        )
    return normalized


def normalize_scenario(raw_scenario: dict[str, Any]) -> dict[str, Any]:
    if "markets" in raw_scenario:
        return _normalize_markets_scenario(raw_scenario)
    name = str(raw_scenario.get("name", "New Scenario")).strip()
    if not name:
        raise ValueError("Each scenario must have a non-empty name.")

    body = _normalize_market_body(raw_scenario, label=f"Scenario '{name}'")
    return {
        "name": name,
        **body,
        "policy_events": list(raw_scenario.get("policy_events") or []),
    }


def _legacy_scenario_to_year(raw_scenario: Mapping[str, Any]) -> dict[str, Any]:
    legacy_year = blank_year_config()
    for field in legacy_year:
        if field in raw_scenario:
            legacy_year[field] = raw_scenario[field]
    legacy_year["participants"] = raw_scenario.get("participants", [])
    legacy_year["year"] = str(raw_scenario.get("year", "Base Year"))
    return legacy_year


def load_config(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return normalize_config(deepcopy(data))


def save_config(config: dict[str, Any], config_path: str | Path) -> None:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_config(deepcopy(config))
    with path.open("w", encoding="utf-8") as handle:
        json.dump(normalized, handle, indent=2)


def build_markets_from_file(config_path: str | Path) -> list[CarbonMarket]:
    return build_markets_from_config(load_config(config_path))


# ── Product market construction (D3-3, docs/multi-commodity-plan.md §1) ──────
# A product market is a CarbonMarket with INERT cap buckets (total_cap =
# auction_offered = 0) carrying the normalised product body as stamped
# attributes (as msr_*/eua_price already are, plan §1). One inert placeholder
# participant satisfies the CarbonMarket ≥1-participant / cap-consistency
# invariants without contributing free allocation — the producers are stamped
# as product data (``product_producers``) and read by the engine's product
# solver, never as carbon participants (the multi-commodity carbon market has NO
# free-alloc supply bucket, spec §7 V-D3-3). None of the carbon reporters is
# attached, so the reporting host emits base columns only over the solver's
# producer participant frame.
_PRODUCT_SHELL_PARTICIPANT_NAME = "__product_shell__"


def _build_producer_ref_views(producer_ref: Mapping[str, Any], year_label: str) -> list:
    r"""Materialise a carbon year's producer emitter views from a resolved producer_ref.

    Builds one :class:`~pe.core.participant.producer.MultiCommodityProducer` per
    referenced steel producer of ``year_label`` (D3-4, spec §7 V-D3-3). Each view
    is a REFERENCE to the same param set (the producer is authored once in the
    steel body) and duck-types the ``MarketParticipant`` compliance protocol on
    the carbon face, so the existing carbon clearing/reporting runs UNCHANGED with
    a view in its participant list. Deterministic: producers are sorted by name.

    Args:
        producer_ref: The resolved producer_ref ``{"market", "producers_by_year",
            ...}`` (from :func:`_resolve_producer_refs`).
        year_label: The carbon market year whose steel-side producers to view.

    Returns:
        The year's ``MultiCommodityProducer`` emitter views (``[]`` when the year
        has no referenced producers).
    """
    from ..core.participant.producer import MultiCommodityProducer, ProducerParams

    producers_by_year = producer_ref.get("producers_by_year") or {}
    specs = list(producers_by_year.get(str(year_label)) or [])
    views: list = []
    for spec in sorted(specs, key=lambda s: str(s["name"])):
        params = ProducerParams(
            gamma=float(spec["gamma"]),
            delta=float(spec["delta"]),
            sigma=float(spec["sigma"]),
            beta=float(spec["beta"]),
            a_max=float(spec["a_max"]),
            phi_oba=float(spec.get("phi_oba", 0.0)),
            f_lump=float(spec.get("f_lump", 0.0)),
        )
        views.append(MultiCommodityProducer(name=str(spec["name"]), params=params))
    return views


def _build_product_markets(scenario: dict[str, Any]) -> list[CarbonMarket]:
    """Build one inert-cap ``CarbonMarket`` per year of a product scenario.

    Args:
        scenario: A normalised product scenario (``model_approach: "product"``)
            carrying ``carbon_price``/``product_demand``/``import_supply``/
            ``years`` (the ``product_market`` plugin's normalised body plus the
            scenario ``name``).

    Returns:
        The scenario's per-year product markets, in year (declaration) order.
    """
    scenario_name = str(scenario["name"])
    return [
        _build_product_market_from_year(scenario_name, year_body, scenario)
        for year_body in scenario["years"]
    ]


def _build_product_market_from_year(
    scenario_name: str, year_body: dict[str, Any], scenario: Mapping[str, Any]
) -> CarbonMarket:
    """Construct one product-market year as an inert-cap ``CarbonMarket``.

    Args:
        scenario_name: The scenario name (market ledger key).
        year_body: One normalised ``years[i]`` entry ``{year, producers: [...]}``.
        scenario: The whole normalised product scenario (read for the body-level
            ``carbon_price``/``product_demand``/``import_supply``).

    Returns:
        The ``CarbonMarket`` shell with the product body stamped as attributes
        for the engine's ``"product"`` dispatch branch.
    """
    placeholder = MarketParticipant(
        name=_PRODUCT_SHELL_PARTICIPANT_NAME,
        initial_emissions=0.0,
        marginal_abatement_cost=0.0,
        free_allocation_ratio=0.0,
        penalty_price=0.0,
    )
    market = CarbonMarket(
        participants=[placeholder],
        total_cap=0.0,
        auction_offered=0.0,
        scenario_name=scenario_name,
        year=str(year_body["year"]),
    )
    # Stamp the product body (read by pe.engine's product solver via getattr) and
    # the scenario-level fields dispatch reads via getattr on the first market.
    # setattr (not a typed attribute write): CarbonMarket carries these product
    # + approach fields dynamically — the solver/dispatch read them via getattr,
    # so they are written via setattr symmetrically (no new mypy attr-defined;
    # the dispatch.py investment-field precedent).
    setattr(market, "model_approach", "product")  # noqa: B010
    setattr(market, "product_carbon_price", float(scenario.get("carbon_price") or 0.0))  # noqa: B010
    setattr(market, "product_demand", dict(scenario.get("product_demand") or {}))  # noqa: B010
    setattr(market, "product_import_supply", dict(scenario.get("import_supply") or {}))  # noqa: B010
    setattr(market, "product_producers", list(year_body.get("producers") or []))  # noqa: B010
    # Dispatch/run_simulation getattr fields — product uses neither transmission
    # nor investment feedback; set them explicitly to the inert/off values.
    setattr(market, "forward_transmission_lambda", None)  # noqa: B010
    setattr(market, "investment_feedback_enabled", False)  # noqa: B010
    setattr(market, "investment_max_iterations", None)  # noqa: B010
    setattr(market, "investment_initial_adoptions", [])  # noqa: B010
    setattr(market, "discount_rate", float(scenario.get("discount_rate") or 0.04))  # noqa: B010
    setattr(market, "risk_premium", float(scenario.get("risk_premium") or 0.0))  # noqa: B010
    return market


def build_markets_from_config(config: dict[str, Any]) -> list[CarbonMarket]:
    normalized = normalize_config(deepcopy(config))
    markets: list[CarbonMarket] = []
    for scenario in normalized["scenarios"]:
        if "markets" in scenario:
            raise ValueError(
                f"Scenario '{scenario.get('name')}' carries a 'markets' key: "
                "build_markets_from_config is the flat single-market builder — "
                "a linked (multi-market) scenario is solved via "
                "pe.engine.run_simulation_from_config (which routes it to "
                "pe.engine.solve_multi_market_scenario), never this function."
            )
        # Product market (D3-3): a ``model_approach: "product"`` scenario is
        # built by the dedicated product path (inert cap buckets + stamped
        # product body), NOT the carbon per-year pipeline. Gated on the approach
        # string, so every carbon scenario reaches the byte-identical branch
        # below (golden-inert).
        if str(scenario.get("model_approach") or "").strip() == "product":
            markets.extend(_build_product_markets(scenario))
            continue
        scenario_meta = {
            "model_approach": scenario.get("model_approach", "competitive"),
            # producer_ref (D3-4): resolved emitter-view producers by year, or None.
            # Read only by build_market_from_year's producer_ref expansion; every
            # non-producer_ref scenario passes None ⇒ byte-identical build.
            "producer_ref": scenario.get("producer_ref"),
            "discount_rate": scenario.get("discount_rate", 0.04),
            "risk_premium": scenario.get("risk_premium", 0.0),
            "forward_transmission_lambda": scenario.get("forward_transmission_lambda"),
            "banking_initial_bank": scenario.get("banking_initial_bank", 0.0),
            "banking_strict_no_arbitrage": scenario.get("banking_strict_no_arbitrage", True),
            "banking_bank_tolerance": scenario.get("banking_bank_tolerance", 1e-6),
            "banking_supply_rule_max_iters": scenario.get("banking_supply_rule_max_iters", 25),
            "banking_supply_rule_tolerance": scenario.get("banking_supply_rule_tolerance", 0.001),
            "reference_carbon_price": scenario.get("reference_carbon_price", 0.0),
            "nash_strategic_participants": scenario.get("nash_strategic_participants", []),
            # Endogenous-investment feedback (docs/invest-feedback-spec.md D6)
            "investment_feedback_enabled": scenario.get("investment_feedback_enabled", False),
            "investment_max_iterations": scenario.get("investment_max_iterations"),
            "investment_initial_adoptions": scenario.get("investment_initial_adoptions", []),
            "invest_credibility": scenario.get("invest_credibility"),
            "free_allocation_trajectories": scenario.get("free_allocation_trajectories", []),
            "cap_trajectory": scenario.get("cap_trajectory", {}),
            "price_floor_trajectory": scenario.get("price_floor_trajectory", {}),
            "price_ceiling_trajectory": scenario.get("price_ceiling_trajectory", {}),
            "sectors": scenario.get("sectors", []),
            # MSR
            "msr_enabled": scenario.get("msr_enabled", False),
            "msr_upper_threshold": scenario.get("msr_upper_threshold", 200.0),
            "msr_lower_threshold": scenario.get("msr_lower_threshold", 50.0),
            "msr_withhold_rate": scenario.get("msr_withhold_rate", 0.12),
            "msr_release_rate": scenario.get("msr_release_rate", 50.0),
            "msr_cancel_excess": scenario.get("msr_cancel_excess", False),
            "msr_cancel_threshold": scenario.get("msr_cancel_threshold", 400.0),
            "msr_mode": scenario.get("msr_mode", "bank_threshold"),
            "msr_price_band_high": scenario.get("msr_price_band_high", 25000.0),
            "msr_price_band_low": scenario.get("msr_price_band_low", 15000.0),
            "msr_surplus_upper_ratio": scenario.get("msr_surplus_upper_ratio", 0.18),
            "msr_surplus_lower_ratio": scenario.get("msr_surplus_lower_ratio", 0.05),
            "msr_max_intake_mt": scenario.get("msr_max_intake_mt", 20.0),
            "msr_max_release_mt": scenario.get("msr_max_release_mt", 20.0),
            "msr_initial_reserve_mt": scenario.get("msr_initial_reserve_mt", 0.0),
            "msr_start_year": scenario.get("msr_start_year", 0.0),
            "ccr_start_year": scenario.get("ccr_start_year", 0.0),
            # CCR
            "ccr_enabled": scenario.get("ccr_enabled", False),
            "ccr_phi_emissions": scenario.get("ccr_phi_emissions", 0.0),
            "ccr_phi_abatement_cost": scenario.get("ccr_phi_abatement_cost", 0.0),
            "ccr_reference_emissions": scenario.get("ccr_reference_emissions", 0.0),
            "ccr_reference_abatement_cost": scenario.get("ccr_reference_abatement_cost", 0.0),
            "solver_competitive_max_iters": scenario.get("solver_competitive_max_iters", 25),
            "solver_competitive_tolerance": scenario.get("solver_competitive_tolerance", 0.001),
            "solver_hotelling_max_bisection_iters": scenario.get("solver_hotelling_max_bisection_iters", 80),
            "solver_hotelling_max_lambda_expansions": scenario.get("solver_hotelling_max_lambda_expansions", 20),
            "solver_hotelling_convergence_tol": scenario.get("solver_hotelling_convergence_tol", 0.0001),
            "solver_nash_price_step": scenario.get("solver_nash_price_step", 0.5),
            "solver_nash_max_iters": scenario.get("solver_nash_max_iters", 120),
            "solver_nash_convergence_tol": scenario.get("solver_nash_convergence_tol", 0.001),
            "solver_penalty_price_multiplier": scenario.get("solver_penalty_price_multiplier", 1.25),
            "solver_hotelling_lambda_initial_low":   scenario.get("solver_hotelling_lambda_initial_low", 0.001),
            "solver_hotelling_lambda_initial_high":  scenario.get("solver_hotelling_lambda_initial_high", 20.0),
            "solver_hotelling_lambda_expand_factor": scenario.get("solver_hotelling_lambda_expand_factor", 3.0),
            "solver_price_bracket_expand_factor":    scenario.get("solver_price_bracket_expand_factor", 2.0),
            "solver_price_bracket_max_expansions":   scenario.get("solver_price_bracket_max_expansions", 10),
            "solver_slsqp_max_iters":                scenario.get("solver_slsqp_max_iters", 400),
            "solver_slsqp_ftol":                     scenario.get("solver_slsqp_ftol", 1e-9),
            "solver_nash_inner_xatol":               scenario.get("solver_nash_inner_xatol", 1e-4),
            "solver_calibration_xatol":              scenario.get("solver_calibration_xatol", 0.1),
            "solver_calibration_fatol":              scenario.get("solver_calibration_fatol", 0.01),
        }
        for year_config in scenario["years"]:
            markets.append(build_market_from_year(scenario["name"], year_config, scenario_meta))
    return markets


def _stamp_investment_specs(
    scenario_name: str,
    year_label: str,
    raw_participants: list[dict[str, Any]],
    participants: list[MarketParticipant],
    meta: Mapping[str, Any],
) -> list[MarketParticipant]:
    """Collect flagged technology options into ``AdoptionSpec``s and attach them.

    The builder-level half of the spec D3.2/D6 loud guards (dispatch.py's
    ``_investment_configured`` mirrors this belt-and-braces at solve time):
    a flagged ``investment_trigger`` sub-dict with the scenario's master
    gate off is a config error, never a silent ignore; the gate on with
    zero flagged options anywhere in this year is equally an error (the
    feature would do nothing). When the gate is on, every flagged option's
    spec is built via the feature's own door (``normalize_investment_trigger``
    — never re-derived here) and attached through the ONE sanctioned writer
    (``attach_adoption_specs``, the ``stamp_and_attach`` precedent next to
    which this call sits in ``build_market_from_year``). The scenario's
    ``invest_credibility``, when set, OVERRIDES every flagged option's own
    ``credibility`` default — the field a policy event raises mid-horizon to
    model an announced decree's credibility (spec D2.2); a spec's
    ``discount_rate=None`` already inherits the scenario default downstream
    (``InvestmentRule`` construction, ``core.investment``), so no scenario
    discount-rate plumbing is needed here.

    Args:
        scenario_name: Scenario name (error attribution).
        year_label: This year's label (error attribution).
        raw_participants: This year's participant dicts AFTER the
            ``_PARTICIPANT_TRANSFORMS`` pipeline — same order as
            ``participants``, so ``zip`` pairs them by index.
        participants: The ``MarketParticipant`` objects built from
            ``raw_participants`` (mutated in place by ``attach_adoption_specs``
            and returned, matching the elastic-baseline stamp's own
            comprehension pattern).
        meta: Scenario metadata (``investment_feedback_enabled``,
            ``invest_credibility``).

    Returns:
        ``participants`` (same list, same order; each stamped in place).

    Raises:
        ValueError: A flagged option exists while the master gate is off;
            the master gate is on with no flagged option anywhere in this
            year; the scenario's ``model_approach`` is outside the v1
            approach coverage (competitive, banking); or a flagged option
            fails ``AdoptionSpec`` construction (bound violation, propagated
            with the offending pair's name).
    """
    investment_feedback_enabled = bool(meta.get("investment_feedback_enabled", False))
    flagged_pairs = sorted(
        {
            (str(raw_participant.get("name", "")), str(raw_option.get("name", "")))
            for raw_participant in raw_participants
            for raw_option in (raw_participant.get("technology_options") or [])
            if raw_option.get("investment_trigger")
        }
    )
    if flagged_pairs and not investment_feedback_enabled:
        raise ValueError(
            f"Scenario '{scenario_name}' year '{year_label}': technology option(s) "
            f"{flagged_pairs} carry an investment_trigger block but "
            "investment_feedback_enabled is false — enable the master gate or "
            "remove the investment_trigger block(s) (spec D3.2)."
        )
    if not investment_feedback_enabled:
        return participants
    if not flagged_pairs:
        raise ValueError(
            f"Scenario '{scenario_name}' year '{year_label}': "
            "investment_feedback_enabled is true but no technology option "
            "carries an investment_trigger block anywhere in this year — flag "
            "one or more technology options, or disable the feature (spec D6)."
        )
    # v1 approach coverage (docs/invest-feedback-plan.md ARBITRATION NOTE;
    # R33 in blocks/validate.py mirrors this for the graph-authoring door):
    # the outer loop only wraps the competitive and banking full path
    # solves (spec D1.3) — engine/dispatch.py's "all" branch already raises
    # on its own, but hotelling/nash_cournot never wrap the loop at all, so
    # a scenario that flags an option under either would silently run the
    # unmasked legacy path unless caught here.
    approach = str(meta.get("model_approach") or "competitive")
    if approach not in ("competitive", "banking"):
        raise ValueError(
            f"Scenario '{scenario_name}' year '{year_label}': endogenous-investment "
            "feedback requires model_approach 'competitive' or 'banking' (v1 "
            f"approach coverage), got '{approach}' (spec D1.3)."
        )

    credibility_override = meta.get("invest_credibility")
    stamped: list[MarketParticipant] = []
    for raw_participant, participant in zip(raw_participants, participants, strict=True):
        specs = []
        for raw_option in raw_participant.get("technology_options") or []:
            trigger_raw = raw_option.get("investment_trigger")
            if not trigger_raw:
                continue
            kwargs = _normalize_investment_trigger(
                trigger_raw, str(raw_option.get("name", "")), participant.name
            )
            if credibility_override is not None:
                kwargs["credibility"] = float(credibility_override)
            specs.append(AdoptionSpec(**kwargs))
        stamped.append(_attach_adoption_specs(participant, tuple(specs)))
    return stamped


def build_market_from_year(
    scenario_name: str,
    year_config: dict[str, Any],
    scenario_meta: dict[str, Any] | None = None,
) -> CarbonMarket:
    meta = scenario_meta or {}
    year_num = _year_to_float(str(year_config.get("year", "2030")))
    trajectories = list(meta.get("free_allocation_trajectories") or [])
    sectors = list(meta.get("sectors") or [])

    # ── Sector-level pool derivation (host-called, features.sectors.plugin) ──
    # Computes per-sector free-allocation pools and, when sectors are
    # defined, the scenario-derived total_cap / auction_offered from the sum
    # of sector caps — ONCE per year, before the per-participant pipeline
    # (the initial_emissions fallback needs every participant in the year at
    # once; see `derive_sector_pools`'s docstring for why this stays
    # host-called rather than a per-participant transform).
    year_participants = list(year_config.get("participants", []))
    sector_pools, derived_total_cap, derived_auction = derive_sector_pools(
        year_num, sectors, year_participants, interp_value=_interp_value
    )

    # ── Per-participant transform pipeline (`_PARTICIPANT_TRANSFORMS`) ───────
    # Sector-pool allocation -> trajectory patch (host-generic) -> OBA, in
    # that EXACT reviewed order (see the literal's module-level comment).
    # `meta` is extended with the derived pool table so
    # `SectorPoolAllocation.apply` can read it; every step in the pipeline
    # receives the same extended mapping for a uniform call signature.
    transform_meta: dict[str, Any] = {**meta, "sector_pools": sector_pools}
    raw_participants = year_participants
    for transform in _PARTICIPANT_TRANSFORMS:
        raw_participants = [transform(p, year_num, transform_meta) for p in raw_participants]

    participants = [build_participant(item) for item in raw_participants]

    # Apply free-allocation phase-out trajectories — override per-participant ratio
    if trajectories:
        updated: list = []
        for p in participants:
            override = None
            for traj in trajectories:
                if str(traj.get("participant_name", "")) == p.name:
                    override = _interp_ratio(year_num, traj)
                    break
            if override is not None:
                import dataclasses as _dc
                p = _dc.replace(p, free_allocation_ratio=min(1.0, max(0.0, override)))
            updated.append(p)
        participants = updated

    # Option A: stamp the scenario reference carbon price onto each participant
    # so its price-elastic baseline has an anchor (0 keeps the channel disabled).
    # The elastic_baseline plugin OWNS this stamping step (Arbitration outcomes,
    # O8, binding): it stamps reference_carbon_price AND attaches the
    # ElasticBaselineOverlay in one call, per participant, conditional on that
    # participant's own output_price_elasticity > 0 — a bare field assignment
    # here would trip MarketParticipant's loud guard for elastic participants.
    reference_carbon_price = float(meta.get("reference_carbon_price") or 0.0)
    if reference_carbon_price > 0.0:
        participants = [
            _elastic_stamp_and_attach(participant, reference_carbon_price)
            for participant in participants
        ]

    # Endogenous-investment feedback (docs/invest-feedback-spec.md D3.2/D6):
    # collect this year's flagged technology options into AdoptionSpecs and
    # attach them via the feature's sanctioned writer — the loud guards fire
    # regardless of the master gate (see _stamp_investment_specs docstring).
    participants = _stamp_investment_specs(
        scenario_name, str(year_config["year"]), raw_participants, participants, meta
    )

    # producer_ref emitter-view expansion (D3-4, docs/multi-commodity-spec.md §7
    # V-D3-3): append the carbon-side MultiCommodityProducer view(s) of the
    # referenced steel producer(s) for THIS year. Each view computes e* on demand
    # from the stamped (P_steel, P_carbon) pair each sweep (the output_ref_price
    # channel stamps P_steel); at build time (prices 0 ⇒ q*=0) it contributes 0
    # free allocation, so the carbon cap accounting is unmoved (no free-alloc
    # supply bucket — clearing is purely Σe*=Cap). A no-op when producer_ref is
    # absent (every carbon golden), so participants stay byte-identical.
    producer_ref = meta.get("producer_ref")
    if producer_ref:
        participants = [
            *participants,
            *_build_producer_ref_views(producer_ref, str(year_config["year"])),
        ]

    free_allocations = sum(participant.free_allocation for participant in participants)
    reserved_allowances = float(year_config.get("reserved_allowances", 0.0))
    cancelled_allowances = float(year_config.get("cancelled_allowances", 0.0))

    # Apply cap / price-bound trajectories — override per-year values. The
    # cap arm stays HOST (it is the cap's, not a price control's); the
    # floor/ceiling arms are the price_controls feature's config door (O10),
    # handed the host's _interp_value so trajectory semantics are defined
    # exactly once.
    total_cap = float(year_config["total_cap"])
    price_lower_bound = year_config.get("price_lower_bound")
    price_upper_bound = year_config.get("price_upper_bound")
    cap_override = _interp_value(year_num, meta.get("cap_trajectory") or {})
    if cap_override is not None:
        total_cap = cap_override
    price_lower_bound, price_upper_bound = apply_price_bound_trajectories(
        year_num,
        meta,
        price_lower_bound,
        price_upper_bound,
        interp_value=_interp_value,
    )

    # Sector-derived values override cap_trajectory and per-year values
    if derived_total_cap is not None:
        total_cap = derived_total_cap
    if derived_auction is not None:
        auction_offered_from_sectors = derived_auction
    else:
        auction_offered_from_sectors = None

    if year_config["auction_mode"] == "derive_from_cap":
        auction_offered = (
            total_cap
            - free_allocations
            - reserved_allowances
            - cancelled_allowances
        )
    elif auction_offered_from_sectors is not None:
        auction_offered = auction_offered_from_sectors
    else:
        auction_offered = year_config["auction_offered"]

    if auction_offered < 0:
        raise ValueError(
            f"Scenario '{scenario_name}' year '{year_config['year']}' implies negative "
            "auction offered. Raise the cap or lower free allocation."
        )

    # Cap consistency check — post-trajectory, with actual effective values
    effective_supply = (
        free_allocations + auction_offered + reserved_allowances + cancelled_allowances
    )
    if total_cap > 0 and effective_supply - total_cap > 1e-6:
        raise ValueError(
            f"Scenario '{scenario_name}' year '{year_config['year']}': allowance supply "
            f"({effective_supply:.2f}) exceeds total_cap ({total_cap:.2f}). "
            "Reduce auction_offered, free_allocation_ratio, or increase total_cap."
        )

    market = CarbonMarket(
        participants=participants,
        total_cap=total_cap,
        auction_offered=auction_offered,
        reserved_allowances=reserved_allowances,
        cancelled_allowances=cancelled_allowances,
        auction_reserve_price=year_config["auction_reserve_price"],
        minimum_bid_coverage=year_config["minimum_bid_coverage"],
        unsold_treatment=year_config["unsold_treatment"],
        scenario_name=scenario_name,
        year=year_config["year"],
        price_lower_bound=price_lower_bound,
        price_upper_bound=price_upper_bound,
        banking_allowed=year_config["banking_allowed"],
        borrowing_allowed=year_config["borrowing_allowed"],
        borrowing_limit=year_config["borrowing_limit"],
        expectation_rule=year_config["expectation_rule"],
        manual_expected_price=year_config["manual_expected_price"],
        penalty_price_multiplier=float(meta.get("solver_penalty_price_multiplier") or 1.25),
    )
    # Attach reporting plugin literals (PLAN v2 two-door features; the only
    # CarbonMarket construction site that wires them — Arbitration outcomes,
    # O7). A market built directly, outside config_io, keeps the base
    # columns only (see CarbonMarket's docstring).
    market.participant_reporters = _PARTICIPANT_REPORTERS
    market.summary_reporters_pre_year = _SUMMARY_REPORTERS_PRE_YEAR
    market.summary_reporters_post_year = _SUMMARY_REPORTERS_POST_YEAR
    # Attach scenario-level and year-level modelling approach fields
    market.model_approach = meta.get("model_approach", "competitive")
    market.discount_rate = float(meta.get("discount_rate") or 0.04)
    market.risk_premium = float(meta.get("risk_premium") or 0.0)
    _ftl = meta.get("forward_transmission_lambda")
    market.forward_transmission_lambda = None if _ftl is None else float(_ftl)
    # Attach endogenous-investment feedback settings (docs/invest-feedback-
    # spec.md D6) — the three fields the dispatch guard/engine host read via
    # getattr(m0, ...) (engine/dispatch.py:_investment_configured,
    # engine/feedback.py:solve_with_investment_feedback).
    market.investment_feedback_enabled = bool(meta.get("investment_feedback_enabled", False))
    _max_iters = meta.get("investment_max_iterations")
    market.investment_max_iterations = None if _max_iters is None else int(_max_iters)
    market.investment_initial_adoptions = list(meta.get("investment_initial_adoptions") or [])
    # Attach banking-equilibrium settings
    market.banking_initial_bank = float(meta.get("banking_initial_bank") or 0.0)
    market.banking_strict_no_arbitrage = bool(
        meta.get("banking_strict_no_arbitrage", True)
    )
    market.banking_bank_tolerance = float(meta.get("banking_bank_tolerance") or 1e-6)
    market.banking_supply_rule_max_iters = int(
        meta.get("banking_supply_rule_max_iters") or 25
    )
    market.banking_supply_rule_tolerance = float(
        meta.get("banking_supply_rule_tolerance") or 0.001
    )
    market.nash_strategic_participants = list(meta.get("nash_strategic_participants") or [])
    market.carbon_budget = float(year_config.get("carbon_budget") or 0.0)
    market.hoarding_inflow = float(year_config.get("hoarding_inflow") or 0.0)
    market.cap_trajectory = dict(meta.get("cap_trajectory") or {})
    market.price_floor_trajectory = dict(meta.get("price_floor_trajectory") or {})
    market.price_ceiling_trajectory = dict(meta.get("price_ceiling_trajectory") or {})
    market.eua_price = float(year_config.get("eua_price") or 0.0)
    market.eua_prices = dict(year_config.get("eua_prices") or {})
    market.eua_price_ensemble = dict(year_config.get("eua_price_ensemble") or {})
    # Attach MSR settings
    market.msr_enabled = bool(meta.get("msr_enabled", False))
    market.msr_upper_threshold = float(meta.get("msr_upper_threshold") or 200.0)
    market.msr_lower_threshold = float(meta.get("msr_lower_threshold") or 50.0)
    market.msr_withhold_rate = float(meta.get("msr_withhold_rate") or 0.12)
    market.msr_release_rate = float(meta.get("msr_release_rate") or 50.0)
    market.msr_cancel_excess = bool(meta.get("msr_cancel_excess", False))
    market.msr_cancel_threshold = float(meta.get("msr_cancel_threshold") or 400.0)
    market.msr_mode = str(meta.get("msr_mode") or "bank_threshold")
    market.msr_price_band_high = float(meta.get("msr_price_band_high") or 25000.0)
    market.msr_price_band_low = float(meta.get("msr_price_band_low") or 15000.0)
    market.msr_surplus_upper_ratio = float(meta.get("msr_surplus_upper_ratio") or 0.18)
    market.msr_surplus_lower_ratio = float(meta.get("msr_surplus_lower_ratio") or 0.05)
    market.msr_max_intake_mt = float(meta.get("msr_max_intake_mt") or 20.0)
    market.msr_max_release_mt = float(meta.get("msr_max_release_mt") or 20.0)
    market.msr_initial_reserve_mt = float(meta.get("msr_initial_reserve_mt") or 0.0)
    market.msr_start_year = float(meta.get("msr_start_year") or 0.0)
    market.ccr_start_year = float(meta.get("ccr_start_year") or 0.0)
    # Attach CCR settings (Carbon Cap Rule)
    market.ccr_enabled = bool(meta.get("ccr_enabled", False))
    market.ccr_phi_emissions = float(meta.get("ccr_phi_emissions") or 0.0)
    market.ccr_phi_abatement_cost = float(meta.get("ccr_phi_abatement_cost") or 0.0)
    market.ccr_reference_emissions = float(meta.get("ccr_reference_emissions") or 0.0)
    market.ccr_reference_abatement_cost = float(meta.get("ccr_reference_abatement_cost") or 0.0)
    # Attach solver settings
    market.solver_competitive_max_iters = int(meta.get("solver_competitive_max_iters") or 25)
    market.solver_competitive_tolerance = float(meta.get("solver_competitive_tolerance") or 0.001)
    market.solver_hotelling_max_bisection_iters = int(meta.get("solver_hotelling_max_bisection_iters") or 80)
    market.solver_hotelling_max_lambda_expansions = int(meta.get("solver_hotelling_max_lambda_expansions") or 20)
    market.solver_hotelling_convergence_tol = float(meta.get("solver_hotelling_convergence_tol") or 0.0001)
    market.solver_nash_price_step = float(meta.get("solver_nash_price_step") or 0.5)
    market.solver_nash_max_iters = int(meta.get("solver_nash_max_iters") or 120)
    market.solver_nash_convergence_tol = float(meta.get("solver_nash_convergence_tol") or 0.001)
    market.solver_hotelling_lambda_initial_low   = float(meta.get("solver_hotelling_lambda_initial_low") or 0.001)
    market.solver_hotelling_lambda_initial_high  = float(meta.get("solver_hotelling_lambda_initial_high") or 20.0)
    market.solver_hotelling_lambda_expand_factor = float(meta.get("solver_hotelling_lambda_expand_factor") or 3.0)
    market.solver_price_bracket_expand_factor    = float(meta.get("solver_price_bracket_expand_factor") or 2.0)
    market.solver_price_bracket_max_expansions   = int(meta.get("solver_price_bracket_max_expansions") or 10)
    market.solver_slsqp_max_iters                = int(meta.get("solver_slsqp_max_iters") or 400)
    market.solver_slsqp_ftol                     = float(meta.get("solver_slsqp_ftol") or 1e-9)
    market.solver_nash_inner_xatol               = float(meta.get("solver_nash_inner_xatol") or 1e-4)
    market.solver_calibration_xatol              = float(meta.get("solver_calibration_xatol") or 0.1)
    market.solver_calibration_fatol              = float(meta.get("solver_calibration_fatol") or 0.01)
    return market


def build_participant(participant: dict[str, Any]) -> MarketParticipant:
    technology_options = [
        build_technology_option(item) for item in participant.get("technology_options", [])
    ]
    if participant["abatement_type"] == "linear":
        marginal_abatement_cost = linear_abatement_factory(
            max_abatement=participant["max_abatement"],
            cost_slope=participant["cost_slope"],
        )
        max_abatement_share = 1.0
    elif participant["abatement_type"] == "piecewise":
        marginal_abatement_cost = piecewise_abatement_factory(
            participant["mac_blocks"]
        )
        initial_emissions = participant["initial_emissions"]
        max_abatement = sum(
            float(block["amount"]) for block in participant["mac_blocks"]
        )
        max_abatement_share = 0.0
        if initial_emissions > 0:
            max_abatement_share = min(1.0, max_abatement / initial_emissions)
    else:
        initial_emissions = participant["initial_emissions"]
        max_abatement_share = 0.0
        if initial_emissions > 0:
            max_abatement_share = min(
                1.0, participant["max_abatement"] / initial_emissions
            )
        marginal_abatement_cost = participant["threshold_cost"]

    return MarketParticipant(
        name=participant["name"],
        initial_emissions=participant["initial_emissions"],
        marginal_abatement_cost=marginal_abatement_cost,
        free_allocation_ratio=participant["free_allocation_ratio"],
        penalty_price=participant["penalty_price"],
        max_abatement_share=max_abatement_share,
        technology_options=technology_options or None,
        cbam_export_share=float(participant.get("cbam_export_share") or 0.0),
        cbam_coverage_ratio=float(participant.get("cbam_coverage_ratio") or 1.0),
        cbam_jurisdictions=list(participant.get("cbam_jurisdictions") or []),
        sector_group=str(participant.get("sector_group") or ""),
        sector_allocation_share=float(participant.get("sector_allocation_share") or 0.0),
        electricity_consumption=float(participant.get("electricity_consumption") or 0.0),
        grid_emission_factor=float(participant.get("grid_emission_factor") or 0.0),
        scope2_cbam_coverage=float(participant.get("scope2_cbam_coverage") or 0.0),
        production_output=float(participant.get("production_output") or 0.0),
        benchmark_emission_intensity=float(participant.get("benchmark_emission_intensity") or 0.0),
        output_price_elasticity=float(participant.get("output_price_elasticity") or 0.0),
    )


def build_technology_option(option: dict[str, Any]) -> TechnologyOption:
    if option["abatement_type"] == "linear":
        marginal_abatement_cost = linear_abatement_factory(
            max_abatement=option["max_abatement"],
            cost_slope=option["cost_slope"],
        )
        max_abatement_share = 1.0
    elif option["abatement_type"] == "piecewise":
        marginal_abatement_cost = piecewise_abatement_factory(option["mac_blocks"])
        max_abatement = sum(float(block["amount"]) for block in option["mac_blocks"])
        max_abatement_share = 0.0
        if option["initial_emissions"] > 0:
            max_abatement_share = min(1.0, max_abatement / option["initial_emissions"])
    else:
        marginal_abatement_cost = option["threshold_cost"]
        max_abatement_share = 0.0
        if option["initial_emissions"] > 0:
            max_abatement_share = min(
                1.0, option["max_abatement"] / option["initial_emissions"]
            )

    return TechnologyOption(
        name=option["name"],
        initial_emissions=option["initial_emissions"],
        free_allocation_ratio=option["free_allocation_ratio"],
        penalty_price=option["penalty_price"],
        marginal_abatement_cost=marginal_abatement_cost,
        max_abatement_share=max_abatement_share,
        max_activity_share=option["max_activity_share"],
        fixed_cost=option["fixed_cost"],
    )
