r"""Joint-equilibrium outer loop over a cyclic SCC (T3).

The D2 joint-equilibrium engine's back half (``docs/joint-equilibrium.md`` §1-3,
§5-6; ``docs/joint-equilibrium-plan.md`` §1, §3, work order D2-2). Given ONE
cyclic strongly-connected component (from :func:`engine.scc.condensation_order`),
finds the joint (simultaneous) partial equilibrium — the price-path vector
``(P_m)`` such that every market m clears its own approach equilibrium evaluated
at its SCC siblings' converged delivered paths (``docs/joint-equilibrium.md``
§1: ``P* = T(P*)``). Markets OUTSIDE the SCC stay exogenous; acyclic components
never reach here (D1 solves them byte-identically).

The solve is a damped Gauss-Seidel fixed point over the SCC's price-path vector,
the coupling-loop pattern (Feedback Option B, ``pe.coupling.loop``) lifted from a
scalar-per-year price to a per-market price PATH:

  * one outer iteration = one Gauss-Seidel SWEEP in deterministic market order,
    each market reading the MOST-RECENT delivered paths of already-swept siblings
    (in-sweep update, not Jacobi; ``docs/joint-equilibrium.md`` §6 V-D2-2);
  * relaxation ``P_next = (1-w)·P_prev + w·P_swept`` applied to the WHOLE vector
    AFTER the sweep (``core.relaxation.relax_pathmap``; §3, w=0.5 default);
  * convergence = max over SCC markets of the per-market RELATIVE (dimensionless)
    change (``core.relaxation.max_pathmap_relative_change``; §5) — a bare
    ``max|ΔP|`` across mixed ``flow_unit`` markets is dimensionally meaningless.

Decoupling (the D2-5 injection hook). ``solve_one_market`` is INJECTED: it owns
link application (``engine.links.apply_inbound_links``) and the per-approach
path solve, so this module imports NEITHER dispatch NOR the channel runtime and
never reaches T4 (coupling/workflows). D2-3 injects the real per-approach
closure; D2-5 will wrap that same closure in the investment-adoption middle loop
(adoption-as-outer-FLOOR, ``docs/joint-equilibrium.md`` §4) WITHOUT changing this
outer loop — the hook is deliberately left clean here and NOT implemented.

Termination discipline (banking/coupling precedent, §6 V-D2-8). A non-converged
SCC is NEVER reported as an equilibrium: the loop terminates ONLY on convergence
(``delta < tol``) or the hard ``max_iterations`` cap, logs a ``warning``, and
returns the last iterate stamped ``Joint Converged = 0.0``. Success stamps
``Joint Converged = 1.0`` plus the outer-iteration count, the final max
normalized change, and the cycle period.

Cycle detection is DIAGNOSTIC-ONLY and NON-TERMINATING (``docs/joint-equilibrium.md``
§3a, RATIFIED 2026-07-11, four binding conditions). The folding signature (an
iterate landing closer to its 2-ago position than its 1-ago one — a period-2
anti-phase mode) fires for a real scalar mode ``P_k = P* + λ^k e_0`` iff
``λ < -1/2``; the band ``-1 < λ < -1/2`` CONVERGES yet folds, so folding MUST
NOT abort the loop (an early break there would wrongly stamp a convergent SCC
``Converged = 0``). The period is DERIVED ONCE at loop exit, terminally: a
converged run reports period 0 (no latch — a transient descent alternation is
not a reportable cycle); a non-converged run reports period 2 only when folding
persisted over the FINAL sweeps (``fold_run >= _TERMINAL_FOLD_SWEEPS`` at
cap-exit), else period 0. v1 detection is period-2 ONLY: a higher-period or
complex-eigenvalue spiral in a >=3-market SCC correctly reads ``Converged = 0``
with period 0 (true non-convergence, not a false negative).

References:
    docs/joint-equilibrium.md §1 (equilibrium object), §2 (contraction ρ(J)<1),
    §3 (damping w=0.5), §5 (mixed-unit norm), §6 (seed, sweep, cap), anchors
    J1-J6. docs/joint-equilibrium-plan.md §1, §3, §5 (work order D2-2).
    pe.coupling.loop (the scalar-price precedent this lifts to a path vector).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from ..core.relaxation import (
    max_pathmap_relative_change as _rel_change_impl,
    relax_pathmap as _relax_impl,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from ..core.protocols import LinkSpec

logger = logging.getLogger(__name__)

# A delivered price path: {year label -> price}, the ``engine.dispatch._delivered_path``
# shape (item["equilibrium"]["price"] per year). Keyed by year label only; the SCC
# member id keys the mapping-of-paths the sweep threads.
PathMap = dict[str, float]

# The D2-1 relaxation kernels are key-generic (dict.get / union only), but their
# ``core.relaxation.PathMap`` alias narrows keys to the coupling loop's
# ``(scenario, year)`` tuple. The joint delivered path keys by year label alone,
# so we bridge the nominal key-type gap with a cast at import — calling the EXACT
# D2-1 implementations (never a reimplementation), just re-typed for this key.
relax_pathmap = cast("Callable[[PathMap, PathMap, float], PathMap]", _relax_impl)
max_pathmap_relative_change = cast("Callable[[PathMap, PathMap, float], float]", _rel_change_impl)

# Module DEFAULTS (no hardcoded magic in the function body; overridable per SCC via
# the arguments, and by D2-3 from the scenario ``joint_solver`` block). These are
# scenario-level modelling defaults, not secrets — the BANKING_DEFAULTS / MSR_DEFAULTS
# precedent (core.defaults), not .env keys.
JOINT_DEFAULTS = {
    # w — relaxation weight [dimensionless], w in (0, 1]; 0.5 damps the oscillatory
    # band |g| < 3 (docs/joint-equilibrium.md §3), w = 1 = undamped Gauss-Seidel.
    "relaxation": 0.5,
    # tol — per-market relative (dimensionless) convergence tolerance (§5 default 1e-4).
    "tolerance": 1e-4,
    # outer-sweep cap; the banking-cyclic worst-case rail (§6 V-D2-8: ~50 for ρ≈0.83).
    "max_iterations": 50,
    # P_ref floor [price unit]; floors the per-market norm denominator so a market
    # driven to the oversupply boundary P -> 0 stays well-posed (§5).
    "reference_floor": 1.0,
}

# Cycle-detection constants (docs/joint-equilibrium.md §3a). NOT tunable knobs —
# they encode the ratified predicate, so they live as named module constants
# (no bare magic in the loop body):
#   * _PERIOD_2 — the only period the v1 detector reports (a period-2 anti-phase
#     2-cycle); higher-period / complex spirals report period 0 (condition 4).
#   * _TERMINAL_FOLD_SWEEPS — consecutive folding sweeps required AT cap-exit to
#     call the terminal mode period-2 (condition 3: asymptotic, not transient).
_PERIOD_2 = 2
_TERMINAL_FOLD_SWEEPS = 2

__all__ = [
    "JOINT_DEFAULTS",
    "JointResult",
    "solve_joint_scc",
]

# The injected per-market solver has signature
#   solve_one_market(market_id, delivered_paths) -> that market's delivered path,
# where ``delivered_paths`` is {market_id: {year label: price}} for the whole SCC as
# it stands mid-sweep (most-recent for already-swept siblings, prior iterate otherwise).


@dataclass(frozen=True)
class JointResult:
    """Outcome of one cyclic SCC's joint solve (frozen).

    Attributes:
        market_paths: Final delivered price path per SCC market
            ``{market_id: {year label: price [currency/unit]}}`` — the last
            iterate; an EQUILIBRIUM only when ``converged`` is ``True``.
        converged: ``True`` iff the max normalized change fell below
            ``tolerance`` within the cap; ``False`` on the hard cap OR a
            confirmed oscillation (never reported as an equilibrium, §6).
        outer_iterations: Number of Gauss-Seidel sweeps performed [-].
        max_normalized_change: The final per-market relative (dimensionless)
            change, max over SCC markets (§5) [-].
        cycle_period: Detected oscillation period (``2`` for the common
            anti-phase cycle), or ``0`` if none — an oscillation asks for MORE
            DAMPING; a slow crawl (``cycle_period == 0`` but not converged)
            asks for more iterations (§3).
        reference_scales: The per-market P_ref used in the norm
            ``{market_id: P_ref [price unit]}`` (frozen after the first sweep,
            or the caller's override) — reported for reproducibility.
    """

    market_paths: dict[str, PathMap]
    converged: bool
    outer_iterations: int
    max_normalized_change: float
    cycle_period: int
    reference_scales: dict[str, float] = field(default_factory=dict)

    def report_columns(self) -> dict[str, float]:
        """Return the guarded ``Joint *`` summary columns (D2-3 stamps these).

        Returns:
            The four float-valued columns — ``Joint Converged`` (1.0/0.0),
            ``Joint Outer Iterations``, ``Joint Max Normalized Change``, and
            ``Joint Cycle Detected`` (0.0 if none) — stamped only on
            cyclic-SCC markets (key-presence guard, ``docs/joint-equilibrium-plan.md``
            §5).
        """
        return {
            "Joint Converged": 1.0 if self.converged else 0.0,
            "Joint Outer Iterations": float(self.outer_iterations),
            "Joint Max Normalized Change": float(self.max_normalized_change),
            "Joint Cycle Detected": float(self.cycle_period),
        }


def _sweep(
    sweep_order: Sequence[str],
    solve_one_market: Callable[[str, Mapping[str, Mapping[str, float]]], Mapping[str, float]],
    entering: Mapping[str, PathMap],
) -> dict[str, PathMap]:
    """One Gauss-Seidel sweep: solve each market against the most-recent paths.

    Threads the copy-on-write output of each market's solve into the working
    map, so a later market in ``sweep_order`` reads the RAW (pre-relaxation)
    just-solved path of an earlier sibling and the prior-iterate path of a
    not-yet-swept sibling (in-sweep update, ``docs/joint-equilibrium.md`` §6
    V-D2-2). Relaxation is applied by the caller AFTER the full sweep.

    Args:
        sweep_order: SCC market ids in the deterministic sweep order.
        solve_one_market: Injected per-market solver (see :func:`solve_joint_scc`).
        entering: The iterate entering the sweep ``P_{k-1}`` per market.

    Returns:
        The raw swept paths ``P_swept`` per market.
    """
    working: dict[str, PathMap] = {m: dict(entering[m]) for m in sweep_order}
    for m in sweep_order:
        working[m] = dict(solve_one_market(m, working))
    return working


def solve_joint_scc(
    scc_markets: Sequence[str],
    solve_one_market: Callable[[str, Mapping[str, Mapping[str, float]]], Mapping[str, float]],
    *,
    links: Sequence[LinkSpec],
    relaxation: float | None = None,
    max_iterations: int | None = None,
    tolerance: float | None = None,
    initial_guess: Mapping[str, Mapping[str, float]] | None = None,
    reference_scales: Mapping[str, float] | None = None,
) -> JointResult:
    r"""Solve one cyclic SCC to its joint equilibrium (damped Gauss-Seidel).

    Iterates sweep -> relax -> convergence-check over the SCC's price-path
    vector until the per-market relative change falls below ``tolerance`` or a
    cap/oscillation stops it. See the module docstring for the decoupling
    contract and the D2-5 investment hook.

    Algorithm:
        Damped Gauss-Seidel on the price-path vector (``docs/joint-equilibrium.md``
        §1-3, §5-6). Let ``T_m`` solve market m at its inputs and ``w`` be the
        relaxation weight.

        LaTeX:
        $$ P^{k}_{\text{swept},m} = T_m\big(P^{k}_{\text{swept},n<m},\;
             P^{k-1}_{n\ge m}\big), \qquad
           P^{k}_m = (1-w)\,P^{k-1}_m + w\,P^{k}_{\text{swept},m}, $$
        $$ \delta_k = \max_{m\in\mathrm{SCC}} \max_t
             \frac{\big|P^{k}_m(t) - P^{k-1}_m(t)\big|}
                  {\max\!\big(P_{\mathrm{ref},m},\, |P^{k}_m(t)|\big)}
           \;<\; \mathrm{tol} \;\Rightarrow\; \text{converged}. $$

        ASCII fallback:
            P0 = initial_guess (D1 one-way seed) or empty (seed = back-links cut)
            fold_run = 0
            for k = 1 .. max_iterations:
                swept = gauss_seidel_sweep(P_{k-1})        # in-sweep updates
                P_k   = (1-w)*P_{k-1} + w*swept            # relax whole vector
                d1    = max_m per_market_relative_change(P_{k-1,m}, P_{k,m})
                if d1 < tol: converged = True; break       # ONLY exit besides cap
                # folding = closer to the 2-ago iterate than the 1-ago one.
                # DIAGNOSTIC ONLY — NEVER breaks the loop (§3a condition 1).
                if k >= 3 and rel_dist(P_{k-2}, P_k) < d1: fold_run += 1
                else:                                       fold_run = 0
            # terminal period derivation, evaluated ONCE at exit (§3a cond. 2-4):
            cycle_period = 2 if (not converged and fold_run >= 2) else 0

        Symbols (units):
            P_m(t)      : market m's delivered price in year t   [currency_m/unit_m]
            w           : relaxation weight                       [dimensionless, (0,1]]
            P_ref,m     : market m's reference price scale        [currency_m/unit_m]
            delta_k     : per-market relative change, max over m  [dimensionless]
            tol         : convergence tolerance                   [dimensionless]
            k           : outer-iteration (sweep) index           [-]

    Seed (V-D2-1, BLESSED). ``initial_guess`` is the D1 one-way seed (forward
    links normal, cycle-closing back-links CUT — their φ·P contribution set to
    0); with ``None`` the cold first sweep reproduces exactly that seed, since a
    not-yet-swept sibling contributes a zero path (the cut back-link). When a
    cycle edge is inert (φ=0) the seed IS the answer and the loop converges in
    ONE iteration (anchor J3).

    Cycle detection (§3a, RATIFIED — four binding conditions; DIAGNOSTIC-ONLY,
    NON-TERMINATING). Tracks the relative distance to the 2-ago iterate
    ``P_{k-2}`` alongside the 1-ago change ``δ_k``: the iterate FOLDS when it is
    closer to its 2-ago position than its 1-ago position (``dist(P_{k-2}, P_k) <
    δ_k``). For a real scalar mode ``P_k = P* + λ^k e_0`` this fires **iff λ <
    -1/2**, which partitions the non-converged set (|λ| ≥ 1) exactly — λ ≤ -1
    (bounded cycle + diverging oscillation) folds; λ ≥ 1 (monotone crawl) does
    not — BUT it ALSO fires in the CONVERGING band -1 < λ < -1/2 (|λ| < 1). So
    folding CANNOT terminate the loop (condition 1): an early break in that band
    would stamp a convergent SCC ``Joint Converged = 0``. This loop only
    ACCUMULATES the run of consecutive folds (``fold_run``); the period is
    derived ONCE at loop exit (conditions 2-4):

    * converged (any reason it converged) ⇒ ``cycle_period = 0`` — NO latch; a
      transient descent alternation is not a reportable cycle, and the period is
      meaningful only when ``Joint Converged = 0``;
    * NOT converged AND folding persisted over the FINAL sweeps
      (``fold_run >= _TERMINAL_FOLD_SWEEPS`` at cap-exit) ⇒ ``cycle_period = 2``
      — a terminal period-2 oscillation (both the BOUNDED λ = -1 cycle and the
      DIVERGING λ < -1 oscillation, anchor J2 at w=1), asking for more damping
      (a smaller w), not more iterations;
    * NOT converged AND non-folding at exit (monotone crawl, or a higher-period
      / complex-eigenvalue spiral in a >=3-market SCC) ⇒ ``cycle_period = 0`` —
      v1 detection is period-2 ONLY (condition 4); this is a TRUE
      non-convergence with no reportable period, not a false negative.

    Args:
        scc_markets: The SCC's market ids in the deterministic SWEEP ORDER
            (``engine.scc.SCC.members``); the order is part of the equilibrium
            definition in the near-critical regime (§6 V-D2-2).
        solve_one_market: Injected callable ``(market_id, delivered_paths) ->
            path``; it owns link application and the per-approach solve (the
            D2-3 / D2-5 hook). ``delivered_paths`` is the whole-SCC working map
            ``{market_id: {year: price}}``.
        links: The scenario's links (kw-only); the intra-SCC edges are logged
            for cycle context. Kept on the signature for D2-3's SCC-scoped link
            set even though ``solve_one_market`` owns their application.
        relaxation: w in (0, 1]; ``None`` -> ``JOINT_DEFAULTS["relaxation"]``.
        max_iterations: outer-sweep cap; ``None`` -> ``JOINT_DEFAULTS``.
        tolerance: per-market relative tolerance; ``None`` -> ``JOINT_DEFAULTS``.
        initial_guess: the D1 one-way seed per market; ``None`` -> cold start
            (first sweep reproduces the seed with back-links cut).
        reference_scales: per-market P_ref override; ``None`` -> frozen after
            the first sweep as ``max(reference_floor, max_t |P_swept,m(t)|)``
            (≈ the market's standalone scale, §5).

    Returns:
        A :class:`JointResult`; ``converged`` is ``True`` only for a genuine
        equilibrium.

    Raises:
        ValueError: ``relaxation`` outside ``(0, 1]``, non-positive
            ``max_iterations``, or non-positive ``tolerance`` (loud validation).
    """
    w = JOINT_DEFAULTS["relaxation"] if relaxation is None else float(relaxation)
    cap = int(JOINT_DEFAULTS["max_iterations"] if max_iterations is None else max_iterations)
    tol = float(JOINT_DEFAULTS["tolerance"] if tolerance is None else tolerance)
    ref_floor = float(JOINT_DEFAULTS["reference_floor"])

    if not 0.0 < w <= 1.0:
        raise ValueError(f"relaxation w must be in (0, 1], got {w!r}.")
    if cap < 1:
        raise ValueError(f"max_iterations must be >= 1, got {cap!r}.")
    if tol <= 0.0:
        raise ValueError(f"tolerance must be > 0, got {tol!r}.")

    order = list(scc_markets)
    order_set = set(order)
    intra_edges = sum(
        1 for link in links if link.from_market in order_set and link.to_market in order_set
    )
    logger.debug(
        "solve_joint_scc: |SCC|=%d, intra-SCC edges=%d, w=%.3g, tol=%.3g, cap=%d",
        len(order),
        intra_edges,
        w,
        tol,
        cap,
    )

    if not order:
        return JointResult(
            {}, converged=True, outer_iterations=0, max_normalized_change=0.0, cycle_period=0
        )

    # P_{k-1} entering the next sweep; the D1 one-way seed (or the cold-start
    # empty seed, whose first sweep cuts back-links — V-D2-1).
    previous: dict[str, PathMap] = {m: dict((initial_guess or {}).get(m, {})) for m in order}
    two_ago: dict[str, PathMap] | None = None
    ref: dict[str, float] | None = (
        {m: max(ref_floor, float(reference_scales[m])) for m in order}
        if reference_scales is not None
        else None
    )

    fold_run = 0
    converged = False
    delta = 0.0
    iterations = 0

    for k in range(1, cap + 1):
        iterations = k
        swept = _sweep(order, solve_one_market, previous)
        current = {m: relax_pathmap(previous[m], swept[m], w) for m in order}

        if ref is None:  # freeze the per-market scale after the first sweep (§5)
            ref = {
                m: max(ref_floor, max((abs(v) for v in swept[m].values()), default=0.0))
                for m in order
            }

        delta = max(max_pathmap_relative_change(previous[m], current[m], ref[m]) for m in order)
        logger.debug("solve_joint_scc: sweep k=%d max_normalized_change=%.3e", k, delta)

        if delta < tol:
            converged = True
            previous = current
            break

        # Folding bookkeeping — DIAGNOSTIC-ONLY, NON-TERMINATING (§3a condition 1).
        # The iterate folds toward its 2-ago position (the period-2 signature)
        # iff it is closer to P_{k-2} than to P_{k-1}; for a real scalar mode
        # this fires iff λ < -1/2, INCLUDING the CONVERGING band -1 < λ < -1/2.
        # So this MUST NOT break the loop (D2-2's early ``break`` on fold_run >= 2
        # is the bug named in docs/joint-equilibrium.md §3a). We only accumulate
        # the consecutive-fold run; the terminal derivation below reads it.
        if two_ago is not None:
            fold = max(max_pathmap_relative_change(two_ago[m], current[m], ref[m]) for m in order)
            if fold < delta:  # folding back toward the 2-ago iterate
                fold_run += 1
            else:
                fold_run = 0

        two_ago = previous
        previous = current

    # Terminal cycle-period derivation (§3a conditions 2-4), evaluated ONCE at
    # loop exit — never latched mid-descent. Converged ⇒ period 0 (no latch).
    # Not converged AND folding persisted over the FINAL sweeps ⇒ terminal
    # period-2; otherwise (monotone crawl, or a higher-period / complex spiral)
    # period 0 — a true non-convergence, v1 detection being period-2 ONLY.
    cycle_period = _PERIOD_2 if (not converged and fold_run >= _TERMINAL_FOLD_SWEEPS) else 0

    if not converged and cycle_period == _PERIOD_2:
        logger.warning(
            "solve_joint_scc: period-2 oscillation on a %d-market SCC persisting to the "
            "max_iterations cap (%d) (max_normalized_change=%.3e); w=%.3g insufficient — "
            "NOT an equilibrium. Reduce w (more damping).",
            len(order),
            cap,
            delta,
            w,
        )
    elif not converged:
        logger.warning(
            "solve_joint_scc: hit the max_iterations cap (%d) on a %d-market SCC without "
            "convergence (max_normalized_change=%.3e, no period-2 cycle — a slow crawl or "
            "a higher-period/complex spiral; raise max_iterations or check ρ near unit "
            "root). NOT an equilibrium.",
            cap,
            len(order),
            delta,
        )

    return JointResult(
        market_paths={m: dict(previous[m]) for m in order},
        converged=converged,
        outer_iterations=iterations,
        max_normalized_change=float(delta),
        cycle_period=cycle_period,
        reference_scales=dict(ref) if ref is not None else {},
    )
