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
    """Build validated :class:`ProducerParams` from a normalised producer spec."""
    return ProducerParams(
        gamma=float(spec["gamma"]),
        delta=float(spec["delta"]),
        sigma=float(spec["sigma"]),
        beta=float(spec["beta"]),
        a_max=float(spec["a_max"]),
        phi_oba=float(spec.get("phi_oba", 0.0)),
        f_lump=float(spec.get("f_lump", 0.0)),
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

    rows = [
        _producer_row(
            market.scenario_name,
            market.year,
            str(spec["name"]),
            optimize_producer(params_by_name[str(spec["name"])], price_steel, carbon_price),
        )
        for spec in producer_specs
    ]
    participant_df = pd.DataFrame.from_records(rows)

    # Equilibrium bundle: the T0 clearing result PLUS the auction-shaped keys the
    # summary host (scenario_summary(auction_outcome=...)) reads — inert here, as
    # the product market has no cap/auction (plan §1 cap buckets inert).
    equilibrium: dict[str, Any] = {
        **result,
        "auction_offered": 0.0,
        "auction_sold": 0.0,
        "unsold_allowances": 0.0,
        "coverage_ratio": 1.0,
    }

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
