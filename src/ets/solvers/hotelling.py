"""
Hotelling Rule solver for ETS.

The Hotelling Rule treats emission allowances as an exhaustible resource.
The optimal price path must rise at the effective discount rate (arbitrage condition):

    P*(t) = λ · (1 + r + ρ)^(t - t₀)

where:
  λ  — shadow price (royalty) at the base year t₀
  r  — risk-free discount rate (discount_rate, e.g. 0.04 = 4%)
  ρ  — policy/market risk premium (risk_premium, e.g. 0.02 = 2%)

The risk premium ρ captures the additional return required by market participants
to hold allowances under policy uncertainty (e.g. future cap tightening ambiguity,
MSR rule changes, CBAM schedule revisions).  Setting ρ = 0 recovers the pure
Hotelling path.  A positive ρ steepens the price path relative to the risk-free
case, consistent with calibrating the model to observed market prices that rise
faster than the risk-free rate.

λ is chosen so that cumulative residual emissions equal the cumulative carbon
budget across all years.

Implementation: for each candidate λ we PIN each year's equilibrium price to the
Hotelling value by calling market.participant_results(P_hotelling(t)) directly.
We bisect on λ until cumulative residual emissions match the cumulative carbon
budget.
"""

from __future__ import annotations

import logging
from copy import deepcopy

import pandas as pd

from ..core.expectations import build_expectation_specs, derive_expected_prices

logger = logging.getLogger(__name__)

# Module-level defaults (used when caller does not supply solver settings)
_MAX_LAMBDA_EXPANSIONS = 20
_MAX_BISECTION_ITERS   = 80
_CONVERGENCE_TOL       = 1e-4   # relative tolerance on cumulative emissions


def _year_to_float(year_label: str) -> float:
    try:
        return float(year_label)
    except (TypeError, ValueError):
        return 0.0


def _hotelling_price(lam: float, effective_rate: float, t_offset: float) -> float:
    """Compute Hotelling price at offset t from base year.

    Parameters
    ----------
    lam : float
        Shadow price λ at base year.
    effective_rate : float
        Combined rate r + ρ  (discount_rate + risk_premium).
    t_offset : float
        Years elapsed since base year.
    """
    return max(0.0, lam * ((1.0 + effective_rate) ** t_offset))


def _simulate_at_hotelling_prices(
    ordered_markets,
    lam: float,
    effective_rate: float,
    base_year_num: float,
) -> tuple[list[dict], float]:
    """
    Simulate path by evaluating every participant DIRECTLY at the Hotelling price.

    In Hotelling mode the price is set by the shadow-price rule — we don't need
    the Brent market-clearing step.  Instead we:
      1. Compute P_hotelling(t) = λ · (1+r+ρ)^(t-t₀)
      2. Call market.participant_results(P_hotelling)  directly
      3. Propagate bank balances exactly as in the competitive path
    """
    bank_balances: dict[str, float] = {
        p.name: 0.0 for p in ordered_markets[0].participants
    }
    details: list[dict] = []

    for market in ordered_markets:
        t_offset     = _year_to_float(str(market.year)) - base_year_num
        p_hotelling  = _hotelling_price(lam, effective_rate, t_offset)
        # Clamp to the scenario's own price bounds
        p_floor      = market.price_lower_bound or 0.0
        p_ceiling    = market.price_upper_bound or 1e9
        p_effective  = max(p_floor, min(p_ceiling, p_hotelling))

        # Next-year expected price follows the same Hotelling rule
        expected_future_price = _hotelling_price(lam, effective_rate, t_offset + 1.0)

        starting_bank = dict(bank_balances)
        participant_df = market.participant_results(
            p_effective,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        )

        # Build a synthetic equilibrium dict (no auction clearing needed)
        demand = float(participant_df["Net Allowances Traded"].sum())
        equilibrium = {
            "price":             p_effective,
            "auction_offered":   market.auction_offered,
            "auction_sold":      min(market.auction_offered, max(0.0, demand)),
            "unsold_allowances": max(0.0, market.auction_offered - demand),
            "coverage_ratio":    1.0,
        }

        details.append({
            "market":                market,
            "expected_future_price": expected_future_price,
            "starting_bank_balances": starting_bank,
            "equilibrium":           equilibrium,
            "participant_df":        participant_df,
            "msr_withheld":          0.0,
            "msr_released":          0.0,
            "msr_pool":              0.0,
        })

        bank_balances = {
            str(row["Participant"]): float(row["Ending Bank Balance"])
            for _, row in participant_df.iterrows()
        }

    total_emissions = sum(
        float(item["participant_df"]["Residual Emissions"].sum())
        for item in details
    )
    return details, total_emissions


def _competitive_fallback(ordered_markets) -> list[dict]:
    from .msr import MSRState
    from .simulation import _simulate_path_details
    specs    = build_expectation_specs(ordered_markets)
    baseline = {str(m.year): m.find_equilibrium_price() for m in ordered_markets}
    expected = derive_expected_prices(
        [str(m.year) for m in ordered_markets], specs, baseline
    )
    msr_state = MSRState() if getattr(ordered_markets[0], "msr_enabled", False) else None
    return _simulate_path_details(ordered_markets, expected, msr_state=msr_state)


