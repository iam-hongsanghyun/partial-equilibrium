r"""price_controls runtime — the floor-cancellation supply rule (T2, engine/host-facing).

Runtime door of the two-door feature (``docs/feature-modules-plan.md`` PLAN
v2): imported by the banking host (transitionally; the wiring literal moves
to ``engine/wiring.py`` in the engine order), never by ``config_io``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...core.market.clearing import total_net_demand

if TYPE_CHECKING:
    from ...core.market.model import CarbonMarket


def _free_allocation_total(market: CarbonMarket) -> float:
    """Total free allocation of a year [Mt CO2e] (as in the banking host)."""
    return float(sum(p.free_allocation for p in market.participants))


class FloorCancellationRule:
    r"""Rule A: cancel auction volume unsold at the reserve-price floor.

    Rule A is the K-MSR paper's cancellation design — the one floor mechanism
    that defeats the waterbed under banking (``docs/blocks-composition-rules
    .md`` §1 Cancellation row): where a static-regime year's auction is
    oversupplied at the reserve floor, the auction sells only the demand at
    the floor, the price pins to the floor, and the unsold volume is REMOVED
    from circulating supply when ``unsold_treatment == "cancel"``.

    Binding test — the DIRECT COMPLEMENTARITY SOLVE (``docs/floor-cancellation
    -fix.md`` §2 PRIMARY). The reserve-price floor is a per-year
    complementarity, $0 \le (P_t - F_t) \perp u_t \ge 0$: either the floor is
    SLACK ($P_t > F_t$, $u_t = 0$) or it BINDS ($P_t = F_t$, $u_t = S_t -
    e_t(F_t)$). The equivalent, DISCONTINUITY-FREE binding condition is the
    CONTEMPORANEOUS test on FIXED quantities — **the floor binds iff
    demand-at-floor is below supply, $e_t(F_t) < S_t$** — identical to "the
    unconstrained price would fall below $F_t$" by monotonicity of $e_t(\cdot)$
    but with NO dependence on the oscillating previous-iterate price. This is
    the SAME boundary the competitive kernel solves directly without iterating
    (``core/market/clearing.py`` oversupply branch, ``demand_floor < offered``).

    The superseded predicate (work order O10, pre-fix) tested ``floor >
    solved_price`` — the PREVIOUS iterate's price with a STRICT inequality — a
    discontinuous proxy that is wrong exactly at the equilibrium ($P_t = F_t$):
    cancel supply -> next solve prices AT $F_t$ -> ``F_t > F_t`` flips False ->
    cancellation withdrawn -> price collapses below the floor -> cancel again,
    a period-2 supply orbit. Because $e_t(F_t)$ and base $S_t$ are FIXED across
    schedule iterations, the fixed-point-on-fixed-quantities test reaches its
    fixed point in <=2 evaluations with zero oscillation, landing on the
    complementarity boundary. See ``docs/floor-cancellation-fix.md`` §1.

    Algorithm:
        LaTeX:
        $$ u_t = \begin{cases}
              S_t - e_t(F_t) & \text{if } F_t > 0,\ \text{cancel},\
                                e_t(F_t) < S_t\quad(\text{floor binds})\\
              0 & \text{otherwise}
           \end{cases},\qquad S_t' = S_t - u_t = e_t(F_t)\text{ when binding.}$$

        ASCII fallback:
            demand_floor = e_t(F_t)              # net auction demand + free alloc, at F_t
            if unsold_treatment == "cancel" and F_t > 0 and demand_floor < S_t:
                unsold = S_t - demand_floor      # cancel the volume unsold at F_t
                supply = demand_floor            # year contributes e_t(F_t)
            else:
                unsold = 0                        # floor slack: full supply passes through

        Symbols (units):
            F_t      : year's auction_reserve_price          [currency/tCO2]
            e_t(F_t) : residual demand at the floor (net auction demand plus
                       free allocation) — the FIXED contemporaneous quantity
                                                             [Mt CO2e]
            S_t      : circulating supply entering the slot (already
                       MSR-adjusted)                         [Mt CO2e]
            u_t      : cancelled unsold volume               [Mt CO2e]

    Regime-aware host gating (``docs/floor-cancellation-fix.md`` §2 binding
    refinement, refined for the release valve): this rule is a WINDOW-BLIND,
    price-free complementarity; the banking HOST (``features.banking.solver
    ._supply_schedule``) decides WHICH years it is applied to.

    * STATIC-regime years: applied unconditionally — the price-free
      $e_t(F_t) < S_t$ test is exactly what removes the pre-fix orbit.
    * WINDOW-regime years: applied only where the floor CLIPS the arbitrage
      price ($F_t > P_t$); otherwise the surplus banks and nothing is unsold,
      so the floor is slack even when $e_t(F_t) < S_t$ locally. When the floor
      DOES clip a window year (investment/MSR drags the Hotelling path down to
      the floor — the release valve), the rule still cancels, so the
      supply-accounting identity $\sum e = \sum S - B_T - \sum u - \text{MSR}$
      holds. The window-year path is byte-identical to the pre-fix rule.

    CONTRACT (explicit, deliberately NOT ``core.protocols.SupplyRule`` —
    economist verdict 1c on PLAN v2): the banking host calls it from a
    DEDICATED slot, in its fixed position — AFTER the injected MSR supply
    rules, on the MSR-adjusted supply (MSR-then-floor,
    ``docs/blocks-composition-rules.md`` §2 item 3), inside the supply-schedule
    fixed point (F4) so cancellation feeds back into the window budget. The
    rule is stateless across years; the host constructs it fresh per schedule
    evaluation (factory slot) so the lifecycle is uniform with the
    ``SupplyRule`` family (``ets.core.protocols`` doctrine).

    The demand-at-floor call is the same expression as the banking host's
    ``_residual_emissions`` (net auction demand at a pinned price plus free
    allocation), computed here from kernel primitives so the feature imports
    only ``ets.core`` (tier contract).
    """

    def apply_to_year(
        self, market: CarbonMarket, solved_price: float, supply: float
    ) -> tuple[float, float]:
        r"""Cancel the volume unsold at the floor, if the floor binds.

        The binding decision is the CONTEMPORANEOUS complementarity test on
        FIXED quantities, $e_t(F_t) < S_t$ — it does NOT read ``solved_price``
        (retained only for the ``FloorRule`` slot-contract signature; the
        pre-fix predicate ``floor > solved_price`` was the source of the
        period-2 orbit, see the class docstring).

        Args:
            market: The year's market (``auction_reserve_price``,
                ``unsold_treatment``, demand-side fields).
            solved_price: The year's price from the previous fixed-point
                iterate [currency/tCO2]. UNUSED by the binding decision —
                see above.
            supply: The year's circulating supply $S_t$ entering this slot
                (already MSR-adjusted) [Mt CO2e].

        Returns:
            ``(supply, cancelled)`` — the replacement circulating supply
            after cancellation and the cancelled volume [Mt CO2e]. When the
            floor binds the supply is replaced by $e_t(F_t)$ and
            ``cancelled = S_t - e_t(F_t)``; otherwise ``(supply, 0.0)``
            unchanged (floor slack, no reserve floor, or
            ``unsold_treatment != "cancel"``).
        """
        del solved_price  # binding is decided on fixed quantities, not the lagged price
        floor = float(getattr(market, "auction_reserve_price", 0.0) or 0.0)
        if floor <= 0.0 or market.unsold_treatment != "cancel":
            return supply, 0.0
        # Contemporaneous complementarity on FIXED quantities (spec §2 PRIMARY):
        # the floor binds iff demand-at-floor is below supply, e_t(F_t) < S_t.
        # The +1e-9 quantity-scale slack matches the kernel's oversupply
        # boundary (clearing.py: demand_floor + 1e-9 < offered) so the F_t =
        # base-price boundary (V4) is complementary-slack, not a spurious cancel.
        # The ``supply − unsold`` form (not a bare ``demand_at_floor``) keeps the
        # window-year path byte-identical to the pre-fix rule (whose window
        # binding the host still gates by the price test — see the solver).
        demand_at_floor = total_net_demand(market, floor) + _free_allocation_total(market)
        unsold = max(0.0, supply - demand_at_floor)
        if unsold > 1e-9:
            return supply - unsold, unsold  # cancel u_t = S_t − e_t(F_t); year contributes e_t(F_t)
        return supply, 0.0
