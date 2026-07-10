from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..costs import linear_abatement_factory, piecewise_abatement_factory
from ..market import CarbonMarket
from ..participant import MarketParticipant, TechnologyOption
from .normalize import (
    ALLOWED_MODEL_APPROACHES,
    normalize_participant,
    normalize_technology_option,
    normalize_year,
)
from .templates import blank_scenario, blank_year_config


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


def _validated_msr_mode(scenario: dict[str, Any]) -> str:
    mode = str(scenario.get("msr_mode") or "bank_threshold").strip()
    if mode not in _ALLOWED_MSR_MODES:
        raise ValueError(
            f"Scenario '{scenario.get('name')}': msr_mode must be one of "
            f"{sorted(_ALLOWED_MSR_MODES)}, got '{mode}'."
        )
    return mode


def normalize_scenario(raw_scenario: dict[str, Any]) -> dict[str, Any]:
    scenario = blank_scenario()
    scenario.update(raw_scenario)
    scenario["name"] = str(scenario["name"]).strip()
    if not scenario["name"]:
        raise ValueError("Each scenario must have a non-empty name.")

    years = scenario.get("years")
    if years is None:
        years = [_legacy_scenario_to_year(raw_scenario)]
    if not isinstance(years, list) or not years:
        raise ValueError(
            f"Scenario '{scenario['name']}' must contain a non-empty 'years' list."
        )

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
                f"Scenario '{scenario['name']}': forward_transmission_lambda must "
                f"be in [0, 1], got {transmission_lambda}."
            )

    return {
        "name": scenario["name"],
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
        # MSR
        "msr_enabled": bool(scenario.get("msr_enabled", False)),
        "msr_upper_threshold": _fval("msr_upper_threshold", 200.0),
        "msr_lower_threshold": _fval("msr_lower_threshold", 50.0),
        "msr_withhold_rate": _fval("msr_withhold_rate", 0.12),
        "msr_release_rate": _fval("msr_release_rate", 50.0),
        "msr_cancel_excess": bool(scenario.get("msr_cancel_excess", False)),
        "msr_cancel_threshold": _fval("msr_cancel_threshold", 400.0),
        # K-MSR decree modes (banking solver; kets-outlook msr.ts parameters)
        "msr_mode": _validated_msr_mode(scenario),
        "msr_price_band_high": _fval("msr_price_band_high", 25000.0),
        "msr_price_band_low": _fval("msr_price_band_low", 15000.0),
        "msr_surplus_upper_ratio": _fval("msr_surplus_upper_ratio", 0.18),
        "msr_surplus_lower_ratio": _fval("msr_surplus_lower_ratio", 0.05),
        "msr_max_intake_mt": _fval("msr_max_intake_mt", 20.0),
        "msr_max_release_mt": _fval("msr_max_release_mt", 20.0),
        "msr_initial_reserve_mt": _fval("msr_initial_reserve_mt", 0.0),
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


def _legacy_scenario_to_year(raw_scenario: dict[str, Any]) -> dict[str, Any]:
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


def build_markets_from_config(config: dict[str, Any]) -> list[CarbonMarket]:
    normalized = normalize_config(deepcopy(config))
    markets: list[CarbonMarket] = []
    for scenario in normalized["scenarios"]:
        scenario_meta = {
            "model_approach": scenario.get("model_approach", "competitive"),
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


def build_market_from_year(
    scenario_name: str,
    year_config: dict[str, Any],
    scenario_meta: dict[str, Any] | None = None,
) -> CarbonMarket:
    meta = scenario_meta or {}
    year_num = _year_to_float(str(year_config.get("year", "2030")))
    trajectories = list(meta.get("free_allocation_trajectories") or [])
    sectors = list(meta.get("sectors") or [])

    # ── Sector-level derivation ──────────────────────────────────────────────
    # When sectors are defined, compute per-sector pools and derive total_cap /
    # auction_offered from the sum of sector caps.  Per-participant
    # free_allocation_ratio is derived here (on raw dicts) before building
    # MarketParticipant objects so the dataclass validation sees the final value.
    sector_pools: dict[str, float] = {}
    derived_total_cap: float | None = None
    derived_auction: float | None = None

    if sectors:
        _derived_total_cap = 0.0
        _derived_auction = 0.0
        for s in sectors:
            sname = s["name"]
            scap = _interp_value(year_num, s.get("cap_trajectory") or {})
            if scap is None:
                # Fall back to summing participant initial_emissions for this sector
                scap = sum(
                    float(p.get("initial_emissions", 0))
                    for p in year_config.get("participants", [])
                    if str(p.get("sector_group", "")) == sname
                )
            sauc_share = _interp_value(year_num, s.get("auction_share_trajectory") or {}) or 0.0
            sauc = scap * sauc_share
            sector_pools[sname] = scap - sauc
            _derived_total_cap += scap
            _derived_auction += sauc
        derived_total_cap = _derived_total_cap
        derived_auction = _derived_auction

        # Patch raw participant dicts with sector-derived free_allocation_ratio
        # (we work on a shallow copy to avoid mutating the caller's config)
        raw_participants = []
        for p in year_config.get("participants", []):
            sg = str(p.get("sector_group", ""))
            sas = float(p.get("sector_allocation_share", 0.0) or 0.0)
            ie = float(p.get("initial_emissions", 0) or 0)
            if sg in sector_pools and sas > 0 and ie > 0:
                pool = sector_pools[sg]
                allocated_mt = pool * sas
                derived_ratio = min(1.0, allocated_mt / ie)
                raw_participants.append({**p, "free_allocation_ratio": derived_ratio})
            else:
                raw_participants.append(p)
    else:
        raw_participants = list(year_config.get("participants", []))

    # Apply initial_emissions_trajectory and grid_emission_factor_trajectory per participant
    patched_participants = []
    for p in raw_participants:
        p = dict(p)  # shallow copy to avoid mutating caller's data
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
        patched_participants.append(p)
    raw_participants = patched_participants

    # Apply Output-Based Allocation (OBA) overrides BEFORE building participants
    # free_allocation = benchmark_emission_intensity × production_output
    # This overrides free_allocation_ratio when both OBA fields are set.
    oba_patched = []
    for p in raw_participants:
        po = float(p.get("production_output") or 0.0)
        bei = float(p.get("benchmark_emission_intensity") or 0.0)
        ie = float(p.get("initial_emissions") or 0.0)
        if po > 0 and bei > 0 and ie > 0:
            free_alloc_mt = bei * po
            p = {**p, "free_allocation_ratio": min(1.0, free_alloc_mt / ie)}
        oba_patched.append(p)
    raw_participants = oba_patched

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
    reference_carbon_price = float(meta.get("reference_carbon_price") or 0.0)
    if reference_carbon_price > 0.0:
        for participant in participants:
            participant.reference_carbon_price = reference_carbon_price

    free_allocations = sum(participant.free_allocation for participant in participants)
    reserved_allowances = float(year_config.get("reserved_allowances", 0.0))
    cancelled_allowances = float(year_config.get("cancelled_allowances", 0.0))

    # Apply cap / price-bound trajectories — override per-year values
    total_cap = float(year_config["total_cap"])
    price_lower_bound = year_config.get("price_lower_bound")
    price_upper_bound = year_config.get("price_upper_bound")
    cap_override = _interp_value(year_num, meta.get("cap_trajectory") or {})
    floor_override = _interp_value(year_num, meta.get("price_floor_trajectory") or {})
    ceiling_override = _interp_value(year_num, meta.get("price_ceiling_trajectory") or {})
    if cap_override is not None:
        total_cap = cap_override
    if floor_override is not None:
        price_lower_bound = floor_override
    if ceiling_override is not None:
        price_upper_bound = ceiling_override

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
    # Attach scenario-level and year-level modelling approach fields
    market.model_approach = meta.get("model_approach", "competitive")
    market.discount_rate = float(meta.get("discount_rate") or 0.04)
    market.risk_premium = float(meta.get("risk_premium") or 0.0)
    _ftl = meta.get("forward_transmission_lambda")
    market.forward_transmission_lambda = None if _ftl is None else float(_ftl)
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