def solve_hotelling_path(
    ordered_markets,
    discount_rate: float = 0.04,
    risk_premium: float = 0.0,
    max_bisection_iters: int = _MAX_BISECTION_ITERS,
    max_lambda_expansions: int = _MAX_LAMBDA_EXPANSIONS,
    convergence_tol: float = _CONVERGENCE_TOL,
) -> list[dict]:
    """
    Find shadow price λ and simulate the Hotelling-optimal path.

    Parameters
    ----------
    ordered_markets : list[CarbonMarket]
        Markets sorted chronologically.
    discount_rate : float
        Risk-free annual discount rate r (e.g. 0.04 = 4%).
    risk_premium : float
        Policy/market risk premium ρ (e.g. 0.02 = 2%).  Added to discount_rate
        to form the effective growth rate used in the Hotelling price formula:
        P*(t) = λ · (1 + r + ρ)^(t − t₀).  Defaults to 0 (pure Hotelling).
        A positive value steepens the price path and is useful when calibrating
        to observed market prices that rise faster than the risk-free rate.

    Returns
    -------
    list[dict]
        Same structure as _simulate_path_details — one dict per year.
    """
    if not ordered_markets:
        return []

    # ── Validate carbon_budget ─────────────────────────────────────────────
    # Hotelling requires a cumulative carbon budget to bisect on.
    # Warn loudly if every year's carbon_budget is zero (common config mistake).
    total_explicit_budget = sum(
        float(getattr(m, "carbon_budget", 0.0) or 0.0) for m in ordered_markets
    )
    total_cap_sum = sum(float(m.total_cap) for m in ordered_markets)
    if total_explicit_budget <= 0.0:
        logger.warning(
            "Hotelling: carbon_budget is 0 for all years in scenario "
            f"'{ordered_markets[0].scenario_name}'. "
            "The solver will fall back to total_cap as the budget "
            f"(cumulative cap = {total_cap_sum:.1f} Mt). "
            "For a meaningful Hotelling path, set carbon_budget per year "
            "to your target cumulative emissions budget."
        )

    year_nums     = [_year_to_float(str(m.year)) for m in ordered_markets]
    base_year_num = year_nums[0]

    # Effective growth rate = risk-free rate + policy risk premium
    effective_rate = float(discount_rate) + float(risk_premium)
    if risk_premium != 0.0:
        logger.debug(
            f"Hotelling: effective rate = {effective_rate:.4f} "
            f"(discount_rate={discount_rate:.4f} + risk_premium={risk_premium:.4f})"
        )

    # Total carbon budget: per-year carbon_budget field; fall back to total_cap
    total_budget = sum(
        float(getattr(m, "carbon_budget", None) or m.total_cap or 0)
        for m in ordered_markets
    )
    if total_budget <= 0:
        total_budget = sum(float(m.total_cap) for m in ordered_markets)

    def run(lam):
        return _simulate_at_hotelling_prices(
            ordered_markets, lam, effective_rate, base_year_num
        )

    # ── Bracket λ ────────────────────────────────────────────────────────────
    # Higher λ  →  higher prices  →  more abatement  →  lower residual emissions
    # We need: emissions(lam_low) > budget  AND  emissions(lam_high) < budget

    m0 = ordered_markets[0]
    lam_low  = float(getattr(m0, "solver_hotelling_lambda_initial_low",  0.001))
    lam_high = float(getattr(m0, "solver_hotelling_lambda_initial_high", 20.0))
    lam_expand_factor = float(getattr(m0, "solver_hotelling_lambda_expand_factor", 3.0))

    _, em_low  = run(lam_low)
    _, em_high = run(lam_high)

    # Shrink lam_low until emissions exceed budget
    for _ in range(max_lambda_expansions):
        if em_low > total_budget:
            break
        lam_low /= 2.0
        _, em_low = run(lam_low)

    # Expand lam_high until emissions fall below budget
    for _ in range(max_lambda_expansions):
        if em_high < total_budget:
            break
        lam_high *= lam_expand_factor
        _, em_high = run(lam_high)

    if em_low <= total_budget or em_high >= total_budget:
        logger.warning(
            "Hotelling: could not bracket shadow price — falling back to competitive. "
            f"budget={total_budget:.1f}, em@λ_low={em_low:.1f}(λ={lam_low:.5f}), "
            f"em@λ_high={em_high:.1f}(λ={lam_high:.2f})"
        )
        return _competitive_fallback(ordered_markets)

    # ── Bisection on λ ───────────────────────────────────────────────────────
    best_details = None
    for _ in range(max_bisection_iters):
        lam_mid = (lam_low + lam_high) / 2.0
        details_mid, em_mid = run(lam_mid)
        best_details = details_mid

        if abs(em_mid - total_budget) / max(total_budget, 1.0) < convergence_tol:
            break

        if em_mid > total_budget:   # too many emissions → need higher price → higher λ
            lam_low = lam_mid
        else:
            lam_high = lam_mid

    return best_details or _competitive_fallback(ordered_markets)
