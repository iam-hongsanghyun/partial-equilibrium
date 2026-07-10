r"""Banking supply-rule fixed point (T2 runtime, engine/host-facing).

Supply-rule composition
-----------------------
Bank-triggered rules (MSR) and price-triggered rules (reserve-price floor with
unsold-volume cancellation) depend on the solved path, so the solver iterates:
solve path → recompute the rules' supply schedule from the new bank/prices →
re-solve, until the schedule is stable (see ``solve_banking_path``). Rules
read only beginning-of-year state (previous bank), never same-year outcomes.

Since work order O6 the MSR rules are INJECTED as ``SupplyRuleFactory``
objects (``ets.core.protocols``): a fresh rule instance is constructed at the
top of every schedule evaluation, keeping evaluations pure across fixed-point
iterations and solver invocations while the rule stays stateful across years
within one evaluation. The rules live in ``features/msr/``
(``DecreeSupplyRule``, ``ThresholdMSRSupplyRule``). Since work order O10 the
floor-cancellation step is ``features.price_controls.rules
.FloorCancellationRule``, called from a DEDICATED host slot in its fixed
position — after the MSR rules, inside the fixed point (F4 — evaluation
timing inside the fixed point is part of the equilibrium definition, not an
implementation detail); the delivered-price clip is
``features.price_controls.plugin.DeliveredFloor`` (clip-LAST); and the
hoarding inflow schedule is read through an injected
``core.protocols.Friction`` (``features.hoarding.plugin.HoardingInflow``) —
only the reader moved, the hoarding HOST SET stays in ``window.py``
(static-year ``S_t − h_t``, window-start constraint, prune exemption, bank
accumulation; Arbitration outcomes O10).

Moved from ``solvers/banking.py`` in the banking feature order (v1 O9 /
v2 O13). This feature imports ONLY the kernel and its own siblings (tier
law), so every cross-feature object above reaches it by INJECTION: the
engine-bound entry point (``ets.engine.wiring.solve_banking_path``, exported
as ``ets.engine.solve_banking_path``) resolves the default supply-rule
factories, floor-rule factory, friction, and delivered-price overlay, then
delegates here. ``ets/solvers/banking.py`` re-exports the engine-bound name.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ...core.defaults import BANKING_DEFAULTS
from ...core.protocols import Observables
from .window import (
    _bank_path,
    _circulating_supply,
    _residual_emissions,
    solve_banking_window,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from ...core.market import CarbonMarket
    from ...core.protocols import Friction, PriceOverlay, SupplyRule, SupplyRuleFactory

logger = logging.getLogger(__name__)


@runtime_checkable
class FloorRule(Protocol):
    """The banking host's dedicated floor-cancellation slot contract.

    Deliberately NOT ``core.protocols.SupplyRule`` (economist verdict 1c on
    PLAN v2): the slot reads the CONTEMPORANEOUS year's price from the
    previous fixed-point iterate, not the lagged ``Observables``. The host
    owns this contract; ``features.price_controls.rules
    .FloorCancellationRule`` implements it and the engine injects it — a
    feature cannot import another feature, so the type is declared
    structurally here.
    """

    def apply_to_year(
        self, market: CarbonMarket, solved_price: float, supply: float
    ) -> tuple[float, float]:
        """Return ``(replacement_supply, cancelled)`` for one year [Mt CO2e]."""
        ...


def _supply_schedule(
    markets: list[CarbonMarket],
    prices: list[float],
    bank: list[float],
    initial_bank: float,
    supply_rule_factories: Sequence[SupplyRuleFactory],
    floor_rule_factory: Callable[[], FloorRule],
) -> tuple[list[float], list[dict[str, float]]]:
    """Recompute per-year supply from bank-/price-triggered rules.

    Applies, in this order (each reads only beginning-of-year state):
      1. MSR — withhold/release against the previous end-of-year bank
         (``msr_*`` scenario fields, as in the competitive path).
      2. Reserve-price floor — where the floor exceeds the solved price, the
         auction sells only the demand at the floor; unsold volume is removed
         from circulating supply when ``unsold_treatment == "cancel"``.

    The MSR step is an injected ``SupplyRule`` (work order O6): every rule is
    constructed FRESH from its factory at the top of each evaluation, so a
    schedule evaluation is a pure function of ``(prices, bank)`` — the same
    inputs give the same schedule regardless of how many fixed-point
    iterations preceded it (lifecycle doctrine, ``ets.core.protocols``). The
    HOST computes the lagged ``Observables`` (beginning-of-year bank,
    previous solved price, previous surplus ratio via
    ``_residual_emissions``) and each rule returns the year's REPLACEMENT
    circulating supply.

    The floor-cancellation step (O10) is
    ``features.price_controls.rules.FloorCancellationRule``, called from
    this DEDICATED slot — not the ``SupplyRule`` list — because it reads the
    CONTEMPORANEOUS year's price from the previous fixed-point iterate, not
    the lagged ``Observables`` (economist verdict 1c; the ``FloorRule``
    slot contract above). Its position is load-bearing economics: AFTER the
    MSR adjustment, on the MSR-adjusted supply, inside the fixed point
    (MSR-then-floor, ``docs/blocks-composition-rules.md`` §2 item 3).

    Args:
        markets: Markets sorted chronologically.
        prices: Previous iterate's solved price path [currency/tCO2].
        bank: Previous iterate's end-of-year aggregate bank path [Mt CO2e].
        initial_bank: Bank carried into the first year [Mt CO2e].
        supply_rule_factories: Zero-argument constructors of fresh
            ``SupplyRule`` instances, applied per year in list order.
        floor_rule_factory: Zero-argument constructor of the fresh
            floor-cancellation rule for this evaluation.

    Returns:
        The adjusted supply schedule and per-year diagnostics.
    """
    n = len(markets)
    supplies = [_circulating_supply(m) for m in markets]
    diags: list[dict[str, float]] = [
        {"msr_withheld": 0.0, "msr_released": 0.0, "msr_pool": 0.0,
         "floor_unsold_cancelled": 0.0}
        for _ in range(n)
    ]

    # Fresh rule instances per schedule evaluation — never reused across
    # fixed-point iterations or solver invocations (ets.core.protocols).
    rules: list[SupplyRule] = [factory() for factory in supply_rule_factories]
    floor_rule = floor_rule_factory()

    for t, market in enumerate(markets):
        if rules:
            begin_bank = initial_bank if t == 0 else bank[t - 1]
            obs = Observables(
                begin_bank=begin_bank,
                prev_price=prices[t - 1] if t > 0 else None,
                prev_surplus_ratio=(
                    begin_bank
                    / max(1e-9, _residual_emissions(markets[t - 1], prices[t - 1]))
                    if t > 0
                    else None
                ),
                year_label=str(market.year),
            )
            for rule in rules:
                supplies[t], rule_diags = rule.apply(market, obs)
                diags[t].update(rule_diags)

        # Dedicated floor-cancellation slot: AFTER the MSR rules, on the
        # MSR-adjusted supply (order is economics — see docstring).
        supplies[t], cancelled = floor_rule.apply_to_year(market, prices[t], supplies[t])
        diags[t]["floor_unsold_cancelled"] = cancelled

    return supplies, diags


def solve_banking_path(
    ordered_markets: list[CarbonMarket],
    discount_rate: float = 0.055,
    risk_premium: float = 0.0,
    initial_bank: float | None = None,
    strict_no_arbitrage: bool | None = None,
    supply_rule_factories: Sequence[SupplyRuleFactory] | None = None,
    floor_rule_factory: Callable[[], FloorRule] | None = None,
    friction: Friction | None = None,
    price_overlay: PriceOverlay | None = None,
) -> list[dict]:
    r"""Solve the banking equilibrium path, composing supply rules to a fixed point.

    Algorithm:
        ASCII: repeat { solve window equilibrium for supply schedule S;
                        S' = supply_rules(prices, bank); } until |S' - S| small
        then price overlays: P_delivered(t) = max(P_t, floor_t).

    See the module docstring for the window equilibrium itself.

    INJECTION CONTRACT (v1 O9 / v2 O13): the rule wiring is injected — this
    feature never resolves defaults itself. Callers go through the
    engine-bound entry point (``ets.engine.solve_banking_path``), which fills
    ``supply_rule_factories`` / ``floor_rule_factory`` / ``friction`` /
    ``price_overlay`` from ``ets.engine.wiring``'s reviewed defaults; the
    ``None`` defaults below exist only for signature stability and are NOT
    resolved here (a ``None`` floor-rule factory or price overlay will fail
    loudly; ``None`` rule factories compose no supply rules; ``None``
    friction reads no hoarding).

    Args:
        ordered_markets: Markets sorted chronologically.
        discount_rate: Risk-free rate r [1/yr].
        risk_premium: Policy risk premium ρ added to r [1/yr].
        initial_bank: Bank carried into the first year [Mt CO2e]. Defaults to
            the scenario field ``banking_initial_bank`` (0 if unset).
        strict_no_arbitrage: Boundary-validity mode; defaults to the scenario
            field ``banking_strict_no_arbitrage`` (True if unset).
        supply_rule_factories: Zero-argument constructors of the
            ``SupplyRule`` objects composed INSIDE the fixed point (F4);
            each factory is re-invoked at the top of every supply-schedule
            evaluation so rule state never leaks across iterations or solver
            invocations (``ets.core.protocols``). Pass an empty sequence
            for an explicitly MSR-free schedule (the floor-cancellation
            slot applies regardless).
        floor_rule_factory: Zero-argument constructor of the
            floor-cancellation rule evaluated in the host's dedicated slot
            AFTER the supply rules (O10; the ``FloorRule`` slot contract).
        friction: Hoarding-inflow provider threaded into the window solve
            (``core.protocols.Friction``); the hoarding HOST SET
            (static-year S_t − h_t, window-start constraint, prune
            exemption, bank accumulation) always stays in
            ``solve_banking_window``.
        price_overlay: Delivered-price transformation applied ONCE, LAST
            (clip-last, F3): the engine injects the reserve-price floor
            overlay (``DeliveredFloor``; attach-always is exact,
            max(p, 0) = p).

    Returns:
        Path details in the ``simulate_path_details`` structure, with
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

    has_rules = bool(supply_rule_factories) or any(
        float(getattr(m, "auction_reserve_price", 0.0) or 0.0) > 0.0
        for m in ordered_markets
    )

    for iteration in range(max_iters):
        prices, window = solve_banking_window(
            ordered_markets, g, initial_bank, supplies,
            strict=strict_no_arbitrage, bank_tol=bank_tol, friction=friction,
        )
        bank = _bank_path(ordered_markets, prices, supplies, initial_bank)
        if not has_rules:
            break
        new_supplies, diags = _supply_schedule(
            ordered_markets, prices, bank, initial_bank,
            supply_rule_factories, floor_rule_factory,
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
                strict=strict_no_arbitrage, bank_tol=bank_tol, friction=friction,
            )
            bank = _bank_path(ordered_markets, prices, supplies, initial_bank)
            break
    else:
        logger.warning(
            "Banking: supply-rule composition did not converge within "
            f"{max_iters} iterations; using the last iterate."
        )

    # Price overlay: the reserve-price floor clips the delivered price ONCE,
    # LAST (features.price_controls.plugin.DeliveredFloor; clip-last is the
    # F3 operation-order doctrine — attach-always is exact, max(p, 0) = p).
    # Injected by the engine-bound entry point since v1 O9 / v2 O13.
    delivered = [
        price_overlay.delivered(p, m) for p, m in zip(prices, ordered_markets)
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
