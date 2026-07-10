from __future__ import annotations

from typing import Any

from ..core.defaults import MSR_DEFAULTS, CCR_DEFAULTS


def blank_config() -> dict[str, Any]:
    return {"scenarios": [blank_scenario()]}


def blank_sector() -> dict[str, Any]:
    return {
        "name": "New Sector",
        "cap_trajectory": {},
        "auction_share_trajectory": {},
        "carbon_budget": 0.0,
    }


def blank_scenario() -> dict[str, Any]:
    return {
        "name": "New Scenario",
        "model_approach": "competitive",
        "discount_rate": 0.04,
        "risk_premium": 0.0,
        # Option A: reference (undistorted) carbon price anchoring the
        # price-elastic baseline. 0 disables the channel for the whole scenario.
        "reference_carbon_price": 0.0,
        "nash_strategic_participants": [],
        # ── Free-allocation phase-out trajectories ───────────────────────────
        # List of {participant_name, start_year, end_year, start_ratio, end_ratio}
        "free_allocation_trajectories": [],
        # ── Policy cap and price-bound trajectories ──────────────────────────
        # Each: {start_year, end_year, start_value, end_value} — empty dict = disabled
        "cap_trajectory": {},            # auto-declining total_cap
        "price_floor_trajectory": {},    # rising price floor (MSR / carbon floor)
        "price_ceiling_trajectory": {},  # declining/rising price ceiling
        # ── Sector-level allocation ──────────────────────────────────────────
        "sectors": [],
        # ── MSR settings ────────────────────────────────────────────────────
        **MSR_DEFAULTS,
        # ── CCR settings (Carbon Cap Rule — Benmir, Roman & Taschini 2025) ───
        **CCR_DEFAULTS,
        # ── Solver / model settings (all user-overridable) ──────────────────
        # Competitive perfect-foresight iteration
        "solver_competitive_max_iters": 25,
        "solver_competitive_tolerance": 0.001,
        # Hotelling bisection
        "solver_hotelling_max_bisection_iters": 80,
        "solver_hotelling_max_lambda_expansions": 20,
        "solver_hotelling_convergence_tol": 0.0001,
        # Nash best-response iteration
        "solver_nash_price_step": 0.5,
        "solver_nash_max_iters": 120,
        "solver_nash_convergence_tol": 0.001,
        # Market clearing
        "solver_penalty_price_multiplier": 1.25,
        # Hotelling λ bracket
        "solver_hotelling_lambda_initial_low": 0.001,
        "solver_hotelling_lambda_initial_high": 20.0,
        "solver_hotelling_lambda_expand_factor": 3.0,
        # Price bracket expansion
        "solver_price_bracket_expand_factor": 2.0,
        "solver_price_bracket_max_expansions": 10,
        # Mixed technology SLSQP
        "solver_slsqp_max_iters": 400,
        "solver_slsqp_ftol": 1e-9,
        # Nash inner best-response minimiser
        "solver_nash_inner_xatol": 1e-4,
        # Calibration (Nelder-Mead)
        "solver_calibration_xatol": 0.1,
        "solver_calibration_fatol": 0.01,
        "years": [blank_year_config()],
    }


def blank_year_config() -> dict[str, Any]:
    return {
        "year": "2030",
        "total_cap": 0.0,
        "carbon_budget": 0.0,
        "auction_mode": "explicit",
        "auction_offered": 0.0,
        "reserved_allowances": 0.0,
        "cancelled_allowances": 0.0,
        "auction_reserve_price": 0.0,
        "minimum_bid_coverage": 0.0,
        "unsold_treatment": "reserve",
        "price_lower_bound": 0.0,
        "price_upper_bound": 100.0,
        "banking_allowed": False,
        "borrowing_allowed": False,
        "borrowing_limit": 0.0,
        "expectation_rule": "next_year_baseline",
        "manual_expected_price": 0.0,
        "eua_price": 0.0,
        "eua_prices": {},           # per-jurisdiction: {"EU": 65, "UK": 50}
        "eua_price_ensemble": {},   # named trajectories: {"EC": 65, "Enerdata": 70, "BNEF": 80}
        "participants": [],
    }


def blank_participant() -> dict[str, Any]:
    return {
        "name": "New Participant",
        "initial_emissions": 0.0,
        "free_allocation_ratio": 0.0,
        "penalty_price": 0.0,
        "abatement_type": "linear",
        "max_abatement": 0.0,
        "cost_slope": 1.0,
        "threshold_cost": 0.0,
        "mac_blocks": [],
        "technology_options": [],
        "cbam_export_share": 0.0,
        "cbam_coverage_ratio": 1.0,
        "cbam_jurisdictions": [],   # [{name, export_share, coverage_ratio}] overrides single fields
        "sector_group": "",
        "sector_allocation_share": 0.0,
        # Scope 2 / indirect emissions
        "electricity_consumption": 0.0,  # MWh
        "grid_emission_factor": 0.0,     # tCO2/MWh
        "scope2_cbam_coverage": 0.0,     # 0–1
        # BAU emissions trajectory — auto-overrides initial_emissions year by year
        "initial_emissions_trajectory": {},
        # Grid emission factor trajectory — auto-overrides grid_emission_factor year by year
        "grid_emission_factor_trajectory": {},
        # Output-based allocation (OBA) / benchmark
        "production_output": 0.0,              # units/yr (e.g. Mt steel)
        "benchmark_emission_intensity": 0.0,   # tCO2/unit
        # Option A: price-elastic baseline — activity contracts as the carbon
        # price rises above the scenario's reference_carbon_price. 0 disables.
        "output_price_elasticity": 0.0,        # ε ≥ 0 (dimensionless)
    }


def blank_technology_option() -> dict[str, Any]:
    option = blank_participant()
    option["name"] = "New Technology"
    option["fixed_cost"] = 0.0
    option["max_activity_share"] = 1.0
    option.pop("technology_options", None)
    return option


def convergence_scenario_template(
    current_kau: float,
    target_eua: float,
    start_year: str,
    end_year: str,
    total_cap: float = 500.0,
) -> dict[str, Any]:
    """
    Return a scenario config snippet that ramps the domestic price floor
    from current_kau toward target_eua over [start_year, end_year].

    Args:
        current_kau: Current KAU (domestic ETS) price floor (e.g. 18.0).
        target_eua: Target EUA (EU ETS) price level (e.g. 85.0).
        start_year: First year of ramp (str, e.g. "2026").
        end_year: Final year of ramp (str, e.g. "2035").
        total_cap: Default total cap in Mt (used as placeholder; override via years).

    Returns:
        A scenario dict with price_floor_trajectory set to ramp current_kau -> target_eua.
    """
    s = blank_scenario()
    s["name"] = f"KAU-EUA Convergence ({start_year}-{end_year})"
    s["price_floor_trajectory"] = {
        "start_year": start_year,
        "end_year": end_year,
        "start_value": current_kau,
        "end_value": target_eua,
    }
    return s
