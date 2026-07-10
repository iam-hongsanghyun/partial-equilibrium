from __future__ import annotations

from typing import Callable


def linear_abatement_factory(
    max_abatement: float, cost_slope: float
) -> Callable[[float], float]:
    """
    Creates a bounded linear abatement function q(p) = p / slope.
    """

    if max_abatement < 0 or cost_slope <= 0:
        raise ValueError(
            "max_abatement must be non-negative and cost_slope must be positive."
        )

    def abatement_rule(carbon_price: float) -> float:
        return min(max_abatement, max(0.0, carbon_price / cost_slope))

    setattr(abatement_rule, "cost_model", "linear")
    setattr(abatement_rule, "cost_slope", cost_slope)
    setattr(abatement_rule, "max_abatement", max_abatement)

    return abatement_rule


def piecewise_abatement_factory(
    mac_blocks: list[dict[str, float]],
) -> Callable[[float], float]:
    """
    Creates a stepwise abatement response from marginal abatement cost blocks.

    Each block should provide:
    - amount: block size in tons
    - marginal_cost: constant marginal cost for that block
    """

    if not mac_blocks:
        raise ValueError("mac_blocks must contain at least one block.")

    normalized_blocks: list[dict[str, float]] = []
    total_max = 0.0
    previous_cost = -float("inf")
    for block in mac_blocks:
        amount = float(block["amount"])
        marginal_cost = float(block["marginal_cost"])
        # amount must be non-negative; marginal_cost MAY be negative — negative-cost
        # ("no-regret") abatement measures are a standard MACC feature.
        if amount < 0:
            raise ValueError("MAC block amount must be non-negative.")
        if marginal_cost < previous_cost:
            raise ValueError("MAC blocks must be ordered by non-decreasing marginal_cost.")
        normalized_blocks.append(
            {"amount": amount, "marginal_cost": marginal_cost}
        )
        total_max += amount
        previous_cost = marginal_cost

    def abatement_rule(carbon_price: float) -> float:
        # Abate every block whose marginal cost the price covers. Negative-cost
        # blocks are undertaken even at a zero carbon price (they are net-saving).
        abatement = 0.0
        for block in normalized_blocks:
            if carbon_price >= block["marginal_cost"]:
                abatement += block["amount"]
            else:
                break
        return abatement

    setattr(abatement_rule, "cost_model", "piecewise")
    setattr(abatement_rule, "mac_blocks", normalized_blocks)
    setattr(abatement_rule, "max_abatement", total_max)

    return abatement_rule
