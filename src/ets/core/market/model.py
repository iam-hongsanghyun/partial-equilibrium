from __future__ import annotations

from ..participant import MarketParticipant


class CarbonMarket:
    def __init__(
        self,
        participants: list[MarketParticipant],
        total_cap: float,
        auction_offered: float,
        reserved_allowances: float = 0.0,
        cancelled_allowances: float = 0.0,
        auction_reserve_price: float = 0.0,
        minimum_bid_coverage: float = 0.0,
        unsold_treatment: str = "reserve",
        scenario_name: str = "Unnamed Scenario",
        year: str | None = None,
        price_lower_bound: float | None = None,
        price_upper_bound: float | None = None,
        banking_allowed: bool = False,
        borrowing_allowed: bool = False,
        borrowing_limit: float = 0.0,
        expectation_rule: str = "next_year_baseline",
        manual_expected_price: float = 0.0,
        penalty_price_multiplier: float = 1.25,
    ) -> None:
        if not participants:
            raise ValueError("CarbonMarket requires at least one participant.")
        if total_cap < 0 or auction_offered < 0 or reserved_allowances < 0 or cancelled_allowances < 0:
            raise ValueError("total_cap and allowance supply buckets must be non-negative.")

        self.participants = participants
        self.total_cap = float(total_cap)
        self.auction_offered = float(auction_offered)
        self.reserved_allowances = float(reserved_allowances)
        self.cancelled_allowances = float(cancelled_allowances)
        self.auction_reserve_price = float(auction_reserve_price)
        self.minimum_bid_coverage = float(minimum_bid_coverage)
        self.unsold_treatment = str(unsold_treatment)
        self.scenario_name = scenario_name
        self.year = year
        self.price_lower_bound = price_lower_bound
        self.price_upper_bound = price_upper_bound
        self.banking_allowed = banking_allowed
        self.borrowing_allowed = borrowing_allowed
        self.borrowing_limit = float(borrowing_limit)
        self.expectation_rule = str(expectation_rule)
        self.manual_expected_price = float(manual_expected_price)
        self.penalty_price_multiplier = float(penalty_price_multiplier)
        # CBAM / MSR — set post-construction via scenarios.py
        self.eua_price: float = 0.0          # external EUA reference price (EU default)
        self.eua_prices: dict = {}           # per-jurisdiction prices e.g. {"EU": 65, "UK": 50}
        self.eua_price_ensemble: dict = {}   # named EUA trajectories e.g. {"EC": 65, "Enerdata": 70}

        free_allocations = sum(participant.free_allocation for participant in participants)
        allowance_supply = (
            free_allocations
            + self.auction_offered
            + self.reserved_allowances
            + self.cancelled_allowances
        )
        self.unallocated_allowances = max(0.0, self.total_cap - allowance_supply)

        if allowance_supply - self.total_cap > 1e-9:
            raise ValueError(
                "Inconsistent cap setup: free allocations plus auctioned, reserved, and cancelled allowances "
                f"cannot exceed total_cap. Got {allowance_supply:.2f} vs {self.total_cap:.2f}."
            )

    def effective_auction_offered(self, carry_forward_in: float = 0.0) -> float:
        return max(0.0, self.auction_offered + float(carry_forward_in))

    def calculate_auction_revenue(
        self, equilibrium_price: float, auction_sold: float | None = None
    ) -> float:
        sold = self.auction_offered if auction_sold is None else float(auction_sold)
        return equilibrium_price * sold

    def find_equilibrium_price(
        self,
        lower_bound: float = 0.0,
        upper_bound: float | None = None,
        bank_balances: dict[str, float] | None = None,
        expected_future_price: float = 0.0,
        carry_forward_in: float = 0.0,
    ) -> float:
        return self.solve_equilibrium(
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            bank_balances=bank_balances,
            expected_future_price=expected_future_price,
            carry_forward_in=carry_forward_in,
        )["price"]
