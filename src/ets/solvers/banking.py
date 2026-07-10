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

Supply-rule composition
-----------------------
Bank-triggered rules (MSR) and price-triggered rules (reserve-price floor with
unsold-volume cancellation) depend on the solved path, so the solver iterates:
solve path → recompute the rules' supply schedule from the new bank/prices →
re-solve, until the schedule is stable (see ``solve_banking_path``). Rules
read only beginning-of-year state (previous bank), never same-year outcomes.
"""

from __future__ import annotations

import logging

from scipy.optimize import brentq

from ..market import CarbonMarket
from ..market.equilibrium import total_net_demand
from .msr import MSRState

logger = logging.getLogger(__name__)

# Solver defaults (overridable via scenario config fields of the same name).
BANKING_DEFAULTS = {
    "banking_initial_bank": 0.0,       # Mt CO2e carried into the first year
    "banking_strict_no_arbitrage": True,
    "banking_bank_tolerance": 1e-6,    # Mt; interior bank >= -tol
    "banking_supply_rule_max_iters": 25,
    "banking_supply_rule_tolerance": 1e-3,  # Mt; schedule fixed-point tol
}


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


def _hoarding_inflow(market: CarbonMarket) -> float:
    """Exogenous hoarding inflow h_t [Mt CO2e] withdrawn from circulation.

    Reduced-form representation of structural hoarding in a λ ≈ 0 market
    (K-MSR paper §3–4: compliance entities bank against future tightening
    without pricing the carry — the registry banked-to-certified ratio rising
    0.03 → 0.17). Hoarded volume clears out of the year's supply (raising the
    static price), accumulates in the aggregate bank, and re-enters the
    window budget when the drawdown window opens. Year field
    ``hoarding_inflow``; default 0 (no hoarding, textbook equilibrium).
    """
    return float(getattr(market, "hoarding_inflow", 0.0) or 0.0)


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
) -> tuple[list[float], tuple[int, int] | None]:
    """Find the banking window and price path for a fixed supply schedule.

    Searches candidate windows (earliest start, then longest extent), solving
    the window budget for each and validating bank non-negativity and the
    boundary no-arbitrage inequalities (see module docstring).

    Args:
        markets: Markets sorted chronologically.
        g: Effective carry rate r + ρ [1/yr].
        initial_bank: Bank carried into the first year [Mt CO2e].
        supplies: Circulating supply per year [Mt CO2e], same order as
            ``markets``.
        strict: Reject boundary no-arbitrage violations (see module
            docstring).
        bank_tol: Interior bank non-negativity tolerance [Mt CO2e].

    Returns:
        ``(prices, window)`` — the per-year price path and the chosen window
        as ``(a, b)`` indices, or ``(static_prices, None)`` when no valid
        window exists (pure static equilibrium).
    """
    n = len(markets)
    hoarding = [_hoarding_inflow(m) for m in markets]
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


def _decree_msr_action(
    market: CarbonMarket,
    mode: str,
    prev_price: float | None,
    prev_surplus_ratio: float | None,
    reserve_stock: float,
) -> tuple[float, float]:
    r"""K-MSR draft-decree action for one year: (intake, release) in Mt.

    Ports the decree parameterization published in the PLANiT K-ETS Outlook
    dashboard (kets-outlook ``src/lib/msr.ts``, K-ETS MSR policy: Phase-4
    reserve 85.277 Mt, price band 15,000–25,000 KRW, surplus-ratio band
    5 %–18 %, max intake/release 20 Mt/yr) and matching the K-MSR paper's P1
    ("absorb above a trigger, release 20 Mt/yr thereafter, no cancellation").

    Algorithm:
        ASCII: price signal   — prev_price >= high → release;
                                 prev_price <= low  → intake
               surplus signal — prev_surplus >= upper ratio → intake;
                                 prev_surplus <= lower ratio → release
               mode price_band / surplus_rule uses its own signal;
               hybrid takes the majority of the two signals (ties → neutral);
               release is capped by the reserve stock, intake by max_intake.

    Both signals read PREVIOUS-year state (the decree acts on observed
    outcomes); the first year is always neutral.

    Args:
        market: The year's market (carries the ``msr_*`` decree fields).
        mode: ``"price_band"`` | ``"surplus_rule"`` | ``"hybrid"``.
        prev_price: Previous year's solved price [currency/tCO2]; None in the
            first year.
        prev_surplus_ratio: Previous end-of-year bank over previous residual
            emissions [dimensionless]; None in the first year.
        reserve_stock: Reserve stock at the start of the year [Mt CO2e].

    Returns:
        ``(intake, release)`` in Mt CO2e; at most one is non-zero.
    """
    if prev_price is None or prev_surplus_ratio is None:
        return 0.0, 0.0

    high = float(getattr(market, "msr_price_band_high", 25_000.0))
    low = float(getattr(market, "msr_price_band_low", 15_000.0))
    upper = float(getattr(market, "msr_surplus_upper_ratio", 0.18))
    lower = float(getattr(market, "msr_surplus_lower_ratio", 0.05))
    max_intake = float(getattr(market, "msr_max_intake_mt", 20.0))
    max_release = float(getattr(market, "msr_max_release_mt", 20.0))

    def price_signal() -> int:  # +1 release, -1 intake, 0 neutral
        if prev_price >= high:
            return 1
        if prev_price <= low:
            return -1
        return 0

    def surplus_signal() -> int:
        if prev_surplus_ratio <= lower:
            return 1
        if prev_surplus_ratio >= upper:
            return -1
        return 0

    if mode == "price_band":
        signal = price_signal()
    elif mode == "surplus_rule":
        signal = surplus_signal()
    else:  # hybrid: majority of the two signals, ties neutral
        total = price_signal() + surplus_signal()
        signal = 0 if total == 0 else (1 if total > 0 else -1)

    if signal > 0:
        return 0.0, min(max_release, max(0.0, reserve_stock))
    if signal < 0:
        return max_intake, 0.0
    return 0.0, 0.0


def _supply_schedule(
    markets: list[CarbonMarket],
    prices: list[float],
    bank: list[float],
    initial_bank: float,
) -> tuple[list[float], list[dict[str, float]]]:
    """Recompute per-year supply from bank-/price-triggered rules.

    Applies, in this order (each reads only beginning-of-year state):
      1. MSR — withhold/release against the previous end-of-year bank
         (``msr_*`` scenario fields, as in the competitive path).
      2. Reserve-price floor — where the floor exceeds the solved price, the
         auction sells only the demand at the floor; unsold volume is removed
         from circulating supply when ``unsold_treatment == "cancel"``.

    Returns the adjusted supply schedule and per-year diagnostics.
    """
    n = len(markets)
    supplies = [_circulating_supply(m) for m in markets]
    diags: list[dict[str, float]] = [
        {"msr_withheld": 0.0, "msr_released": 0.0, "msr_pool": 0.0,
         "floor_unsold_cancelled": 0.0}
        for _ in range(n)
    ]

    m0 = markets[0]
    msr_enabled = bool(getattr(m0, "msr_enabled", False))
    msr_mode = str(getattr(m0, "msr_mode", "bank_threshold") or "bank_threshold")
    msr_state = MSRState() if (msr_enabled and msr_mode == "bank_threshold") else None
    decree_reserve = float(getattr(m0, "msr_initial_reserve_mt", 0.0) or 0.0)

    for t, market in enumerate(markets):
        if msr_enabled and msr_mode != "bank_threshold":
            begin_bank = initial_bank if t == 0 else bank[t - 1]
            intake, release = _decree_msr_action(
                market=market,
                mode=msr_mode,
                prev_price=prices[t - 1] if t > 0 else None,
                prev_surplus_ratio=(
                    begin_bank
                    / max(1e-9, _residual_emissions(markets[t - 1], prices[t - 1]))
                    if t > 0
                    else None
                ),
                reserve_stock=decree_reserve,
            )
            decree_reserve += intake - release
            supplies[t] = (
                _free_allocation_total(market)
                + float(market.auction_offered)
                - intake
                + release
            )
            diags[t]["msr_withheld"] = intake
            diags[t]["msr_released"] = release
            diags[t]["msr_pool"] = decree_reserve
        elif msr_state is not None:
            begin_bank = initial_bank if t == 0 else bank[t - 1]
            adj_auction, withheld, released = msr_state.apply(
                total_bank=begin_bank,
                auction_offered=float(market.auction_offered),
                upper_threshold=float(getattr(market, "msr_upper_threshold", 200.0)),
                lower_threshold=float(getattr(market, "msr_lower_threshold", 50.0)),
                withhold_rate=float(getattr(market, "msr_withhold_rate", 0.12)),
                release_rate=float(getattr(market, "msr_release_rate", 50.0)),
                cancel_excess=bool(getattr(market, "msr_cancel_excess", False)),
                cancel_threshold=float(getattr(market, "msr_cancel_threshold", 400.0)),
                year_label=str(market.year),
            )
            supplies[t] = _free_allocation_total(market) + adj_auction
            diags[t]["msr_withheld"] = withheld
            diags[t]["msr_released"] = released
            diags[t]["msr_pool"] = msr_state.reserve_pool

        floor = float(getattr(market, "auction_reserve_price", 0.0) or 0.0)
        if floor > prices[t] and market.unsold_treatment == "cancel":
            demand_at_floor = _residual_emissions(market, floor)
            unsold = max(0.0, supplies[t] - demand_at_floor)
            supplies[t] -= unsold
            diags[t]["floor_unsold_cancelled"] = unsold

    return supplies, diags


def solve_banking_path(
    ordered_markets: list[CarbonMarket],
    discount_rate: float = 0.055,
    risk_premium: float = 0.0,
    initial_bank: float | None = None,
    strict_no_arbitrage: bool | None = None,
) -> list[dict]:
    r"""Solve the banking equilibrium path, composing supply rules to a fixed point.

    Algorithm:
        ASCII: repeat { solve window equilibrium for supply schedule S;
                        S' = supply_rules(prices, bank); } until |S' - S| small
        then price overlays: P_delivered(t) = max(P_t, floor_t).

    See the module docstring for the window equilibrium itself.

    Args:
        ordered_markets: Markets sorted chronologically.
        discount_rate: Risk-free rate r [1/yr].
        risk_premium: Policy risk premium ρ added to r [1/yr].
        initial_bank: Bank carried into the first year [Mt CO2e]. Defaults to
            the scenario field ``banking_initial_bank`` (0 if unset).
        strict_no_arbitrage: Boundary-validity mode; defaults to the scenario
            field ``banking_strict_no_arbitrage`` (True if unset).

    Returns:
        Path details in the ``_simulate_path_details`` structure, with
        banking diagnostics per year (aggregate bank, regime, window, MSR and
        floor-cancellation adjustments).
    """
    if not ordered_markets:
        raise ValueError("solve_banking_path requires at least one market.")

    m0 = ordered_markets[0]
    g = float(discount_rate) + float(risk_premium)
    if g < 0.0:
        raise ValueError(
            f"Banking requires a non-negative carry rate; got r + ρ = {g}."
        )
    if initial_bank is None:
        initial_bank = float(getattr(m0, "banking_initial_bank", 0.0) or 0.0)
    if strict_no_arbitrage is None:
        strict_no_arbitrage = bool(
            getattr(m0, "banking_strict_no_arbitrage", True)
        )
    bank_tol = float(
        getattr(m0, "banking_bank_tolerance", BANKING_DEFAULTS["banking_bank_tolerance"])
    )
    max_iters = int(
        getattr(
            m0,
            "banking_supply_rule_max_iters",
            BANKING_DEFAULTS["banking_supply_rule_max_iters"],
        )
    )
    schedule_tol = float(
        getattr(
            m0,
            "banking_supply_rule_tolerance",
            BANKING_DEFAULTS["banking_supply_rule_tolerance"],
        )
    )

    n = len(ordered_markets)
    supplies = [_circulating_supply(m) for m in ordered_markets]
    diags = [
        {"msr_withheld": 0.0, "msr_released": 0.0, "msr_pool": 0.0,
         "floor_unsold_cancelled": 0.0}
        for _ in range(n)
    ]
    prices: list[float] = []
    window: tuple[int, int] | None = None
    bank: list[float] = []

    has_rules = bool(getattr(m0, "msr_enabled", False)) or any(
        float(getattr(m, "auction_reserve_price", 0.0) or 0.0) > 0.0
        for m in ordered_markets
    )

    for iteration in range(max_iters):
        prices, window = solve_banking_window(
            ordered_markets, g, initial_bank, supplies,
            strict=strict_no_arbitrage, bank_tol=bank_tol,
        )
        bank = _bank_path(ordered_markets, prices, supplies, initial_bank)
        if not has_rules:
            break
        new_supplies, diags = _supply_schedule(
            ordered_markets, prices, bank, initial_bank
        )
        max_delta = max(abs(a - b) for a, b in zip(new_supplies, supplies))
        logger.debug(
            f"Banking supply-rule iteration {iteration}: max Δsupply = "
            f"{max_delta:.4f} Mt"
        )
        supplies = new_supplies
        if max_delta <= schedule_tol:
            prices, window = solve_banking_window(
                ordered_markets, g, initial_bank, supplies,
                strict=strict_no_arbitrage, bank_tol=bank_tol,
            )
            bank = _bank_path(ordered_markets, prices, supplies, initial_bank)
            break
    else:
        logger.warning(
            "Banking: supply-rule composition did not converge within "
            f"{max_iters} iterations; using the last iterate."
        )

    # Price overlay: reserve-price floor clips the delivered price last.
    delivered = [
        max(p, float(getattr(m, "auction_reserve_price", 0.0) or 0.0))
        for p, m in zip(prices, ordered_markets)
    ]

    details: list[dict] = []
    participant_bank = {p.name: 0.0 for p in m0.participants}
    for t, market in enumerate(ordered_markets):
        next_price = delivered[t + 1] if t + 1 < n else delivered[t]
        starting_bank = dict(participant_bank)
        participant_df = market.participant_results(
            delivered[t],
            bank_balances=participant_bank,
            expected_future_price=next_price,
        )
        offered = float(market.auction_offered)
        demand = float(participant_df["Net Allowances Traded"].sum())
        sold = min(offered, max(0.0, demand))
        in_window = window is not None and window[0] <= t <= window[1]
        details.append(
            {
                "market": market,
                "expected_future_price": next_price,
                "starting_bank_balances": starting_bank,
                "equilibrium": {
                    "price": delivered[t],
                    "auction_offered": offered,
                    "auction_sold": sold,
                    "unsold_allowances": max(0.0, offered - sold),
                    "coverage_ratio": (sold / offered) if offered > 0 else 1.0,
                },
                "participant_df": participant_df,
                "msr_withheld": diags[t]["msr_withheld"],
                "msr_released": diags[t]["msr_released"],
                "msr_pool": diags[t]["msr_pool"],
                "banking_aggregate_bank": bank[t],
                "banking_regime": "hotelling" if in_window else "static",
                "banking_window_start": window[0] if window else -1,
                "banking_window_end": window[1] if window else -1,
                "banking_floor_cancelled": diags[t]["floor_unsold_cancelled"],
            }
        )
        participant_bank = {
            str(row["Participant"]): float(row["Ending Bank Balance"])
            for _, row in participant_df.iterrows()
        }

    return details
