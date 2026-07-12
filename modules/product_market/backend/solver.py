r"""product_market runtime door — the product-path solver (T2 runtime, D3-3).

Builds the three injected clearing curves from a normalised product market body
(stamped on an inert-cap :class:`~pe.core.market.CarbonMarket` by the builder)
and clears each year via the T0 primitive
:func:`pe.core.market.product_clearing.solve_product_equilibrium`. The market
is solved STANDALONE at its EXOGENOUS ``carbon_price`` — D3-3 proves the product
market is dispatchable in isolation, BEFORE any steel↔carbon coupling (D3-4
replaces the exogenous P_c with the coupled joint price; plan §6 D3-3).

The three curves (spec §1, plan §1):

* demand — :class:`~pe.core.market.product_clearing.DemandCurve` from
  ``product_demand`` (linear ``A_d - b_d·P_s`` or isoelastic ``κ·P_s^{-η}``);
* imports — :class:`~pe.core.market.product_clearing.ImportSupply` from
  ``import_supply`` (``M_0 + m·P_s`` + optional price-active CBAM shift);
* domestic supply — the aggregate ``S_dom(P_s, P_c) = Σ_i q_i`` over the body's
  ``kind: "producer"`` participants, each a
  :class:`~pe.core.participant.producer.MultiCommodityProducer` evaluated at the
  body's exogenous carbon price (its output FOC ``q_i(P_s, P_c)``).

The solver returns LEDGER-COMPATIBLE detail dicts (plan §3/§7 strain 1): the
per-year ``{market, equilibrium, participant_df, ...}`` bundle
``pe.core.ledger.collect_path_results`` consumes with no carbon-specific
assumptions. The producer participant frame carries product columns (``Output``,
``Emissions``, ``Profit``) ALONGSIDE the carbon-ledger base columns the
reporting host sums, so a product market reports through the SAME frame
machinery as a carbon one (whatever shape emerges is pinned by a baseline in
D3-6). The equilibrium dict carries the auction-shaped keys the summary host
reads, set to inert product values (the cap buckets are inert, plan §1).

Purity: imports ``pe.core.*`` only (the T2→T0 edge the AST ratchet permits) +
stdlib. Reached ONLY from the engine (``engine/wiring.py:solve_product_path``,
routed by the ``"product"`` dispatch branch); ``config_io`` sees only the
``plugin`` door. Determinism: producers are sorted by name before every
iteration (aggregate supply, reporting), and the T0 primitive runs a fixed-
tolerance Brent solve, so identical inputs return identical output.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pandas as pd

from ...core.logger import get_logger
from ...core.market.product_clearing import (
    DemandCurve,
    ImportSupply,
    solve_product_equilibrium,
)
from ...core.participant.producer import (
    MultiCommodityProducer,
    ProducerOutcome,
    ProducerParams,
    clean_tech_option_from_spec,
    optimize_producer,
)

if TYPE_CHECKING:
    from ...core.market import CarbonMarket

logger = get_logger(__name__)

__all__ = ["product_scc_loop_gain", "solve_product_path"]

# R37 (D3 adaptation) — the joint SCC loop gain above which damped Gauss-Seidel
# is not guaranteed to contract (docs/multi-commodity-spec.md §7 R37 ADAPTATION).
# |g| >= 1 warns; the D3 anchor sits at g = 0.627 and must NOT fire.
_LOOP_GAIN_WARN_THRESHOLD = 1.0


def product_scc_loop_gain(
    params_list: list[ProducerParams],
    b_d: float,
    m: float,
    price_steel: float,
    price_carbon: float,
    *,
    cbam_coverage: float = 0.0,
    cbam_sigma_foreign: float = 0.0,
) -> float:
    r"""Actual steel↔carbon joint loop gain ``g = s_c · s_s`` (R37, D3 adaptation).

    The shared-agent structural coupling has NO external link coefficient ``φ``
    and its steel-side response ``s_s`` is not bounded by 1, so R37's conservative
    ``ĝ = Π|φ|`` (a D1/D2 external-link device) does NOT apply (spec §7 R37
    ADAPTATION). This evaluates the ACTUAL loop gain from the linearised 2×2
    clearing Jacobian at a given operating point — a cheap closed-form read of the
    producer FOC slopes plus the demand/import slopes; the cap is a constant and
    drops out of every derivative, so the whole gain lives in the steel body.

    Algorithm:
        LaTeX:
        $$ a_i^{*} = \mathrm{clip}(P_c/\beta_i, 0, a_{\max,i}), \quad
           \frac{\partial q_i}{\partial P_s} = \frac{1}{\delta_i}\,[q_i>0], \quad
           \frac{\partial q_i}{\partial P_c}
             = -\frac{(\sigma_i - a_i^{*}) - \varphi_i}{\delta_i}\,[q_i>0]. $$
        Carbon clearing $G=\sum_i e_i-\mathrm{Cap}=0$ and steel clearing
        $H=\sum_i q_i+M-D=0$ give
        $$ s_c = -\frac{\partial G/\partial P_s}{\partial G/\partial P_c}, \qquad
           s_s = -\frac{\partial H/\partial P_c}{\partial H/\partial P_s}, \qquad
           g = s_c\,s_s, $$
        with $\partial G/\partial P_s=\sum_i(\sigma_i-a_i^{*})\partial q_i/\partial P_s$,
        $\partial G/\partial P_c=\sum_i[-\dot a_i^{*}q_i+(\sigma_i-a_i^{*})\partial q_i/\partial P_c]$,
        $\partial H/\partial P_s=\sum_i\partial q_i/\partial P_s+m+b_d$,
        $\partial H/\partial P_c=\sum_i\partial q_i/\partial P_c-m\,c\,\sigma_{\mathrm{fgn}}$,
        $\dot a_i^{*}=1/\beta_i$ when the intensity clip is slack, else 0.

        ASCII fallback:
            per producer i at (P_s, P_c):
                a       = clip(P_c/beta, 0, a_max);  da = 1/beta if clip slack else 0
                q       = optimize_producer(i, P_s, P_c).q
                dq_dPs  = 1/delta if q>0 else 0
                dB_dPc  = beta*a*da + (sigma-a) - P_c*da - phi_oba
                dq_dPc  = -dB_dPc/delta if q>0 else 0
                dG_dPs += (sigma-a)*dq_dPs
                dG_dPc += -da*q + (sigma-a)*dq_dPc
                dH_dPs += dq_dPs ; dH_dPc += dq_dPc
            dH_dPs += m + b_d ; dH_dPc += -m*c*sigma_fgn
            s_c = -dG_dPs/dG_dPc ; s_s = -dH_dPc/dH_dPs ; g = s_c*s_s

        Symbols (units):
            P_s        : steel price (operating point)      [currency/t-steel]
            P_c        : carbon price (operating point)     [currency/tCO2]
            b_d        : demand slope b_d (>= 0)             [t-steel/period per currency/t]
            m          : import price-slope (>= 0)          [t-steel/period per currency/t]
            c, sigma_fgn: CBAM coverage / foreign intensity [-, tCO2/t-steel]
            s_c, s_s   : carbon/steel structural responses  [dimensionless]
            g          : joint Gauss-Seidel loop gain       [dimensionless]

    Args:
        params_list: The producers' validated :class:`ProducerParams`.
        b_d: Linear-demand slope ``b_d`` [t-steel/period per currency/t]; 0 for a
            perfectly inelastic (or isoelastic — approximated locally) demand.
        m: Import price-slope ``m`` [t-steel/period per currency/t].
        price_steel: Operating steel price ``P_s`` [currency/t-steel].
        price_carbon: Operating carbon price ``P_c`` [currency/tCO2].
        cbam_coverage: CBAM coverage ``c`` [dimensionless] (0 = off).
        cbam_sigma_foreign: Foreign intensity ``σ_foreign`` [tCO2/t-steel].

    Returns:
        The loop gain ``g`` [dimensionless]; 0 when either clearing slope is
        degenerate (a decoupled / block-recursive corner).
    """
    dG_dPs = 0.0
    dG_dPc = 0.0
    dH_dPs_prod = 0.0
    dH_dPc_prod = 0.0
    for params in params_list:
        a = min(params.a_max, max(0.0, price_carbon / params.beta))
        clip_slack = price_carbon < params.beta * params.a_max
        da_dPc = (1.0 / params.beta) if clip_slack else 0.0
        q = optimize_producer(params, price_steel, price_carbon).q
        dq_dPs = (1.0 / params.delta) if q > 0.0 else 0.0
        dB_dPc = (
            params.beta * a * da_dPc + (params.sigma - a) - price_carbon * da_dPc - params.phi_oba
        )
        dq_dPc = (-dB_dPc / params.delta) if q > 0.0 else 0.0
        dG_dPs += (params.sigma - a) * dq_dPs
        dG_dPc += -da_dPc * q + (params.sigma - a) * dq_dPc
        dH_dPs_prod += dq_dPs
        dH_dPc_prod += dq_dPc

    dH_dPs = dH_dPs_prod + m + b_d
    dH_dPc = dH_dPc_prod - m * cbam_coverage * cbam_sigma_foreign
    if dG_dPc == 0.0 or dH_dPs == 0.0:
        return 0.0
    s_c = -dG_dPs / dG_dPc
    s_s = -dH_dPc / dH_dPs
    return s_c * s_s


def _demand_curve(spec: dict[str, Any]) -> DemandCurve:
    """Build a :class:`DemandCurve` from a normalised ``product_demand`` spec."""
    if spec.get("form") == "isoelastic":
        return DemandCurve(
            form="isoelastic",
            kappa=float(spec.get("kappa", 0.0)),
            eta=float(spec.get("eta", 1.0)),
        )
    return DemandCurve(
        form="linear",
        a_d=float(spec.get("a_d", 0.0)),
        b_d=float(spec.get("b_d", 0.0)),
    )


def _import_supply(spec: dict[str, Any]) -> ImportSupply:
    """Build an :class:`ImportSupply` from a normalised ``import_supply`` spec."""
    return ImportSupply(
        m_0=float(spec.get("m_0", 0.0)),
        m=float(spec.get("m", 0.0)),
        cbam_enabled=bool(spec.get("cbam_enabled", False)),
        coverage=float(spec.get("coverage", 0.0)),
        sigma_foreign=float(spec.get("sigma_foreign", 0.0)),
    )


def _producer_params(spec: dict[str, Any]) -> ProducerParams:
    """Build validated :class:`ProducerParams` from a normalised producer spec.

    Carries the cleaner-tech ``technology_options`` (spec §4g) and the
    already-adopted floor ``adopted_tech`` (the spec's solve-time
    ``_adopted_tech``, stamped by the SCC adoption-outer-floor host on
    ``product_producers`` before the leg solves); both empty by default (the
    byte-identical no-invest path).
    """
    options = tuple(clean_tech_option_from_spec(o) for o in spec.get("technology_options") or [])
    adopted = frozenset(str(n) for n in spec.get("_adopted_tech") or [])
    return ProducerParams(
        gamma=float(spec["gamma"]),
        delta=float(spec["delta"]),
        sigma=float(spec["sigma"]),
        beta=float(spec["beta"]),
        a_max=float(spec["a_max"]),
        phi_oba=float(spec.get("phi_oba", 0.0)),
        f_lump=float(spec.get("f_lump", 0.0)),
        technology_options=options,
        adopted_tech=adopted,
    )


def _producer_row(
    scenario_name: str,
    year: str | None,
    name: str,
    outcome: ProducerOutcome,
) -> dict[str, Any]:
    """One producer's ledger-compatible participant-frame row.

    Carries the product columns (``Output``, ``Emissions``, ``Profit``, plus the
    intensity-abatement diagnostics) AND the carbon-ledger base columns the
    reporting host (``core/market/reporting.py:scenario_summary``) sums. In the
    STANDALONE product market (D3-3) there is no carbon trading, so the allowance/
    banking columns are 0; ``Abatement`` carries the producer's total intensity
    abatement ``a*·q*`` [tCO2], which is a meaningful aggregate for the summary.
    """
    return {
        "Scenario": scenario_name,
        "Participant": name,
        "Chosen Technology": name,
        "Technology Mix": "",
        # ── product columns (plan §3/§7 strain 1) ──
        "Output": outcome.q,
        "Emissions": outcome.emissions,
        "Profit": outcome.profit,
        "Intensity Abatement": outcome.a,
        "Producer Free Allocation": outcome.free_allocation,
        # ── carbon-ledger base columns the reporting host reads ──
        "Abatement": outcome.a * outcome.q,
        "Allowance Buys": 0.0,
        "Allowance Sells": 0.0,
        "Penalty Emissions": 0.0,
        "Net Allowances Traded": 0.0,
        "Starting Bank Balance": 0.0,
        "Ending Bank Balance": 0.0,
        "Banked Allowances": 0.0,
        "Borrowed Allowances": 0.0,
        "Total Compliance Cost": 0.0,
        **({"Year": year} if year is not None else {}),
    }


# Below this |denominator| the domestic emission cut is numerically zero (no
# policy bite): leakage is undefined ⇒ reported as 0.0 (no cut, no leak).
_LEAKAGE_MIN_CUT = 1e-9


def _leakage_diagnostic(
    producers: list[MultiCommodityProducer],
    demand: DemandCurve,
    imports: ImportSupply,
    price_steel: float,
    price_carbon: float,
) -> tuple[float, float]:
    r"""Carbon-leakage rates vs the no-policy (P_carbon = 0) counterfactual (§4f).

    The share of the domestic emission cut that reappears abroad as embodied
    carbon in extra imports. NAMED counterfactual (V-D3-4 requires it): the
    no-policy world ``P_carbon = 0`` — at which the CBAM charge (``c·P_c·
    σ_foreign``) also vanishes, so both the carbon price AND its border
    adjustment switch off together.

    **V-D3-5 ruling #2 — the counterfactual holds the BASELINE (un-adopted) σ.**
    The headline leakage's ``P_c = 0`` counterfactual re-derives the producer at
    its UN-ADOPTED technology σ (``adopted_tech`` stripped), NOT the
    post-adoption σ′. So the headline measures the WHOLE-POLICY effect INCLUDING
    the induced tech-switch: adoption preserves domestic output/emissions, which
    the un-adopted counterfactual scores as a larger ``e^0`` and hence a lower
    leakage. A SECONDARY "conditional" leakage holds the counterfactual at the
    post-adoption σ′ (the tech-switch taken as given); with no adoption the two
    coincide. Because at ``P_c = 0`` the burden ``B`` vanishes, ``q^0``/``P_s^0``/
    ``M^0`` are identical under σ and σ′ — only ``e^0 = σ·q^0`` differs.

    Algorithm:
        LaTeX:
        $$ L = \sigma_{\mathrm{foreign}}\,
               \frac{M^{*} - M^{0}}{e^{0} - e^{*}_{\mathrm{dom}}}, \qquad
           (P_s^{0}) : S_{\mathrm{dom}}^{\,\mathrm{base}}(P_s^{0}, 0)
                       + M(P_s^{0}, 0) = D(P_s^{0}), $$
        with the HEADLINE ``e^{0} = Σ_i (\sigma_i) q_i(P_s^0,0)`` at the un-adopted
        baseline σ and the CONDITIONAL ``e^{0}_{\mathrm{cond}} = Σ_i
        (\sigma'_i) q_i(P_s^0,0)`` at the post-adoption σ′. Undefined (⇒ 0) when
        the domestic cut is numerically zero.

        ASCII fallback:
            P_s0 solves S_dom_base(P_s0,0) + M(P_s0,0) = D(P_s0)  # un-adopted sigma
            M0        = M(P_s0,0)
            e0        = sum sigma_i    * q_i(P_s0,0)   # headline (un-adopted)
            e0_cond   = sum sigma'_i   * q_i(P_s0,0)   # conditional (post-adopt)
            L         = sigma_foreign*(M_star - M0)/(e0      - e_dom_star)
            L_cond    = sigma_foreign*(M_star - M0)/(e0_cond - e_dom_star)

        Symbols (units):
            sigma_foreign : foreign carbon intensity of imports [tCO2/t-steel]
            M_star, M0    : policy-on / no-policy imports        [t-steel/period]
            e0, e_dom_star: no-policy / policy-on domestic emissions [tCO2/period]
            L             : headline leakage rate (un-adopted σ)  [dimensionless]
            L_cond        : conditional leakage (post-adoption σ′) [dimensionless]

    Args:
        producers: The market's producer fleet (sorted; each reads BOTH prices)
            carrying the CONVERGED adoption floor on ``params.adopted_tech``.
        demand: The product demand curve.
        imports: The import-supply schedule (its ``sigma_foreign`` is the foreign
            carbon intensity used as the leakage numerator's per-unit factor).
        price_steel: The policy-on cleared steel price ``P_s^*`` [currency/t-steel].
        price_carbon: The policy-on carbon price ``P_c^*`` [currency/tCO2].

    Returns:
        ``(headline, conditional)`` leakage rates [dimensionless]; ``(0.0, 0.0)``
        when there is no domestic cut (no policy bite) or no foreign carbon
        channel (``sigma_foreign = 0``).
    """
    sigma_foreign = float(imports.sigma_foreign)
    if sigma_foreign == 0.0:
        return 0.0, 0.0

    # The un-adopted (baseline-σ) counterparts of each producer's params: the
    # clean-tech floor stripped so the P_c = 0 counterfactual world holds the
    # BASELINE technology (ruling #2). With no adoption this is the same object.
    base_params = [replace(p.params, adopted_tech=frozenset()) for p in producers]

    def _base_supply(P_s: float, P_c: float) -> float:
        return sum(optimize_producer(pp, P_s, P_c).q for pp in base_params)

    def _emissions(params_list: list[ProducerParams], P_s: float, P_c: float) -> float:
        return sum(optimize_producer(pp, P_s, P_c).emissions for pp in params_list)

    # Policy-on: imports at the cleared pair (incl. the CBAM shift) + domestic cut
    # at the ACTUAL (post-adoption) technology.
    m_star = float(imports(price_steel, price_carbon))
    e_dom_star = _emissions([p.params for p in producers], price_steel, price_carbon)

    # No-policy counterfactual: re-clear the steel market at P_c = 0 under the
    # UN-ADOPTED baseline supply (identical to the adopted supply here, since the
    # burden vanishes at P_c = 0 — see the docstring).
    cf = solve_product_equilibrium(_base_supply, 0.0, demand, imports)
    price_steel_0 = float(cf["price"])
    m_0 = float(imports(price_steel_0, 0.0))
    e_0_headline = _emissions(base_params, price_steel_0, 0.0)  # baseline σ
    e_0_conditional = _emissions([p.params for p in producers], price_steel_0, 0.0)  # σ′

    numerator = sigma_foreign * (m_star - m_0)
    cut_headline = e_0_headline - e_dom_star
    cut_conditional = e_0_conditional - e_dom_star
    headline = 0.0 if abs(cut_headline) < _LEAKAGE_MIN_CUT else numerator / cut_headline
    conditional = 0.0 if abs(cut_conditional) < _LEAKAGE_MIN_CUT else numerator / cut_conditional
    return headline, conditional


def _solve_one_market(market: CarbonMarket) -> dict[str, Any]:
    r"""Clear one product-market year; return its ledger-compatible detail dict.

    Algorithm:
        LaTeX:
        $$ S_{\mathrm{dom}}(P_s, P_c) = \sum_i q_i(P_s, P_c), \qquad
           P_s^{*}: \; S_{\mathrm{dom}}(P_s^{*}, P_c) + M(P_s^{*}, P_c)
                    = D(P_s^{*}), $$
        with ``P_c`` the body's EXOGENOUS ``carbon_price`` and each ``q_i`` the
        producer's output FOC (D3-2).

        ASCII fallback:
            domestic_supply(P_s) = sum_i producer_i.product_supply(P_s; P_c)
            P_s* solves domestic_supply(P_s*) + imports(P_s*;P_c) = demand(P_s*)

        Symbols (units):
            P_s : steel/product price (solved)   [currency/t-steel]
            P_c : exogenous carbon price         [currency/tCO2]
            q_i : producer i output FOC          [t-steel/period]
            M   : import supply                  [t-steel/period]
            D   : demand                         [t-steel/period]

    Args:
        market: The inert-cap ``CarbonMarket`` carrying the stamped product body
            (``product_carbon_price``/``product_demand``/``product_import_supply``/
            ``product_producers``).

    Returns:
        The per-year detail dict (``market``/``equilibrium``/``participant_df`` +
        the ledger shape keys) for ``collect_path_results``.
    """
    carbon_price = float(getattr(market, "product_carbon_price", 0.0))
    demand = _demand_curve(dict(getattr(market, "product_demand", {})))
    imports = _import_supply(dict(getattr(market, "product_import_supply", {})))

    # Deterministic producer order (sort before iterating, house rules): the
    # aggregate-supply sum and the reporting frame both walk this list.
    producer_specs = sorted(
        list(getattr(market, "product_producers", [])), key=lambda p: str(p["name"])
    )
    params_by_name = {str(spec["name"]): _producer_params(spec) for spec in producer_specs}
    producers = [
        MultiCommodityProducer(name=str(spec["name"]), params=params_by_name[str(spec["name"])])
        for spec in producer_specs
    ]
    for producer in producers:
        producer.stamp_carbon_price(carbon_price)

    def domestic_supply(price_steel: float, price_carbon: float) -> float:
        return sum(producer.product_supply(price_steel, price_carbon) for producer in producers)

    result = solve_product_equilibrium(domestic_supply, carbon_price, demand, imports)
    price_steel = float(result["price"])

    # Leakage diagnostic (spec §4f, V-D3-4): foreign emissions gained per unit of
    # domestic emissions cut, measured against the NAMED no-policy counterfactual
    # (P_carbon = 0 ⇒ the CBAM charge is inactive too, since it scales with P_c).
    # Stashed in the equilibrium bundle; surfaced as the guarded "Leakage Rate"
    # column ONLY on multi-market product rows (dispatch._stamp_multi_market_
    # columns), so a single-market / carbon-only run never carries it. The
    # headline holds the P_c=0 counterfactual at the UN-ADOPTED σ (ruling #2);
    # the conditional holds it at the post-adoption σ′ (a secondary diagnostic).
    leakage_rate, conditional_leakage_rate = _leakage_diagnostic(
        producers, demand, imports, price_steel, carbon_price
    )

    # R37 (D3 adaptation, spec §7): the ACTUAL steel↔carbon joint loop gain
    # g = s_c·s_s from the linearised 2×2 clearing Jacobian at this operating
    # point. The shared-agent structural coupling has no external φ, so R37's
    # conservative ĝ=Π|φ| does not apply; |g|>=1 warns LOUDLY (never silently),
    # else DEBUG only. Evaluated per solve; harmless (no warning) for a
    # standalone product market whose sibling carbon leg is absent.
    loop_gain = product_scc_loop_gain(
        list(params_by_name.values()),
        b_d=demand.b_d,
        m=imports.m,
        price_steel=price_steel,
        price_carbon=carbon_price,
        cbam_coverage=imports.coverage if imports.cbam_enabled else 0.0,
        cbam_sigma_foreign=imports.sigma_foreign if imports.cbam_enabled else 0.0,
    )
    if abs(loop_gain) >= _LOOP_GAIN_WARN_THRESHOLD:
        logger.warning(
            "product market %r year %r: steel<->carbon joint loop gain |g|=%.4g >= 1 "
            "(R37, spec §7) — damped Gauss-Seidel may not contract; check "
            "demand elasticity / cap tightness / emission intensity.",
            market.scenario_name,
            market.year,
            loop_gain,
        )
    else:
        logger.debug(
            "product market %r year %r: joint loop gain g=%.4g < 1 (R37 silent)",
            market.scenario_name,
            market.year,
            loop_gain,
        )

    if not result["converged"]:
        logger.warning(
            "product market %r year %r: clearing did not converge (regime=%s, P_s=%.6g, P_c=%.6g)",
            market.scenario_name,
            market.year,
            result["regime"],
            price_steel,
            carbon_price,
        )

    outcomes = {
        str(spec["name"]): optimize_producer(
            params_by_name[str(spec["name"])], price_steel, carbon_price
        )
        for spec in producer_specs
    }
    rows = [
        _producer_row(
            market.scenario_name, market.year, str(spec["name"]), outcomes[str(spec["name"])]
        )
        for spec in producer_specs
    ]
    participant_df = pd.DataFrame.from_records(rows)

    # OBA cap-relaxation diagnostic (V-D3-5 ruling #4): output-based allocation
    # issues φ·Σq free allowances ON TOP of the auctioned cap, so at a binding
    # carbon price residual Σe = Cap + φ·Σq — OBA is cap-RELAXING (contrast CBAM,
    # cap-PRESERVING Σe=Cap). Surface φ·Σq (the cap relaxation) and the residual
    # gross emissions so the relaxation is never hidden. The multi-commodity
    # producer's OBA is always the marginal output-based design.
    oba_free_allocation = sum(
        params_by_name[str(spec["name"])].phi_oba * outcomes[str(spec["name"])].q
        for spec in producer_specs
    )
    gross_emissions = sum(outcomes[str(spec["name"])].emissions for spec in producer_specs)
    oba_mode = str(getattr(market, "product_oba_mode", "output_based"))

    # Clean-tech adoption trigger P* = M·θ (ruling #1): the nearest carbon price
    # that fires a switch — REPORTED so the user sees "the price that triggers the
    # switch" even though θ and M are kept separate. min over every option.
    trigger_prices = [
        opt.p_star
        for spec in producer_specs
        for opt in params_by_name[str(spec["name"])].technology_options
    ]

    # Equilibrium bundle: the T0 clearing result PLUS the auction-shaped keys the
    # summary host (scenario_summary(auction_outcome=...)) reads — inert here, as
    # the product market has no cap/auction (plan §1 cap buckets inert).
    equilibrium: dict[str, Any] = {
        **result,
        "auction_offered": 0.0,
        "auction_sold": 0.0,
        "unsold_allowances": 0.0,
        "coverage_ratio": 1.0,
        "leakage_rate": leakage_rate,
        "conditional_leakage_rate": conditional_leakage_rate,
        "oba_free_allocation": oba_free_allocation,
        "oba_mode": oba_mode,
        "gross_emissions": gross_emissions,
    }
    if trigger_prices:
        equilibrium["clean_tech_trigger_price"] = min(trigger_prices)

    logger.debug(
        "product market %r year %r cleared: P_s=%.6g, D=%.6g, S_dom=%.6g, M=%.6g (P_c=%.6g)",
        market.scenario_name,
        market.year,
        price_steel,
        float(result["quantity"]),
        float(result["domestic_supply"]),
        float(result["imports"]),
        carbon_price,
    )

    return {
        "market": market,
        "expected_future_price": 0.0,
        "starting_bank_balances": {},
        "equilibrium": equilibrium,
        "participant_df": participant_df,
    }


def solve_product_path(ordered_markets: list[CarbonMarket]) -> list[dict]:
    """Solve a chronologically ordered product-market path (D3-3).

    Each market is cleared INDEPENDENTLY per year (the product market has no
    inter-temporal banking in v1): domestic producer supply + imports = demand,
    at that year's exogenous carbon price. Mirrors the other engine-bound path
    solvers' ``ordered_markets -> list[dict]`` contract so
    ``engine/dispatch.py`` routes it with no special-casing beyond the one
    ``"product"`` branch.

    Args:
        ordered_markets: The scenario's product markets, sorted chronologically.

    Returns:
        One ledger-compatible detail dict per market-year (the
        ``_simulate_path_details`` shape ``collect_path_results`` consumes).
    """
    return [_solve_one_market(market) for market in ordered_markets]
