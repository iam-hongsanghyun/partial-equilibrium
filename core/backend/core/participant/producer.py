"""Two-margin multi-commodity steel producer (T0 kernel, pure).

The D3 flagship agent (``docs/multi-commodity-spec.md`` §2, plan §2). A steel
producer that lives in TWO markets at once — a carbon SCC-market (contributing
emissions ``e`` to ``Σe = Cap``) and a steel product-market (contributing output
``q`` to ``Σq + M = D``) — and optimises over BOTH decarbonisation margins:

* the **intensity margin** ``a`` (abate emissions per tonne of steel), and
* the **output margin** ``q`` (produce less steel).

This is deliberately NOT a ``MarketParticipant``: that type *minimises
compliance cost at a fixed output*, whereas a producer *maximises profit over
(q, a)* and reads two prices (V-D3-2, plan §2). It is a new kind,
``MultiCommodityProducer``, off-by-default and golden-inert — nothing in the
config/builder constructs one yet (routing is D3-3, coupling is D3-4).

The producer exposes ONE core optimiser and TWO thin faces that delegate to it:

* ``optimize_producer(params, P_steel, P_carbon) -> ProducerOutcome`` — the
  closed-form two-margin FOCs.
* carbon face ``MultiCommodityProducer.optimize_compliance(P_carbon, ...)`` —
  DUCK-TYPES the ``MarketParticipant`` protocol so the existing
  ``core/market/clearing.py:solve_equilibrium`` calls it with NO change. Reads
  the steel price stamped on the producer (``self._P_steel``).
* steel face ``MultiCommodityProducer.product_supply(P_steel, ...) -> q`` —
  consumed by D3-1's ``solve_product_equilibrium``. Reads the carbon price
  stamped on the producer (``self._P_carbon``).

Purity: imports only ``pe.core.*`` (``.models``, ``..costs``, ``..logger``) and
numpy — no ``config_io``/``engine``/I/O. All numbers arrive as parameters; there
are no hardcoded magic constants (the optimiser is closed-form, so there is no
bracket/iteration machinery to tune).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..costs import linear_abatement_factory
from ..logger import get_logger
from .models import ComplianceOutcome

logger = get_logger(__name__)

__all__ = [
    "ProducerParams",
    "ProducerOutcome",
    "optimize_producer",
    "MultiCommodityProducer",
]


@dataclass(frozen=True)
class ProducerParams:
    r"""Per-firm structural parameters of the two-margin producer program.

    All quantities are per representative firm and per year. Steel output ``q``
    is in tonnes of steel (t-steel); emissions in tCO2; prices in currency per
    physical unit. ``delta > 0`` (strictly convex output cost ⇒ upward-sloping,
    well-defined supply) and ``beta > 0`` (finite, positive abatement-cost
    curvature ⇒ the intensity FOC ``a = P_c/beta`` is well-posed) are REQUIRED
    at construction — ``delta <= 0`` gives indeterminate output at ``MC = P``
    and is rejected (V-D3-1, spec §2 [JC3]).

    Attributes:
        gamma: Output marginal-cost intercept γ [currency / t-steel].
        delta: Output marginal-cost slope δ [currency / t-steel^2]; MUST be
            > 0 (marginal cost slopes up; output is single-valued).
        sigma: Baseline emission intensity σ [tCO2 / t-steel].
        beta: Abatement-cost curvature β [currency·t-steel / tCO2^2] so that
            MAC = β·a is in [currency / tCO2]; MUST be > 0.
        a_max: Maximum intensity abatement a_max [tCO2 / t-steel]; the
            intensity FOC is clipped to [0, a_max].
        phi_oba: Output-based-allocation benchmark intensity φ_OBA
            [tCO2 / t-steel]; free allocation grows with output as φ_OBA·q
            (a marginal output subsidy P_c·φ_OBA). 0 disables OBA.
        f_lump: Lump-sum free allocation F_lump [tCO2 / yr]; infra-marginal
            (absent from both FOCs — a pure transfer).
    """

    gamma: float
    delta: float
    sigma: float
    beta: float
    a_max: float
    phi_oba: float = 0.0
    f_lump: float = 0.0

    def __post_init__(self) -> None:
        if not np.isfinite(self.delta) or self.delta <= 0.0:
            raise ValueError(
                f"delta must be finite and strictly positive (got {self.delta!r}): "
                "delta <= 0 gives a horizontal marginal cost and indeterminate "
                "output at MC = P (spec §2 [JC3], V-D3-1)."
            )
        if not np.isfinite(self.beta) or self.beta <= 0.0:
            raise ValueError(
                f"beta must be finite and strictly positive (got {self.beta!r}): "
                "the intensity FOC a = P_c/beta is otherwise ill-posed."
            )
        if self.gamma < 0.0:
            raise ValueError(f"gamma must be non-negative (got {self.gamma!r}).")
        if self.sigma < 0.0:
            raise ValueError(f"sigma must be non-negative (got {self.sigma!r}).")
        if self.a_max < 0.0:
            raise ValueError(f"a_max must be non-negative (got {self.a_max!r}).")
        if self.phi_oba < 0.0:
            raise ValueError(f"phi_oba must be non-negative (got {self.phi_oba!r}).")
        if self.f_lump < 0.0:
            raise ValueError(f"f_lump must be non-negative (got {self.f_lump!r}).")


@dataclass(frozen=True)
class ProducerOutcome:
    """Solved two-margin outcome at a given ``(P_steel, P_carbon)`` pair.

    Attributes:
        q: Optimal steel output q* [t-steel / yr]; floored at 0.
        a: Optimal intensity abatement a* [tCO2 / t-steel]; clipped to
            [0, a_max].
        emissions: Residual emissions e* = (σ − a*)·q* [tCO2 / yr].
        profit: Maximised profit π [currency / yr] (spec §2 objective,
            including the OBA allocation credit P_c·(F_lump + φ_OBA·q*)).
        net_carbon_burden: Per-unit net carbon burden B [currency / t-steel]
            entering the output FOC.
        free_allocation: Free allocation F = F_lump + φ_OBA·q* [tCO2 / yr]
            (lump-sum + output-based).
        net_allowance_demand: Carbon-market net demand e* − F [tCO2 / yr]
            (> 0 buyer, < 0 seller).
        abatement_cost: Total intensity-abatement cost ½·β·a*²·q*
            [currency / yr].
        initial_emissions: Baseline (pre-abatement) emissions σ·q*
            [tCO2 / yr].
        clip_binds: True iff the a_max intensity clip is active
            (P_c/β > a_max).
        output_floored: True iff the q ≥ 0 exit floor is active
            (below break-even output).
    """

    q: float
    a: float
    emissions: float
    profit: float
    net_carbon_burden: float
    free_allocation: float
    net_allowance_demand: float
    abatement_cost: float
    initial_emissions: float
    clip_binds: bool
    output_floored: bool


def optimize_producer(params: ProducerParams, P_steel: float, P_carbon: float) -> ProducerOutcome:
    r"""Solve the two-margin producer program in closed form.

    Maximises profit over intensity abatement ``a`` and output ``q`` given a
    steel price and a carbon price. This is the a_max-CLIPPED GENERAL form
    (V-D3-2), not the interior shortcut: the per-unit carbon burden ``B`` is
    built from the CLIPPED ``a*`` (so it is exact when the intensity clip
    binds), and output carries a ``q >= 0`` exit floor. Both the clip and the
    floor are continuous kinks — deterministic and single-valued (V-D3-1) — so
    the map is a pure, deterministic function of the two prices (no
    root-finding, no iteration).

    Algorithm:
        LaTeX:
        $$ a^{*}(P_c) = \mathrm{clip}\!\left(\frac{P_c}{\beta},\ 0,\ a_{\max}\right) $$
        $$ B(P_c) = \tfrac{1}{2}\beta\,(a^{*})^{2}
                    + P_c\,(\sigma - a^{*})
                    - P_c\,\varphi_{\mathrm{OBA}} $$
        $$ q^{*}(P_s,P_c) = \max\!\left(0,\ \frac{P_s - \gamma - B}{\delta}\right) $$
        $$ e^{*} = (\sigma - a^{*})\,q^{*} $$
        $$ \pi = P_s q^{*}
                 - \big(\gamma q^{*} + \tfrac{1}{2}\delta (q^{*})^{2}\big)
                 - \tfrac{1}{2}\beta (a^{*})^{2} q^{*}
                 - P_c e^{*}
                 + P_c\big(F_{\mathrm{lump}} + \varphi_{\mathrm{OBA}} q^{*}\big) $$

        ASCII fallback:
            a = clip(P_c / beta, 0, a_max)
            B = 0.5*beta*a*a + P_c*(sigma - a) - P_c*phi_OBA
            q = max(0, (P_s - gamma - B) / delta)
            e = (sigma - a) * q
            profit = P_s*q - (gamma*q + 0.5*delta*q*q) - 0.5*beta*a*a*q
                     - P_c*e + P_c*(F_lump + phi_OBA*q)

        Symbols (units):
            P_s      : steel price                          [currency / t-steel]
            P_c      : carbon price                         [currency / tCO2]
            gamma    : output marginal-cost intercept γ     [currency / t-steel]
            delta    : output marginal-cost slope δ (> 0)   [currency / t-steel^2]
            sigma    : baseline emission intensity σ        [tCO2 / t-steel]
            beta     : abatement-cost curvature β (> 0)     [currency·t-steel / tCO2^2]
            a_max    : max intensity abatement              [tCO2 / t-steel]
            phi_OBA  : OBA benchmark intensity φ_OBA        [tCO2 / t-steel]
            F_lump   : lump-sum free allocation             [tCO2 / yr]
            a        : intensity abatement a* (decision)    [tCO2 / t-steel]
            B        : per-unit net carbon burden           [currency / t-steel]
            q        : output q* (decision)                 [t-steel / yr]
            e        : residual emissions e*                [tCO2 / yr]
            profit   : maximised profit π                   [currency / yr]

    The intensity margin responds first and linearly (``a* = P_c/β`` clipped);
    the output margin then responds to the *residual* burden ``B`` after
    abatement. OBA (``φ_OBA``) enters ONLY ``B`` (via ``−P_c·φ_OBA``), raising
    ``q*`` while leaving ``a*`` untouched — the marginal output subsidy
    (spec §2, §4d). Note: the abatement-saving cushion ``+½P_c²/β`` of the
    interior form is recovered automatically here whenever the clip is slack,
    since then ``½β a*² + P_c(σ−a*) = P_c σ − ½P_c²/β``.

    Args:
        params: Structural parameters (validated at construction).
        P_steel: Steel price P_s [currency / t-steel].
        P_carbon: Carbon price P_c [currency / tCO2].

    Returns:
        The solved :class:`ProducerOutcome`.
    """
    P_s = float(P_steel)
    P_c = float(P_carbon)

    # Intensity FOC: abate until MAC = beta*a = P_c, clipped to [0, a_max].
    # Reuse the kernel's linear abatement helper (core/costs.py) — its rule is
    # exactly min(a_max, max(0, P_c/beta)) = clip(P_c/beta, 0, a_max).
    abatement_rule = linear_abatement_factory(max_abatement=params.a_max, cost_slope=params.beta)
    a = float(abatement_rule(P_c))
    clip_binds = params.beta * a < P_c - 1e-12  # MAC < P_c ⇒ clip active

    # Per-unit net carbon burden B, built from the CLIPPED a (general form).
    abatement_cost_per_unit = 0.5 * params.beta * a * a
    burden = abatement_cost_per_unit + P_c * (params.sigma - a) - P_c * params.phi_oba

    # Output FOC with the q >= 0 exit floor (below break-even ⇒ shut output).
    q_unfloored = (P_s - params.gamma - burden) / params.delta
    q = max(0.0, q_unfloored)
    output_floored = q_unfloored <= 0.0

    emissions = (params.sigma - a) * q
    initial_emissions = params.sigma * q
    free_allocation = params.f_lump + params.phi_oba * q
    net_allowance_demand = emissions - free_allocation
    abatement_cost = abatement_cost_per_unit * q

    # Profit = revenue - production cost - abatement cost - allowance cost on
    # gross emissions + allocation credit on BOTH lump-sum and OBA allowances.
    # The OBA credit +P_c*phi*q is REQUIRED for consistency with the q-FOC
    # (whose B carries -P_c*phi) and with spec §2's objective pi = ... + P_c*F,
    # F = F_lump + phi*q; see module report note.
    profit = (
        P_s * q
        - (params.gamma * q + 0.5 * params.delta * q * q)
        - abatement_cost
        - P_c * emissions
        + P_c * free_allocation
    )

    if clip_binds or output_floored:
        logger.debug(
            "optimize_producer kinks: clip_binds=%s output_floored=%s (a=%.6g, q=%.6g)",
            clip_binds,
            output_floored,
            a,
            q,
        )

    return ProducerOutcome(
        q=q,
        a=a,
        emissions=emissions,
        profit=profit,
        net_carbon_burden=burden,
        free_allocation=free_allocation,
        net_allowance_demand=net_allowance_demand,
        abatement_cost=abatement_cost,
        initial_emissions=initial_emissions,
        clip_binds=clip_binds,
        output_floored=output_floored,
    )


@dataclass
class MultiCommodityProducer:
    r"""A two-margin steel producer registered in a carbon AND a steel market.

    One object, two faces, both delegating to :func:`optimize_producer`. The
    producer carries the sibling market's price as *stamped state*
    (``_P_steel``, ``_P_carbon``): before the carbon leg solves, the sweep
    stamps the current steel price (:meth:`stamp_steel_price`); before the steel
    leg solves, it stamps the current carbon price (:meth:`stamp_carbon_price`).
    Each face reads the stamped sibling price and solves at
    ``(P_steel, P_carbon)`` — at the joint fixed point both faces evaluate at the
    same converged pair and recover the identical ``q*`` (plan §0, §2: the price
    norm suffices; no quantity is threaded across markets).

    Carbon face (``optimize_compliance``) DUCK-TYPES the ``MarketParticipant``
    protocol that ``core/market/clearing.py:solve_equilibrium`` consumes: it
    exposes ``name``, ``penalty_price``, ``free_allocation`` (read by
    ``CarbonMarket.__init__``) and returns a real
    :class:`~pe.core.participant.models.ComplianceOutcome` whose
    ``net_allowances_traded`` equals ``e − free_alloc``. So the existing carbon
    solver runs UNCHANGED with a producer in its participant list.

    Off-by-default and golden-inert — no config/builder path constructs one yet.

    Attributes:
        name: Participant name (carbon-market ledger key).
        params: Structural :class:`ProducerParams`.
        penalty_price: Compliance-cap penalty [currency / tCO2]; 0 = no cap
            (matches ``MarketParticipant`` convention; read by
            ``solve_equilibrium`` for the default upper bracket).
    """

    name: str
    params: ProducerParams
    penalty_price: float = 0.0
    _P_steel: float = field(default=0.0, repr=False)
    _P_carbon: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        if self.penalty_price < 0.0:
            raise ValueError(
                f"{self.name}: penalty_price must be non-negative "
                f"(0 = no cap; got {self.penalty_price!r})."
            )

    # ── Price stamping (the sanctioned sibling-price mutators) ───────────────

    def stamp_steel_price(self, P_steel: float) -> None:
        """Stamp the current steel price read by the carbon face.

        Args:
            P_steel: Steel price P_s [currency / t-steel].
        """
        self._P_steel = float(P_steel)

    def stamp_carbon_price(self, P_carbon: float) -> None:
        """Stamp the current carbon price read by the steel face.

        Args:
            P_carbon: Carbon price P_c [currency / tCO2].
        """
        self._P_carbon = float(P_carbon)

    # ── Core optimisation at stamped prices ──────────────────────────────────

    def optimize(self) -> ProducerOutcome:
        """Solve the producer program at the currently stamped price pair.

        Returns:
            The :class:`ProducerOutcome` at ``(self._P_steel, self._P_carbon)``.
        """
        return optimize_producer(self.params, self._P_steel, self._P_carbon)

    @property
    def free_allocation(self) -> float:
        """Free allocation at stamped prices [tCO2 / yr].

        ``F_lump + φ_OBA·q*`` evaluated at the currently stamped price pair
        (V-D3-2 / plan §STRAIN5: OBA free allocation is solve-time state, not a
        build-time constant). Read by ``CarbonMarket.__init__`` when the
        producer stands in the carbon participant list. At construction (prices
        0 ⇒ below break-even ⇒ q* = 0) this is just ``F_lump``.
        """
        return self.optimize().free_allocation

    # ── Carbon face: duck-types the MarketParticipant protocol ───────────────

    def optimize_compliance(
        self,
        carbon_price: float,
        starting_bank_balance: float = 0.0,
        expected_future_price: float = 0.0,
        banking_allowed: bool = False,
        borrowing_allowed: bool = False,
        borrowing_limit: float = 0.0,
        slsqp_max_iters: int = 400,
        slsqp_ftol: float = 1e-9,
    ) -> ComplianceOutcome:
        r"""Carbon-market face — compliance outcome at the stamped steel price.

        DUCK-TYPES ``MarketParticipant.optimize_compliance``: the carbon solver
        (``core/market/clearing.py``) calls this with the SAME signature and
        reads only ``ComplianceOutcome.net_allowances_traded`` from the result,
        which here equals ``e* − F`` with ``F = F_lump + φ_OBA·q*`` — the
        producer's net carbon demand. Emissions and output are re-derived from
        BOTH prices via :func:`optimize_producer`, using the steel price stamped
        by the sweep (``self._P_steel``) and the ``carbon_price`` argument. This
        is an own-market response inside the single carbon Brent solve (like the
        elastic-baseline overlay, V-D2-7), NOT an outer loop.

        The producer does not bank in v1: banking/borrowing arguments and the
        SLSQP tuning arguments are accepted for protocol compatibility and
        ignored; ``ending_bank_balance`` is 0.

        Algorithm:
            LaTeX:  $$ D_{\mathrm{net}}(P_c) = e^{*} - F,
                       \quad F = F_{\mathrm{lump}} + \varphi_{\mathrm{OBA}} q^{*} $$
            ASCII:  net_allowances_traded = e - (F_lump + phi_OBA*q),
                    with (q, a, e) = optimize_producer(P_steel_stamped, P_c)

        Symbols (units):
            P_c       : carbon price (this argument)         [currency / tCO2]
            e         : residual emissions e*                [tCO2 / yr]
            F         : free allocation (lump-sum + OBA)      [tCO2 / yr]
            D_net     : net allowance demand                  [tCO2 / yr]

        Args:
            carbon_price: Carbon price P_c [currency / tCO2].
            starting_bank_balance: Beginning-of-year bank balance [tCO2];
                recorded, not acted on (producer does not bank in v1).
            expected_future_price: Expected next-period price [currency / tCO2];
                recorded only.
            banking_allowed: Ignored (producer does not bank in v1).
            borrowing_allowed: Ignored.
            borrowing_limit: Ignored.
            slsqp_max_iters: Ignored (closed-form; no SLSQP).
            slsqp_ftol: Ignored (closed-form; no SLSQP).

        Returns:
            A :class:`~pe.core.participant.models.ComplianceOutcome` whose
            ``net_allowances_traded`` is the producer's net carbon demand.
        """
        outcome = optimize_producer(self.params, self._P_steel, carbon_price)
        net_demand = outcome.net_allowance_demand
        buys = max(0.0, net_demand)
        sells = max(0.0, -net_demand)
        allowance_cost = buys * carbon_price
        sales_revenue = sells * carbon_price
        return ComplianceOutcome(
            abatement=outcome.a * outcome.q,
            residual_emissions=outcome.emissions,
            allowance_buys=buys,
            allowance_sells=sells,
            penalty_emissions=0.0,
            abatement_cost=outcome.abatement_cost,
            allowance_cost=allowance_cost,
            penalty_cost=0.0,
            sales_revenue=sales_revenue,
            fixed_cost=0.0,
            technology_name=self.name,
            initial_emissions=outcome.initial_emissions,
            free_allocation=outcome.free_allocation,
            penalty_price=self.penalty_price,
            starting_bank_balance=starting_bank_balance,
            ending_bank_balance=0.0,
            expected_future_price=expected_future_price,
            banked_allowances=0.0,
            borrowed_allowances=0.0,
            total_cost=outcome.abatement_cost + allowance_cost - sales_revenue,
            technology_mix=(),
        )

    # ── Steel face: consumed by solve_product_equilibrium (D3-1) ─────────────

    def product_supply(self, P_steel: float, carbon_price: float | None = None) -> float:
        r"""Steel-market face — output supply at the stamped carbon price.

        Returns ``q*`` for the product-market clearing (D3-1's
        ``solve_product_equilibrium`` sums this over producers). Solves at the
        ``P_steel`` argument (the price the product solver is probing) and the
        carbon price stamped on the producer (``self._P_carbon``), or an
        explicit ``carbon_price`` override if supplied.

        Algorithm:
            LaTeX:  $$ q^{*}(P_s, P_c) =
                       \max\!\left(0,\ \frac{P_s - \gamma - B(P_c)}{\delta}\right) $$
            ASCII:  q = optimize_producer(P_s, P_c_stamped).q

        Symbols (units):
            P_s : steel price (this argument)   [currency / t-steel]
            P_c : stamped carbon price          [currency / tCO2]
            q   : optimal output q*             [t-steel / yr]

        Args:
            P_steel: Steel price P_s [currency / t-steel].
            carbon_price: Optional carbon-price override [currency / tCO2];
                defaults to the stamped ``self._P_carbon``.

        Returns:
            Optimal steel output ``q*`` [t-steel / yr], floored at 0.
        """
        P_c = self._P_carbon if carbon_price is None else float(carbon_price)
        return optimize_producer(self.params, P_steel, P_c).q
