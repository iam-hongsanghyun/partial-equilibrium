r"""Rubin/Schennach banking equilibrium solver.

References
----------
- Rubin, J. D. (1996). "A model of intertemporal emission trading, banking,
  and borrowing." JEEM 31(3), 269–286.
- Schennach, S. M. (2000). "The economics of pollution permit banking in the
  context of Title IV." JEEM 40(3), 189–210.
- PLANiT K-MSR working paper (July 2026), Appendix A.1: with bankable permits,
  no borrowing, and competition, $P_t = P_0 (1+r)^t$ while the aggregate bank
  is positive; the level is pinned by the cumulative budget over the banking
  window, and the rule breaks when the bank is exhausted.

The solver computes the deterministic, risk-neutral banking equilibrium with
an **endogenous banking window** $[a, b]$:

Algorithm
---------
LaTeX:
$$
P_t = P_a (1+g)^{t-a} \;\; \forall t \in [a,b], \qquad
\sum_{t=a}^{b} e_t(P_t) = B_{a^-} + \sum_{t=a}^{b} S_t,
$$
$$
B_t = B_{a^-} + \sum_{s=a}^{t} \big(S_s - e_s(P_s)\big) \ge 0
\;\; \forall t \in [a,b), \qquad |B_b| \le \varepsilon,
$$

($B_b = 0$ exactly under continuous MACs; with discrete piecewise/threshold
MACs demand is a step correspondence, the window budget may be unattainable
exactly, and the terminal residual — bounded by the MAC block at the boundary
— is logged as a WARNING rather than silently accepted.)
with static year-by-year clearing $e_t(P_t) = S_t$ outside the window, and
no-arbitrage validity at both boundaries:
pre-window $P_{t+1} \le (1+g) P_t$ (no incentive to start banking earlier)
and post-window $P_{b+1} \le (1+g) P_b$ (no incentive to keep banking).

ASCII fallback:
    P_t = P_a * (1+g)^(t-a)                 for t in [a, b]   (banking window)
    sum_{t=a..b} e_t(P_t) = B_pre + sum_{t=a..b} S_t          (window budget)
    B_t >= 0 inside the window, B_b = 0                        (bank validity)
    e_t(P_t) = S_t                          outside the window (static years)
    P_{t+1} <= (1+g) * P_t at both window boundaries           (no-arbitrage)

Symbols (units):
    P_t   : allowance price in year t                       [currency/tCO2]
    g     : effective carry rate = discount_rate + risk_premium   [1/yr]
    e_t(p): residual emissions at price p (BAU minus abatement)   [Mt CO2e]
    S_t   : circulating supply = free allocation + auction volume [Mt CO2e]
    B_t   : aggregate bank at end of year t                       [Mt CO2e]
    B_a-  : bank carried into the window (initial_bank plus any
            pre-window accumulation; zero under pure static pre-years)
                                                                  [Mt CO2e]
    a, b  : first and last year of the banking window (endogenous)

The window is found by searching candidate (a, b) pairs — earliest feasible
start, longest valid extent — solving the window-budget equation for
$P_a$ by Brent root-finding, then checking bank non-negativity and the
boundary no-arbitrage inequalities.

Strictness modes
----------------
``strict_no_arbitrage=True`` (default) rejects candidate solutions whose
static segments violate the boundary inequalities and falls back to the pure
static path with a WARNING if no valid window exists (note: a rejection can
also mean the true equilibrium needs two disjoint banking windows, which this
single-window solver does not model). ``False`` keeps the earliest/longest
interior-feasible candidate and emits one aggregate WARNING — needed when
calibrating to markets that structurally hoard without pricing the carry (the
K-MSR paper's λ ≈ 0 reading of the KAU market, whose published P0 rises
faster than (1+g)^t while the bank is positive: a textbook-invalid but
empirically motivated shape).

Hoarding years are static-regime years **by definition**: the banking window
never starts at or before a year with ``hoarding_inflow > 0`` (the friction
is meaningless inside an arbitrage window), pre-window no-arbitrage checks
exempt transitions out of hoarding years, and the hoarded volume feeds the
window budget through the accumulated bank.

Moved from ``solvers/banking.py`` in the banking feature order (v1 O9 /
v2 O13, ``docs/feature-modules-plan.md``): this module holds the window
search and observables math; ``solver.py`` holds the supply-rule fixed
point (``solve_banking_path`` — see its docstring for the composition
doctrine); ``ets/solvers/banking.py`` remains as a re-export shim of the
engine-bound entry point.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from scipy.optimize import brentq

from ...core.market.clearing import total_net_demand

if TYPE_CHECKING:
    from ...core.market import CarbonMarket
    from ...core.protocols import Friction

logger = logging.getLogger(__name__)


def _free_allocation_total(market: CarbonMarket) -> float:
    return float(sum(p.free_allocation for p in market.participants))


def _circulating_supply(market: CarbonMarket) -> float:
    """Supply entering circulation in a year: free allocation + auction."""
    return _free_allocation_total(market) + float(market.auction_offered)


def _residual_emissions(market: CarbonMarket, price: float) -> float:
    """Residual emissions e_t(p) = net auction demand + free allocation.

    ``total_net_demand`` returns purchases beyond free allocation at a pinned
    price (banking handled by this solver, not by participants), so adding
    back the free allocation gives BAU-minus-abatement emissions.
    """
    return total_net_demand(market, price) + _free_allocation_total(market)


def _static_price(market: CarbonMarket, supply: float) -> float:
    r"""Static clearing price at a given circulating supply (no floor).

    Algorithm:
        ASCII: solve e_t(p) = supply for p by Brent root-finding.
    """
    upper = float(market.price_upper_bound or 0.0) or 1e7

    def excess(p: float) -> float:
        return _residual_emissions(market, p) - supply

    if excess(0.0) <= 0.0:
        return 0.0
    if excess(upper) > 0.0:
        logger.warning(
            f"Banking [{market.year}]: static clearing infeasible below the "
            f"price ceiling {upper:,.0f}; returning the ceiling."
        )
        return upper
    return float(brentq(excess, 0.0, upper, xtol=1e-6))


def _window_start_price(
    markets: list[CarbonMarket],
    a: int,
    b: int,
    g: float,
    incoming_bank: float,
    supplies: list[float],
    upper_bound: float,
) -> float | None:
    """Solve the window-budget equation for P_a on candidate window [a, b].

    Returns None when the budget cannot be bracketed (e.g. even a zero price
    over-abates, or the window is infeasibly tight at the price ceiling).
    """
    budget = incoming_bank + sum(supplies[a : b + 1])

    def excess(p_a: float) -> float:
        total = 0.0
        for t in range(a, b + 1):
            total += _residual_emissions(markets[t], p_a * (1.0 + g) ** (t - a))
        return total - budget

    lo, hi = 0.0, upper_bound
    f_lo, f_hi = excess(lo), excess(hi)
    if f_lo <= 0.0:
        # Supply covers BAU over the window even at a zero price. Tolerance is
        # quantity-scale (Mt), consistent with the schedule tolerance — a bare
        # 1e-9 would be dead code under the nested optimizers' noise floor.
        return 0.0 if abs(f_lo) < 1e-3 else None
    if f_hi > 0.0:
        return None
    return float(brentq(excess, lo, hi, xtol=1e-6))


def _bank_path(
    markets: list[CarbonMarket],
    prices: list[float],
    supplies: list[float],
    initial_bank: float,
) -> list[float]:
    """End-of-year aggregate bank B_t for a given price path."""
    bank = initial_bank
    path = []
    for t, market in enumerate(markets):
        bank += supplies[t] - _residual_emissions(market, prices[t])
        path.append(bank)
    return path


def solve_banking_window(
    markets: list[CarbonMarket],
    g: float,
    initial_bank: float,
    supplies: list[float],
    strict: bool,
    bank_tol: float,
    friction: Friction | None = None,
) -> tuple[list[float], tuple[int, int] | None]:
    """Find the banking window and price path for a fixed supply schedule.

    Searches candidate windows (earliest start, then longest extent), solving
    the window budget for each and validating bank non-negativity and the
    boundary no-arbitrage inequalities (see module docstring).

    The hoarding HOST SET lives in this function (Arbitration outcomes, O10,
    binding): the static-year supply reduction S_t − h_t, the window-start
    constraint a > max{t : h_t > 0}, the pre-window no-arbitrage prune
    exemption for hoarding years, and the accumulation of hoarded volume
    into the window budget are window-equilibrium math and never move to the
    hoarding feature — only the inflow schedule reader is injected.

    Args:
        markets: Markets sorted chronologically.
        g: Effective carry rate r + ρ [1/yr].
        initial_bank: Bank carried into the first year [Mt CO2e].
        supplies: Circulating supply per year [Mt CO2e], same order as
            ``markets``.
        strict: Reject boundary no-arbitrage violations (see module
            docstring).
        bank_tol: Interior bank non-negativity tolerance [Mt CO2e].
        friction: Hoarding-inflow provider (``core.protocols.Friction``),
            injected by the engine-bound entry point (attach-always: the
            hoarding feature's reader, exact for unconfigured markets —
            h_t = 0 without ``hoarding_inflow`` fields). ``None`` reads no
            hoarding (h_t = 0, the textbook equilibrium): a feature cannot
            construct another feature's reader (tier law), and the in-repo
            engine wiring never passes ``None``, so the neutral branch is
            reachable only by direct feature callers.

    Returns:
        ``(prices, window)`` — the per-year price path and the chosen window
        as ``(a, b)`` indices, or ``(static_prices, None)`` when no valid
        window exists (pure static equilibrium).
    """
    n = len(markets)
    # Neutral without an injected Friction: zero inflow — identical to the
    # attached reader on unconfigured markets (see Args above).
    hoarding = [friction.inflow(m) for m in markets] if friction is not None else [0.0] * n
    static = [
        _static_price(m, supplies[t] - hoarding[t]) for t, m in enumerate(markets)
    ]
    upper = max(
        float(m.price_upper_bound or 0.0) for m in markets
    ) or (max(static) * 10.0 + 1.0)

    # Hoarding years are static-regime years BY DEFINITION (they model the
    # λ ≈ 0 hoarding friction, which is meaningless inside an arbitrage
    # window). Restricting the window start past the last hoarding year both
    # keeps the documented semantics (hoarded volume feeds the window budget)
    # and removes the selection ambiguity of a window that could otherwise
    # swallow the hoarded year and silently ignore h_t.
    first_allowed_start = 0
    for t in range(n):
        if hoarding[t] > 0.0:
            first_allowed_start = t + 1
    if first_allowed_start > 0:
        logger.debug(
            f"Banking: hoarding years force the window start to index "
            f">= {first_allowed_start}."
        )

    best_relaxed: tuple[list[float], tuple[int, int]] | None = None

    for a in range(first_allowed_start, n):
        # Pre-window static segment must not tempt earlier banking. The check
        # covers transitions strictly inside the static segment (the a-1 → a
        # transition is checked against the actual solved window price below,
        # not against the hypothetical static[a]). Transitions out of a
        # hoarding year are exempt: the λ ≈ 0 friction is precisely a
        # documented no-arbitrage violation. Cheap, so prune here.
        pre_ok = all(
            static[t + 1] <= (1.0 + g) * static[t] + 1e-9
            for t in range(a - 1)
            if hoarding[t] == 0.0
        )
        if strict and not pre_ok:
            continue
        if best_relaxed is not None and not pre_ok:
            continue

        # Bank carried into the window: initial bank plus pre-window hoarding
        # (static years clear at S_t − h_t, so the bank grows by exactly h_t).
        incoming_bank = initial_bank + sum(hoarding[:a])

        for b in range(n - 1, a - 1, -1):  # prefer the longest window
            p_a = _window_start_price(
                markets, a, b, g, incoming_bank, supplies, upper
            )
            if p_a is None:
                continue
            prices = list(static)
            for t in range(a, b + 1):
                prices[t] = p_a * (1.0 + g) ** (t - a)

            bank = _bank_path(markets, prices, supplies, initial_bank)
            interior_ok = all(bank[t] >= -bank_tol for t in range(a, b + 1))
            if not interior_ok:
                continue

            # Terminal-bank diagnostic: with discrete (piecewise/threshold)
            # MACs, e_t(p) is a step function, so the window budget may be
            # unattainable exactly — brentq lands on a block boundary and the
            # residual equals the step size. Loud, never silent.
            if abs(bank[b]) > max(bank_tol, 1e-3):
                logger.warning(
                    f"Banking: terminal bank of window ({a}, {b}) is "
                    f"{bank[b]:.3f} Mt, not ~0 — discrete-MAC step demand "
                    "cannot meet the window budget exactly; the residual is "
                    "bounded by the largest MAC block at the boundary."
                )

            ceiling_violation = next(
                (
                    t
                    for t in range(a, b + 1)
                    if markets[t].price_upper_bound is not None
                    and prices[t] > float(markets[t].price_upper_bound) + 1e-9
                ),
                None,
            )
            if ceiling_violation is not None:
                logger.warning(
                    f"Banking: window price in year index {ceiling_violation} "
                    f"({prices[ceiling_violation]:,.0f}) exceeds that year's "
                    "price_upper_bound; the ceiling is not enforced inside "
                    "the banking window."
                )

            boundary_ok = pre_ok
            if a > 0 and prices[a] > (1.0 + g) * prices[a - 1] + 1e-9:
                boundary_ok = False  # banking should have started earlier
            if b + 1 < n and prices[b + 1] > (1.0 + g) * prices[b] + 1e-9:
                boundary_ok = False  # banking should have continued
            # Post-window static years must not tempt a second window
            # (single-window solver: a violation means the true window lies
            # later — keep searching).
            if any(
                static[t + 1] > (1.0 + g) * static[t] + 1e-9
                for t in range(b + 1, n - 1)
            ):
                boundary_ok = False

            if boundary_ok:
                return prices, (a, b)
            if best_relaxed is None:
                best_relaxed = (prices, (a, b))

    if best_relaxed is not None and not strict:
        prices, window = best_relaxed
        logger.warning(
            "Banking: no candidate window satisfies the boundary no-arbitrage "
            f"inequalities; keeping window {window} under "
            "banking_strict_no_arbitrage=False."
        )
        return prices, window

    if best_relaxed is not None:
        logger.warning(
            "Banking: candidate windows exist but violate boundary "
            "no-arbitrage; falling back to the pure static path "
            "(set banking_strict_no_arbitrage=False to keep the best candidate)."
        )
    return static, None

