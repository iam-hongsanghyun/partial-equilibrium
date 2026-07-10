r"""Dixit–Pindyck irreversible-investment trigger analysis.

References
----------
- Dixit, A. K. & Pindyck, R. S. (1994). *Investment under Uncertainty*.
  Princeton University Press.
- PLANiT K-MSR working paper (July 2026), Section 6 and Appendices A.7/A.10:
  under price uncertainty an irreversible investor commits not at the
  Marshallian break-even P_NPV but at the trigger P* = [β/(β−1)]·P_NPV; a
  fully credible deterministic price floor removes the uncertainty in the
  binding region (σ_eff → 0) and bounds the multiple at the pure timing wedge
  r/y — it does not eliminate the hurdle.

This is a post-processing module: it takes a solved price path (any of the
repo's solvers) plus a volatility assumption and computes trigger multiples
and activation dates. It adds nothing to market clearing — the clearing
engine is deterministic; σ is an *input* here, e.g. the paper's pooled KAU
estimate σ ≈ 0.48, not an engine output.

Algorithm
---------
β > 1 is the positive root of the fundamental quadratic (Dixit–Pindyck 1994):

LaTeX:
$$
\tfrac{1}{2}\sigma^2\beta(\beta-1) + (r-y)\beta - r = 0,
\qquad
P^* = \frac{\beta}{\beta-1}\,P_{NPV}
$$

ASCII fallback:
    (sigma^2/2)*beta*(beta-1) + (r - y)*beta - r = 0 ;  P* = beta/(beta-1) * P_NPV

Closed form of the positive root, with a = σ²/2, b = r − y − σ²/2, c = −r:

    beta = (-b + sqrt(b^2 - 4*a*c)) / (2*a)                     (sigma > 0)
    beta = r / (r - y)                                          (sigma = 0)

and the σ → 0 limit of the multiple is β/(β−1) → r/y — the residual *timing*
wedge that survives even under certainty because the price path drifts up at
r − y > 0 (deferring a sunk outlay while its committed value appreciates
remains weakly profitable).

Symbols (units):
    sigma : annualized volatility of the price the investor faces
            [1/sqrt(yr), i.e. std of log returns per year]
    r     : discount rate [1/yr]  (paper: 0.055)
    y     : payout/convenience yield of the completed project [1/yr]
            (paper: 0.03)
    beta  : positive root of the fundamental quadratic [dimensionless, > 1]
    P_NPV : Marshallian break-even price [currency/tCO2]
    P*    : investment trigger price [currency/tCO2]

Worked values from the paper (regression-tested in
``tests/test_investment_trigger.py``):
    sigma = 0.20 → beta ≈ 1.54, multiple ≈ 2.86        (paper A.7)
    sigma = 0.30 → multiple ≈ 3.86                     (paper §6)
    sigma = 0.48 → multiple ≈ 6.4                      (paper §3, KAU estimate)
    sigma → 0    → beta = 2.2, multiple = r/y ≈ 1.83   (paper A.10)
"""

from __future__ import annotations

import math
from collections.abc import Mapping

__all__ = [
    "beta_positive_root",
    "trigger_multiple",
    "credible_floor_multiple",
    "effective_volatility",
    "activation_year",
]


def beta_positive_root(sigma: float, r: float, y: float) -> float:
    r"""Positive root β > 1 of the Dixit–Pindyck fundamental quadratic.

    Algorithm:
        $$\tfrac{1}{2}\sigma^2\beta(\beta-1) + (r-y)\beta - r = 0$$
        ASCII: (sigma^2/2)*beta*(beta-1) + (r-y)*beta - r = 0
        solved in closed form; sigma = 0 degenerates to beta = r/(r-y).

    Args:
        sigma: Annualized price volatility [1/sqrt(yr)]. Must be >= 0.
        r: Discount rate [1/yr]. Must be > 0.
        y: Payout/convenience yield [1/yr]. Must satisfy 0 < y (and y < r
            when sigma = 0, otherwise the certainty limit is undefined).

    Returns:
        β, dimensionless, strictly greater than 1.

    Raises:
        ValueError: On sigma < 0, r <= 0, y <= 0, or (sigma = 0 and y >= r).
    """
    if sigma < 0.0:
        raise ValueError(f"sigma must be >= 0, got {sigma}")
    if r <= 0.0:
        raise ValueError(f"r must be > 0, got {r}")
    if y <= 0.0:
        raise ValueError(f"y must be > 0, got {y}")

    if sigma == 0.0:
        if y >= r:
            raise ValueError(
                f"The certainty limit beta = r/(r-y) requires y < r, got r={r}, y={y}."
            )
        return r / (r - y)

    a = 0.5 * sigma * sigma
    b = r - y - a
    c = -r
    return (-b + math.sqrt(b * b - 4.0 * a * c)) / (2.0 * a)


