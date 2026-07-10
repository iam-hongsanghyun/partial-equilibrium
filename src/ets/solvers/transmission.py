r"""Forward-transmission blending (λ) of static and Hotelling price paths.

Reference
---------
PLANiT, "Leading Carbon Prices to an Irreversible Industrial Transition:
Instrument Choice for a Market Stability Reserve under Weak Forward
Transmission" (working paper, July 2026), Sections 3 and 5.

The paper formalizes a market's *forward-transmission capacity* as a
reduced-form coefficient λ ∈ [0, 1] mapping the theoretical inter-temporal
(Hotelling) price into the realized price. λ = 0 is a market that prices no
inter-temporal carry (the paper's empirical reading of the KAU market:
realized cross-vintage carry ≈ 0 %/yr against a 5.5 %/yr Hotelling
benchmark); λ = 1 is full Hotelling pricing. The paper stress-tests three
regimes: relapse (λ → 0), hold (λ ≈ 0.55), consolidate (λ → 0.9).

Algorithm
---------
LaTeX:
$$
P^{\text{blend}}_t = (1-\lambda)\,P^{\text{comp}}_t + \lambda\,P^{\text{hot}}_t
\qquad
P^{\text{delivered}}_t = \max\!\left(P^{\text{blend}}_t,\; F_t\right)
$$

ASCII fallback:
    P_blend(t)     = (1 - lambda) * P_comp(t) + lambda * P_hot(t)
    P_delivered(t) = max(P_blend(t), F_t)

Symbols (units):
    lambda        : forward-transmission coefficient, dimensionless in [0, 1]
    P_comp(t)     : static year-by-year competitive clearing price with the
                    reserve floor REMOVED (the no-policy market-clearing
                    component)                                  [currency/tCO2]
    P_hot(t)      : Hotelling path price on the same floor-stripped markets,
                    P_hot(t) = shadow_price * (1 + r + rho)^(t - t0)
                                                                [currency/tCO2]
    F_t           : auction reserve price (floor) of year t; 0 when unset
                                                                [currency/tCO2]
    P_delivered(t): realized price reported for the scenario    [currency/tCO2]

Order of operations — the transmission-immunity property
---------------------------------------------------------
The floor is applied AFTER blending (blend → clip), never before. This is what
reproduces the paper's two joint properties:

  1. λ-independent floor: the delivered price never falls below F_t regardless
     of λ, because the floor is enforced at the primary auction, outside the
     forward-transmission channel (the paper's Layer-1 theorem).
  2. λ-dependent price above the floor: where the blend clears above F_t, the
     delivered level varies with λ (only the counterfactual lift over
     no-policy depends on transmission).

Clipping the components before blending would instead deliver
(1-λ)·F_t + λ·P_hot > F_t in floor-bound years — a different (wrong) object.

Scope: λ here is a reduced-form summary of market frictions, exactly as the
paper frames it — it blends *prices*; it does not feed back into abatement or
investment decisions (that would leave partial equilibrium; see the repo's
coupling module for soft-link feedback). MSR/CCR adjustments, if enabled,
apply inside the competitive component only.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from ..market import CarbonMarket

logger = logging.getLogger(__name__)


def blend_prices(p_competitive: float, p_hotelling: float, lam: float) -> float:
    r"""Convex-combine the static and Hotelling prices.

    Algorithm:
        $$P^{blend} = (1-\lambda) P^{comp} + \lambda P^{hot}$$
        ASCII: P_blend = (1 - lam) * p_competitive + lam * p_hotelling

    Args:
        p_competitive: Static clearing price [currency/tCO2].
        p_hotelling: Hotelling path price [currency/tCO2].
        lam: Forward-transmission coefficient λ, dimensionless in [0, 1].

    Returns:
        Blended price [currency/tCO2].

    Raises:
        ValueError: If ``lam`` is outside [0, 1].
    """
    if not 0.0 <= lam <= 1.0:
        raise ValueError(f"forward_transmission_lambda must be in [0, 1], got {lam}")
    return (1.0 - lam) * float(p_competitive) + lam * float(p_hotelling)


def _strip_floors(ordered_markets: list[CarbonMarket]) -> list[CarbonMarket]:
    """Deep-copy markets with the auction reserve price removed.

    The blend components are the *no-floor* paths; the floor re-enters only as
    the final max() clip (see module docstring on operation order).
    """
    stripped = []
    for market in ordered_markets:
        copy = deepcopy(market)
        copy.auction_reserve_price = 0.0
        stripped.append(copy)
    return stripped


def _path_prices(path_details: list[dict]) -> dict[str, float]:
    """Extract {year_label: equilibrium price} from a solved path."""
    return {
        str(item["market"].year): float(item["equilibrium"]["price"])
        for item in path_details
    }


def _evaluate_at_prices(
    ordered_markets: list[CarbonMarket],
    delivered_prices: dict[str, float],
    diagnostics: dict[str, dict[str, float]],
    lam: float,
) -> list[dict]:
    """Evaluate every market year at its delivered (pinned) price.

    Mirrors the Hotelling solver's direct evaluation: no Brent clearing step —
    the price is given, participants optimize against it, and bank balances
    propagate year to year. The synthetic auction outcome accounts for a
    binding floor: demand below the offered volume leaves unsold allowances,
    which the year's ``unsold_treatment`` then disposes of (Rule A cancels).

    Args:
        ordered_markets: Markets sorted chronologically (floors intact).
        delivered_prices: Year label → delivered price [currency/tCO2].
        diagnostics: Year label → component prices for reporting.
        lam: λ used, recorded on each year's result row.

    Returns:
        Path details in the same structure as ``_simulate_path_details``.
    """
    bank_balances: dict[str, float] = {
        p.name: 0.0 for p in ordered_markets[0].participants
    }
    year_labels = [str(m.year) for m in ordered_markets]
    details: list[dict] = []

    for index, market in enumerate(ordered_markets):
        year = str(market.year)
        price = float(delivered_prices[year])
        next_year = year_labels[index + 1] if index + 1 < len(year_labels) else year
        expected_future_price = float(delivered_prices[next_year])

        starting_bank = dict(bank_balances)
        participant_df = market.participant_results(
            price,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        )

        demand = float(participant_df["Net Allowances Traded"].sum())
        offered = float(market.auction_offered)
        sold = min(offered, max(0.0, demand))
        equilibrium = {
            "price": price,
            "auction_offered": offered,
            "auction_sold": sold,
            "unsold_allowances": max(0.0, offered - sold),
            "coverage_ratio": (sold / offered) if offered > 0 else 1.0,
        }

        diag = diagnostics[year]
        details.append(
            {
                "market": market,
                "expected_future_price": expected_future_price,
                "starting_bank_balances": starting_bank,
                "equilibrium": equilibrium,
                "participant_df": participant_df,
                "msr_withheld": 0.0,
                "msr_released": 0.0,
                "msr_pool": 0.0,
                "transmission_lambda": lam,
                "static_component_price": diag["competitive"],
                "hotelling_component_price": diag["hotelling"],
                "reserve_floor_price": diag["floor"],
            }
        )

        bank_balances = {
            str(row["Participant"]): float(row["Ending Bank Balance"])
            for _, row in participant_df.iterrows()
        }

    return details


def solve_transmission_path(
    ordered_markets: list[CarbonMarket],
    lam: float,
    discount_rate: float = 0.04,
    risk_premium: float = 0.0,
    **hotelling_kwargs: Any,
) -> list[dict]:
    r"""Solve the λ-blended (forward-transmission) delivered price path.

    Algorithm:
        $$
        P^{delivered}_t=\max\big((1-\lambda)P^{comp}_t+\lambda P^{hot}_t,\,F_t\big)
        $$
        ASCII: P_delivered(t) = max((1-lam)*P_comp(t) + lam*P_hot(t), F_t)

    where both components are solved with the reserve floor removed, and the
    floor F_t (each year's ``auction_reserve_price``) clips the blend last —
    see the module docstring for why this order is load-bearing.

    Args:
        ordered_markets: Markets sorted chronologically.
        lam: Forward-transmission coefficient λ, dimensionless in [0, 1].
        discount_rate: Risk-free rate r used by the Hotelling component
            [1/yr].
        risk_premium: Policy risk premium ρ added to r in the Hotelling
            component [1/yr].
        **hotelling_kwargs: Extra keyword arguments forwarded to
            ``solve_hotelling_path`` (bisection iterations, tolerances).

    Returns:
        Path details in the same structure as ``_simulate_path_details``,
        priced at the delivered path, with per-year component diagnostics
        (``static_component_price``, ``hotelling_component_price``,
        ``reserve_floor_price``, ``transmission_lambda``).

    Raises:
        ValueError: If ``lam`` is outside [0, 1] or no markets are given.
    """
    if not ordered_markets:
        raise ValueError("solve_transmission_path requires at least one market.")
    if not 0.0 <= lam <= 1.0:
        raise ValueError(f"forward_transmission_lambda must be in [0, 1], got {lam}")

    # Lazy imports to avoid circular dependency (simulation ↔ transmission).
    from .hotelling import solve_hotelling_path
    from .simulation import solve_scenario_path

    competitive_path = solve_scenario_path(_strip_floors(ordered_markets))
    hotelling_path = solve_hotelling_path(
        _strip_floors(ordered_markets),
        discount_rate=discount_rate,
        risk_premium=risk_premium,
        **hotelling_kwargs,
    )

    p_comp = _path_prices(competitive_path)
    p_hot = _path_prices(hotelling_path)

    delivered: dict[str, float] = {}
    diagnostics: dict[str, dict[str, float]] = {}
    for market in ordered_markets:
        year = str(market.year)
        floor = float(getattr(market, "auction_reserve_price", 0.0) or 0.0)
        blended = blend_prices(p_comp[year], p_hot[year], lam)
        delivered[year] = max(blended, floor)  # blend FIRST, clip at floor LAST
        diagnostics[year] = {
            "competitive": p_comp[year],
            "hotelling": p_hot[year],
            "floor": floor,
        }
        logger.debug(
            f"λ-blend [{year}]: comp={p_comp[year]:.1f}, hot={p_hot[year]:.1f}, "
            f"λ={lam:.2f} → blend={blended:.1f}, floor={floor:.1f}, "
            f"delivered={delivered[year]:.1f}"
        )

    return _evaluate_at_prices(ordered_markets, delivered, diagnostics, lam)
