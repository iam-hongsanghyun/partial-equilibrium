from __future__ import annotations

from scipy.optimize import root_scalar

from .model import CarbonMarket


def total_net_demand(
    market: CarbonMarket,
    carbon_price: float,
    bank_balances: dict[str, float] | None = None,
    expected_future_price: float = 0.0,
) -> float:
    return sum(
        _participant_outcome(
            market,
            participant,
            carbon_price,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        ).net_allowances_traded
        for participant in market.participants
    )


def _participant_outcome(
    market: CarbonMarket,
    participant,
    carbon_price: float,
    bank_balances: dict[str, float] | None = None,
    expected_future_price: float = 0.0,
):
    starting_bank_balance = 0.0
    if bank_balances is not None:
        starting_bank_balance = float(bank_balances.get(participant.name, 0.0))
    return participant.optimize_compliance(
        carbon_price,
        starting_bank_balance=starting_bank_balance,
        expected_future_price=expected_future_price,
        banking_allowed=market.banking_allowed,
        borrowing_allowed=market.borrowing_allowed,
        borrowing_limit=market.borrowing_limit,
        slsqp_max_iters=getattr(market, "solver_slsqp_max_iters", 400),
        slsqp_ftol=getattr(market, "solver_slsqp_ftol", 1e-9),
    )


def _solve_for_supply(
    market: CarbonMarket,
    target_supply: float,
    lower_bound: float,
    upper_bound: float,
    bank_balances: dict[str, float] | None,
    expected_future_price: float,
) -> float:
    f_low = total_net_demand(
        market, lower_bound,
        bank_balances=bank_balances,
        expected_future_price=expected_future_price,
    ) - target_supply
    f_high = total_net_demand(
        market, upper_bound,
        bank_balances=bank_balances,
        expected_future_price=expected_future_price,
    ) - target_supply

    expansion_count = 0
    max_expansions = getattr(market, "solver_price_bracket_max_expansions", 10)
    expand_factor  = getattr(market, "solver_price_bracket_expand_factor", 2.0)
    while f_low * f_high > 0 and expansion_count < max_expansions:
        upper_bound *= expand_factor
        f_high = total_net_demand(
            market, upper_bound,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        ) - target_supply
        expansion_count += 1

    if f_low * f_high > 0:
        raise RuntimeError(
            f"Could not bracket equilibrium price for {market.scenario_name}. "
            f"target_supply={target_supply:.2f}, "
            f"condition({lower_bound})={f_low:.2f}, condition({upper_bound})={f_high:.2f}"
        )

    solution = root_scalar(
        lambda carbon_price: total_net_demand(
            market, carbon_price,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
        ) - target_supply,
        bracket=[lower_bound, upper_bound],
        method="brentq",
    )

    if not solution.converged:
        raise RuntimeError(
            f"Market clearing did not converge for {market.scenario_name}."
        )

    return float(solution.root)


def solve_equilibrium(
    market: CarbonMarket,
    lower_bound: float = 0.0,
    upper_bound: float | None = None,
    bank_balances: dict[str, float] | None = None,
    expected_future_price: float = 0.0,
    carry_forward_in: float = 0.0,
) -> dict[str, float]:
    if lower_bound == 0.0 and market.price_lower_bound is not None:
        lower_bound = market.price_lower_bound

    if upper_bound is None:
        if market.price_upper_bound is not None:
            upper_bound = market.price_upper_bound
        else:
            max_penalty = max(
                participant.penalty_price for participant in market.participants
            )
            upper_bound = max_penalty * market.penalty_price_multiplier

    floor_price = max(lower_bound, market.auction_reserve_price)
    offered = market.effective_auction_offered(carry_forward_in)

    def demand_at(price: float) -> float:
        return max(
            0.0,
            total_net_demand(
                market, price,
                bank_balances=bank_balances,
                expected_future_price=expected_future_price,
            ),
        )

    if offered <= 0.0:
        sold = 0.0
        unsold = 0.0
        price = _solve_for_supply(
            market, 0.0, lower_bound, upper_bound, bank_balances, expected_future_price,
        )
        return {
            "price": price,
            "auction_offered": offered,
            "auction_sold": sold,
            "unsold_allowances": unsold,
            "coverage_ratio": 1.0,
        }

    demand_floor = demand_at(floor_price)
    if demand_floor + 1e-9 < offered:
        coverage = demand_floor / offered if offered > 0 else 1.0
        if coverage < market.minimum_bid_coverage:
            sold = 0.0
            unsold = offered
            price = _solve_for_supply(
                market, 0.0, lower_bound, upper_bound, bank_balances, expected_future_price,
            )
        else:
            sold = demand_floor
            unsold = max(0.0, offered - sold)
            price = floor_price
        return {
            "price": price,
            "auction_offered": offered,
            "auction_sold": sold,
            "unsold_allowances": unsold,
            "coverage_ratio": coverage,
        }

    price = _solve_for_supply(
        market, offered, floor_price, upper_bound, bank_balances, expected_future_price,
    )
    return {
        "price": price,
        "auction_offered": offered,
        "auction_sold": offered,
        "unsold_allowances": 0.0,
        "coverage_ratio": 1.0,
    }