def trigger_multiple(sigma: float, r: float, y: float) -> float:
    r"""Trigger multiple β/(β−1): how far above break-even the investor waits.

    Algorithm:
        $$P^*/P_{NPV} = \beta/(\beta-1)$$
        ASCII: multiple = beta / (beta - 1), beta from beta_positive_root().

    Args:
        sigma: Annualized price volatility [1/sqrt(yr)].
        r: Discount rate [1/yr].
        y: Payout/convenience yield [1/yr].

    Returns:
        The multiple P*/P_NPV, dimensionless, > 1. Increasing in sigma;
        equals r/y exactly at sigma = 0.
    """
    beta = beta_positive_root(sigma, r, y)
    return beta / (beta - 1.0)


def credible_floor_multiple(r: float, y: float) -> float:
    r"""The full-credibility bound on the hurdle: the pure timing wedge r/y.

    A fully credible deterministic floor schedule removes price uncertainty in
    the binding region (σ_eff → 0), so the multiple falls to its certainty
    limit — not to 1 (paper A.10):

    Algorithm:
        $$\lim_{\sigma\to 0}\frac{\beta}{\beta-1} = \frac{r}{y}$$
        ASCII: multiple -> r / y as sigma -> 0

    Args:
        r: Discount rate [1/yr].
        y: Payout/convenience yield [1/yr]. Must satisfy 0 < y < r.

    Returns:
        r/y, dimensionless (paper: 0.055/0.03 ≈ 1.83).
    """
    return trigger_multiple(0.0, r, y)


def effective_volatility(sigma_unfloored: float, credibility: float) -> float:
    r"""Reduced-form σ_eff(q): volatility faced under a partially credible floor.

    The paper (A.10) defines only the endpoints — σ_eff(1) = 0 (fully credible
    floor: price in the binding region is the announced schedule) and
    σ_eff(0) = σ (no credible floor) — and leaves the interior mapping
    unidentified ("the exact treatment ... is future work"). This helper uses
    the simplest interpolation consistent with those endpoints:

    Algorithm:
        $$\sigma_{eff}(q) = (1-q)\,\sigma_0$$
        ASCII: sigma_eff = (1 - q) * sigma_unfloored

    It is a modeling choice, not a paper result — treat interior values as
    illustrative bounds between ``trigger_multiple(sigma, r, y)`` (q = 0) and
    ``credible_floor_multiple(r, y)`` (q = 1).

    Args:
        sigma_unfloored: σ₀, the volatility with no credible floor
            [1/sqrt(yr)].
        credibility: q ∈ [0, 1], probability the announced floor schedule
            holds in the binding region [dimensionless].

    Returns:
        σ_eff [1/sqrt(yr)].

    Raises:
        ValueError: If credibility is outside [0, 1].
    """
    if not 0.0 <= credibility <= 1.0:
        raise ValueError(f"credibility must be in [0, 1], got {credibility}")
    return (1.0 - credibility) * sigma_unfloored


def activation_year(
    price_path: Mapping[str, float],
    break_even: float | Mapping[str, float],
    multiple: float = 1.0,
) -> str | None:
    r"""First year the price path reaches the investment trigger.

    Algorithm:
        ASCII: activation = min { t : P(t) >= multiple * P_NPV(t) }

    With ``multiple = 1`` this is break-even dating (how the K-MSR paper dates
    activation, understating the certainty-case trigger by the r/y wedge);
    pass ``trigger_multiple(...)`` or ``credible_floor_multiple(...)`` for the
    Dixit–Pindyck dating.

    Args:
        price_path: Year label → delivered price [currency/tCO2]. Years are
            scanned in ascending numeric order when labels parse as numbers,
            insertion order otherwise.
        break_even: P_NPV — a constant, or a year label → threshold mapping
            for declining thresholds (e.g. θ_steel,t falling with hydrogen
            costs) [currency/tCO2].
        multiple: Trigger multiple P*/P_NPV, dimensionless, >= 1.

    Returns:
        The first year label whose price weakly exceeds the trigger, or
        ``None`` if the path never reaches it.

    Raises:
        ValueError: If multiple < 1, or break_even lacks a year present in
            price_path.
    """
    if multiple < 1.0:
        raise ValueError(f"multiple must be >= 1, got {multiple}")

    def _sort_key(label: str) -> tuple[int, float, str]:
        try:
            return (0, float(label), label)
        except ValueError:
            return (1, 0.0, label)

    ordered_years = sorted((str(y) for y in price_path), key=_sort_key)
    for year in ordered_years:
        if isinstance(break_even, Mapping):
            if year not in break_even:
                raise ValueError(f"break_even has no threshold for year '{year}'.")
            threshold = float(break_even[year])
        else:
            threshold = float(break_even)
        if float(price_path[year]) >= multiple * threshold:
            return year
    return None
