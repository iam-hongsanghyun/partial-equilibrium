"""Product-market clearing on a demand curve (T0 kernel, D3-1).

The one genuinely new solver primitive for the multi-commodity (steel↔carbon)
flagship (``docs/multi-commodity-spec.md`` §1, ``docs/multi-commodity-plan.md``
§1). Every carbon market today clears a *compliance-obligation flow* — the
``clearing.py`` sibling solves ``total_net_demand(P) = auction_offered`` where
supply is the exogenous cap-derived auction volume and the price is the shadow
price of the cap. A **product** market is different *in kind*: it clears a
**goods market** on a behavioural **demand curve** against **optimising
supply** (both blades price-responsive), and the price is a Walrasian goods
price.

This module is pure numerics (T0): it imports only ``pe.core.*`` + scipy and
performs the same **bracket-then-Brent, never-raises total-clearing**
discipline as :func:`pe.core.market.clearing.solve_equilibrium`. The three
curves (demand, domestic supply, imports) are **injected** as callables /
frozen param objects — the real ``MultiCommodityProducer`` supply arrives in
D3-2, the config-driven market/routing in D3-3; here they are parameters so
the primitive stays testable against the closed-form spec §5 anchor with a
*synthetic* supply. Nothing imports this module yet (golden-inert).

Determinism: the excess-demand map is a deterministic function of the two
prices, Brent runs with fixed tolerances, so identical inputs return an
identical price (mirroring ``optimize_compliance``'s discipline,
``docs/multi-commodity-plan.md`` §7 risk 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from scipy.optimize import root_scalar

from ..logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "DEFAULTS",
    "DemandCurve",
    "ImportSupply",
    "ProductSupply",
    "solve_product_equilibrium",
]


# ── Solver defaults (module DEFAULTS dict; no hardcoded values at call sites) ──
# Overridable per call via keyword arguments of the same name.
DEFAULTS: dict[str, float | int] = {
    "price_upper": 1_000.0,  # currency/t-steel — initial P_s bracket ceiling
    "brent_xtol": 1e-12,  # currency/t-steel — absolute Brent tol on P_s
    "brent_rtol": 1e-12,  # dimensionless — relative Brent tol on P_s
    "brent_maxiter": 100,  # Brent iteration cap
    "max_bracket_expansions": 40,  # capped geometric bracket-expansion count
    "bracket_expand_factor": 2.0,  # geometric ceiling growth factor (>1)
    "isoelastic_price_floor": 1e-9,  # currency/t-steel — guards P_s^{-eta} at P_s→0
}


class ProductSupply(Protocol):
    """Injected aggregate domestic supply :math:`S_{\\mathrm{dom}}=\\sum_i q_i`.

    Any callable ``f(price_steel, price_carbon) -> float`` satisfies this
    protocol. D3-2's ``MultiCommodityProducer`` fleet supplies the real
    implementation (the sum of each producer's output FOC ``q_i(P_s,P_c)``);
    tests inject a synthetic linear/pinned supply.

    Units: ``price_steel`` [currency/t-steel], ``price_carbon`` [currency/tCO2],
    return [t-steel/period].
    """

    def __call__(self, price_steel: float, price_carbon: float) -> float: ...


@dataclass(frozen=True)
class DemandCurve:
    """Behavioural product demand :math:`D(P_s)` (spec §1 [JC1]).

    Two forms, selected by ``form`` (config picks it):

    * ``"linear"`` — the closed-form anchor form
      :math:`D = A_d - b_d P_s`;
    * ``"isoelastic"`` — :math:`D = \\kappa\\,P_s^{-\\eta}` (numerically
      solved; realistic for pass-through studies).

    Attributes:
        form: ``"linear"`` or ``"isoelastic"``.
        a_d: Choke intercept :math:`A_d` [t-steel/period] (linear only).
        b_d: Slope :math:`b_d` [t-steel/period per currency/t] (linear only).
        kappa: Scale :math:`\\kappa`
            [t-steel·(currency/t)^η / period] (isoelastic only).
        eta: Own-price elasticity :math:`\\eta > 0` [dimensionless]
            (isoelastic only).
        price_floor: Positive floor [currency/t-steel] guarding
            :math:`P_s^{-\\eta}` as :math:`P_s \\to 0` (isoelastic only).
    """

    form: str = "linear"
    a_d: float = 0.0
    b_d: float = 0.0
    kappa: float = 0.0
    eta: float = 1.0
    price_floor: float = field(default=float(DEFAULTS["isoelastic_price_floor"]))

    def __call__(self, price_steel: float) -> float:
        """Return demanded quantity [t-steel/period] at ``price_steel``."""
        if self.form == "linear":
            return self.a_d - self.b_d * price_steel
        if self.form == "isoelastic":
            p = max(price_steel, self.price_floor)
            return self.kappa * p ** (-self.eta)
        raise ValueError(f"DemandCurve.form must be 'linear' or 'isoelastic', got {self.form!r}.")


@dataclass(frozen=True)
class ImportSupply:
    """Carbon-free elastic import supply :math:`M(P_s)` (spec §1, §4e/§4f).

    Base schedule :math:`M = M_0 + m P_s`. With ``cbam_enabled`` the
    **price-active** CBAM lever shifts the schedule by the imported carbon
    charge :math:`c\\,P_c\\,\\sigma_{\\mathrm{foreign}}`:

    .. math:: M = M_0 + m\\,(P_s - c\\,P_c\\,\\sigma_{\\mathrm{foreign}}).

    This is a distinct object from the inert F6 reporting CBAM (spec §4e
    [STRAIN2]): it feeds *into* steel clearing. The schedule is left
    unclamped so the linear closed-form anchor is exact; under a strong CBAM
    at low :math:`P_s` it can go negative (net exports), which is monotone and
    does not affect the unique positive-price root.

    Attributes:
        m_0: Autonomous imports :math:`M_0` [t-steel/period].
        m: Import price-slope :math:`m > 0`
            [t-steel/period per currency/t].
        cbam_enabled: Turn the price-active CBAM shift on (default off).
        coverage: CBAM coverage :math:`c \\in [0, 1]` [dimensionless].
        sigma_foreign: Foreign carbon intensity
            :math:`\\sigma_{\\mathrm{foreign}}` [tCO2/t-steel].
    """

    m_0: float = 0.0
    m: float = 0.0
    cbam_enabled: bool = False
    coverage: float = 0.0
    sigma_foreign: float = 0.0

    def __call__(self, price_steel: float, price_carbon: float) -> float:
        """Return import quantity [t-steel/period] at the price pair."""
        if self.cbam_enabled:
            adjusted = price_steel - self.coverage * price_carbon * self.sigma_foreign
            return self.m_0 + self.m * adjusted
        return self.m_0 + self.m * price_steel


def solve_product_equilibrium(
    domestic_supply: ProductSupply,
    price_carbon: float,
    demand: DemandCurve,
    imports: ImportSupply,
    *,
    price_lower: float = 0.0,
    price_upper: float | None = None,
    xtol: float | None = None,
    rtol: float | None = None,
    maxiter: int | None = None,
    max_bracket_expansions: int | None = None,
    bracket_expand_factor: float | None = None,
) -> dict[str, float | int | bool | str]:
    r"""Clear a product market: Brent root-find the steel price.

    Solves for the steel price :math:`P_s` at which domestic supply plus
    imports meet demand, taking the carbon price :math:`P_c` as given (the
    carbon leg is solved separately; at the joint fixed point both legs
    evaluate at :math:`(P_s^*, P_c^*)`). The excess-demand map is **monotone
    increasing** (supply ↑, demand ↓ in :math:`P_s`) ⇒ a **unique root**, so a
    single bracket-then-Brent solve suffices — mirroring
    :func:`pe.core.market.clearing.solve_equilibrium` numerically, including
    its **total-clearing** guarantee (never raises; always returns a price at
    every supply level, including the glut and unbracketable-demand corners).

    Algorithm:
        LaTeX:
        $$ \operatorname{excess}(P_s) \;=\;
           S_{\mathrm{dom}}(P_s, P_c) + M(P_s, P_c) - D(P_s), $$
        $$ P_s^{*}:\ \operatorname{excess}(P_s^{*}) = 0, \qquad
           \frac{\mathrm{d}\,\operatorname{excess}}{\mathrm{d}P_s} > 0
           \ \Rightarrow\ \text{unique root}. $$
        Bracket-then-Brent on :math:`[P_{\text{lo}}, P_{\text{hi}}]`:
        $$ \operatorname{excess}(P_{\text{lo}}) \ge 0
           \ \Rightarrow\ \text{glut: } P_s^{*} = P_{\text{lo}}, $$
        else expand :math:`P_{\text{hi}} \leftarrow \phi\,P_{\text{hi}}`
        (capped) until :math:`\operatorname{excess}(P_{\text{hi}}) > 0`, then
        Brent-solve; if still :math:`\operatorname{excess}(P_{\text{hi}}) < 0`
        after the cap, clamp to the ceiling (loud WARNING fallback).

        ASCII fallback:
            excess(P_s) = domestic_supply(P_s;P_c) + imports(P_s;P_c)
                          - demand(P_s)
            excess(P_lo) >= 0            -> glut, price = P_lo
            expand P_hi *= factor (cap)  until excess(P_hi) > 0
            excess(P_hi) < 0 after cap   -> ceiling, price = P_hi (WARNING)
            else                         -> brentq on [P_lo, P_hi]

        Symbols (units):
            P_s           : steel/product price          [currency/t-steel]
            P_c           : carbon price (given)          [currency/tCO2]
            S_dom(P_s,P_c): aggregate domestic supply     [t-steel/period]
            M(P_s,P_c)    : import supply                 [t-steel/period]
            D(P_s)        : demand                        [t-steel/period]
            P_lo, P_hi    : Brent bracket bounds          [currency/t-steel]
            phi           : bracket_expand_factor (>1)    [dimensionless]

    Args:
        domestic_supply: Injected aggregate domestic supply
            :math:`S_{\mathrm{dom}}(P_s, P_c)` (a :class:`ProductSupply`
            callable). D3-2's producer fleet supplies the real one; tests
            inject a synthetic linear/pinned supply.
        price_carbon: The given carbon price :math:`P_c` [currency/tCO2].
        demand: The product :class:`DemandCurve` (linear or isoelastic).
        imports: The :class:`ImportSupply` schedule (optional CBAM shift).
        price_lower: Bracket bottom :math:`P_{\text{lo}}`
            [currency/t-steel]; default 0.
        price_upper: Initial bracket ceiling :math:`P_{\text{hi}}`
            [currency/t-steel]; defaults to ``DEFAULTS["price_upper"]``.
        xtol: Absolute Brent tolerance on :math:`P_s`; defaults to
            ``DEFAULTS["brent_xtol"]``.
        rtol: Relative Brent tolerance on :math:`P_s`; defaults to
            ``DEFAULTS["brent_rtol"]``.
        maxiter: Brent iteration cap; defaults to
            ``DEFAULTS["brent_maxiter"]``.
        max_bracket_expansions: Capped geometric ceiling-expansion count;
            defaults to ``DEFAULTS["max_bracket_expansions"]``.
        bracket_expand_factor: Geometric ceiling growth factor
            :math:`\phi > 1`; defaults to
            ``DEFAULTS["bracket_expand_factor"]``.

    Returns:
        A ledger-compatible detail dict (the shape the D3-3 dispatch product
        path and the reporter consume):

        * ``"price"``: clearing steel price :math:`P_s^{*}`
          [currency/t-steel];
        * ``"quantity"``: cleared volume :math:`D(P_s^{*})` [t-steel/period];
        * ``"domestic_supply"``: :math:`S_{\mathrm{dom}}(P_s^{*}, P_c)`
          [t-steel/period];
        * ``"imports"``: :math:`M(P_s^{*}, P_c)` [t-steel/period];
        * ``"coverage"``: domestic share
          :math:`S_{\mathrm{dom}}/D` [dimensionless];
        * ``"excess"``: residual :math:`\operatorname{excess}(P_s^{*})`
          (≈0 at an interior root) [t-steel/period];
        * ``"price_carbon"``: echoed :math:`P_c` [currency/tCO2];
        * ``"regime"``: ``"interior"`` | ``"glut"`` | ``"ceiling"`` |
          ``"nonconverged"``;
        * ``"converged"``: ``True`` for an interior root or a valid glut
          boundary, ``False`` for the ceiling / non-converged fallbacks;
        * ``"bracket_expansions"``: geometric expansions used [int].
    """
    price_upper_v = float(DEFAULTS["price_upper"]) if price_upper is None else price_upper
    xtol_v = float(DEFAULTS["brent_xtol"]) if xtol is None else xtol
    rtol_v = float(DEFAULTS["brent_rtol"]) if rtol is None else rtol
    maxiter_v = int(DEFAULTS["brent_maxiter"]) if maxiter is None else maxiter
    max_expansions = (
        int(DEFAULTS["max_bracket_expansions"])
        if max_bracket_expansions is None
        else max_bracket_expansions
    )
    expand_factor = (
        float(DEFAULTS["bracket_expand_factor"])
        if bracket_expand_factor is None
        else bracket_expand_factor
    )

    def excess(price_steel: float) -> float:
        dom = float(domestic_supply(price_steel, price_carbon))
        imp = float(imports(price_steel, price_carbon))
        dem = float(demand(price_steel))
        return dom + imp - dem

    lower = float(price_lower)
    upper = float(price_upper_v)
    f_low = excess(lower)

    expansions = 0
    if f_low >= 0.0:
        # Supply already meets/exceeds demand at the floor: the market-clearing
        # price is at (or below) the floor -> pin to the floor (glut boundary,
        # the product analogue of clearing.py's oversupply P=floor branch). A
        # valid boundary equilibrium, DEBUG not WARNING.
        regime = "glut"
        root = lower
        logger.debug(
            "solve_product_equilibrium: glut boundary, excess(%.6g)=%.6g>=0; "
            "pinning price to floor",
            lower,
            f_low,
        )
    else:
        f_high = excess(upper)
        while f_high < 0.0 and expansions < max_expansions:
            upper *= expand_factor
            f_high = excess(upper)
            expansions += 1
            logger.debug(
                "solve_product_equilibrium: bracket expansion %d, upper=%.6g, excess=%.6g",
                expansions,
                upper,
                f_high,
            )

        if f_high < 0.0:
            # Demand outruns supply even at the expanded ceiling: no finite
            # crossing in the searched range. Fall back LOUDLY to the ceiling
            # (never raise) rather than silently, per the total-clearing
            # discipline + house rules.
            regime = "ceiling"
            root = upper
            logger.warning(
                "solve_product_equilibrium: could not bracket root; demand "
                "exceeds supply at upper=%.6g (excess=%.6g) after %d "
                "expansions; clamping price to ceiling",
                upper,
                f_high,
                expansions,
            )
        else:
            solution = root_scalar(
                excess,
                bracket=[lower, upper],
                method="brentq",
                xtol=xtol_v,
                rtol=rtol_v,
                maxiter=maxiter_v,
            )
            if not solution.converged:
                # brentq should always converge on a sign-changed bracket;
                # guard defensively with a loud fallback rather than raising.
                regime = "nonconverged"
                root = 0.5 * (lower + upper)
                logger.warning(
                    "solve_product_equilibrium: brentq did not converge on "
                    "[%.6g, %.6g]; falling back to bracket midpoint %.6g",
                    lower,
                    upper,
                    root,
                )
            else:
                regime = "interior"
                root = float(solution.root)

    dom_star = float(domestic_supply(root, price_carbon))
    imp_star = float(imports(root, price_carbon))
    dem_star = float(demand(root))
    coverage = dom_star / dem_star if dem_star != 0.0 else 0.0

    return {
        "price": root,
        "quantity": dem_star,
        "domestic_supply": dom_star,
        "imports": imp_star,
        "coverage": coverage,
        "excess": dom_star + imp_star - dem_star,
        "price_carbon": float(price_carbon),
        "regime": regime,
        "converged": regime in ("interior", "glut"),
        "bracket_expansions": expansions,
    }
