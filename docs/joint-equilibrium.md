# D2 economic specification: the joint equilibrium model (cyclic PriceLinks)

Authored by ets-lead-economist (design gate, 2026-07-11). Binds the D2
executor orders (docs/joint-equilibrium-plan.md §6). Companion:
docs/platform-spec-d0-d1.md (D0/D1 spec), TODO.md:91 (floor-cancellation
2-cycle — a sibling prerequisite, §3).

## 1. The equilibrium object

A converged cyclic SCC computes a **joint (simultaneous) partial
equilibrium**: a price-path vector (P_m)_{m∈SCC} such that every market m
clears its OWN approach equilibrium (static Coase, Rubin/Schennach
banking, budget-Hotelling, Nash, or trigger-consistent adoption)
evaluated at its link inputs computed from the OTHER markets' converged
delivered paths — all satisfied simultaneously. With T_m = "solve market m
given inputs" and L the link compilation: P* = T(P*),
T_m(P) = clear_m(base_m ⊕ Σ_n L_{n→m}(P_n)).

Contrast D1 (recursive/block-recursive PE): D1 markets are exogenous to
their non-ancestors, solved once in topological order. A cyclic SCC's
markets are MUTUALLY endogenous — no valid solve order — so the vector is
found jointly. SURVIVING partial boundary: each market atomistic in
factor/income terms (no wage/numéraire/GE closure); own supply totals and
waterbed/bank identities untouched (I1). BREAKS deliberately: a market is
no longer atomistic in its SCC siblings — that feedback is the cycle's
purpose. Markets OUTSIDE the SCC (condensation-upstream) stay exogenous.

## 2. Existence / uniqueness / contraction (V-D2-6)

**Existence.** Each T_m maps into a compact per-year price box [0,P_max,m]
(the clearing bracket). Continuous MAC (linear/piecewise-sloped/smooth):
T continuous on a compact convex set → joint fixed point exists by
**Brouwer**. Discrete MAC (threshold, discrete adoption, floor-
cancellation): demand is a step correspondence, T upper-hemicontinuous →
**Kakutani gives an ε-equilibrium; a CRISP joint equilibrium need not
exist.** That non-existence must be surfaced (cycle-detection reporting,
R37), never faked as a converged number.

**Contraction — the checkable v1 condition.** Linearize T: market m's own
price response to its input is s_m = ∂P_m/∂input_m; cross-market Jacobian
J_{mn} = s_m·φ_{mn} (0 if no link n→m). **Unique globally-attracting fixed
point iff ρ(J) < 1** (spectral radius; equivalently diagonal-dominance /
gross-substitutes). Canonical 2-market cycle A↔B: eigenvalues
±√(s_A s_B φ_AB φ_BA), so the **loop gain g = s_A s_B φ_AB φ_BA, |g| < 1**.
Pass-through bound: s_m ∈ [0,1] (=1 in the discrete-pinned regime where
the price sits AT the shifted block cost; <1 when demand response or other
participants absorb part of the shift). Config-checkable WARNING (R37):
ĝ = Π|φ| along each cycle with s_m←1; ĝ ≥ 1 ⇒ WARN "near-critical/
divergent coupling". Sign: 0<g<1 monotone convergence; −1<g<0 oscillatory
convergence; g>1 monotone divergence (price → ceiling, NOT rescuable by
any w∈(0,1]); g<0, |g|>1 genuine period-2 oscillation (recoverable by
damping).

**Inner-solve non-convergence mid-outer-loop — HARD ABORT, never
damped-continue.** (i) Inner SOFT max-iters (banking supply-rule
solver.py:317-321; investment safety-rail): documented degradation the
inner owns; outer may proceed but MUST propagate Converged=0 into the
joint report. (ii) Inner HARD failure (bracket/RuntimeError, Brent
non-convergence): inner equilibrium undefined at that neighbor-price →
ABORT the SCC, stamp Joint Converged=0, surface the inner reason. Relaxing
over a hard inner failure is the papering-over the architecture forbids.

## 3. Damping (V-D2-5)

Default **w = 0.5** (coupling-loop precedent; converges for the
oscillatory case λ=−|g| when |g|<3 — a wide margin over the |g|<1
contraction band). Expose w∈(0,1] per SCC; w=1 = undamped Gauss-Seidel
(retained for the oscillation anchor). Adaptive/Aitken/Anderson =
**D3, not v1** (acceleration masks the cycle-detection/non-convergence
reporting that is v1's deliverable).

**Floor-cancellation 2-cycle (TODO.md:91) — SAME contraction family,
DIFFERENT locus, MUST NOT MERGE.** The 16.9-Mt cancellation 2-cycle
oscillates in the cancellation channel INSIDE one market's banking
supply-rule fixed point (solver.py:292-316), strictly BELOW the outer SCC
loop. D2 relaxation acts on the SCC price vector BETWEEN market solves and
does NOT (must not) damp the inner supply-schedule iteration. **BINDING
PREREQUISITE: the inner floor-cancellation damping is a separately-
designed sibling fix, and a single-market banking + unsold_treatment
"cancel" config must converge on its own (NO links) BEFORE any cyclic SCC
containing such a market is trusted.** An outer w large enough to hide the
inner 2-cycle would conceal a pathology present with zero links. R37's
WARNING is necessary but NOT sufficient for banking-cyclic-with-cancel
SCCs; the inner fix is a hard gate. Shared math, zero shared state.

### 3a. Joint Cycle Detected predicate — RATIFIED with corrections (2026-07-11)

D2-2's executor replaced §3's implied "‖P_k−P_{k−2}‖ ≈ 0" cycle signature
(which describes only the BOUNDED 2-cycle, λ=−1) with the FOLDING test
**period-2 iff dist(P_{k−2},P_k) < dist(P_{k−1},P_k)** (per-market relative
norm, V-D2-3). Economist CONFIRMED (2026-07-11): the folding test is the
correct operationalization and fixes an error in the §3 prose — under
Gauss-Seidel the effective iteration eigenvalue is the real loop gain
g = s_A·s_B·φ_AB·φ_BA (the ±√g Jacobi form does NOT apply), so anchor J2
at w=1 is a DIVERGING oscillation (λ=−1.5, |λ|>1) whose 2-ago distance is
small-but-nonzero-and-GROWING, which the ≈0 test never fires on. For a
real scalar iterate the folding test fires **iff |λ+1| < |λ|, i.e. iff
λ < −1/2**, partitioning the decision-relevant non-converged set (|λ|≥1)
exactly: λ ≤ −1 (bounded cycle + diverging oscillation) fires; λ ≥ 1
(monotone crawl) does not.

**FOUR BINDING CONDITIONS on the ratification (executor MUST satisfy all):**
1. **Diagnostic-only, NON-TERMINATING.** Cycle detection MUST NOT early-
   abort the outer loop. The band −1 < λ < −1/2 CONVERGES (|λ|<1) yet
   folds (λ<−1/2); an early break there would wrongly stamp a convergent
   SCC `Joint Converged=0`. The loop terminates ONLY on convergence
   (delta<tol) or the hard cap. **(joint.py currently BREAKS on detection
   — this is the bug to fix in D2-3: remove the break; derive cycle_period
   at loop exit.)**
2. **No latch.** If the run ultimately converges, `Joint Cycle Detected`
   reads 0 — a transient alternation during descent is NOT a reportable
   cycle. The period is meaningful only when `Joint Converged=0`.
3. **Terminal-sweep evaluation.** The flag reflects the asymptotic
   dominant mode: report period-2 only if folding persisted over the
   FINAL sweeps before the cap (e.g. fold_run ≥ 2 at cap-exit), not on an
   early transient.
4. **v1 scope = period-2 only.** Higher-period or complex-eigenvalue
   spiral non-convergence in ≥3-market SCCs correctly reports
   `Joint Converged=0` with NO period (0) — a true non-convergence of a
   non-period-2 kind, not a false negative. Document this limit.

Regression test to add: an SCC with −1 < λ < −1/2 (converges WITH
alternation) must return `converged=True, cycle_period=0` — the witness
for conditions 1 & 2. The existing J2-at-w=0.5 (λ=−0.25) is in the
non-folding zone and does NOT exercise this; the new test must sit in the
(−1, −1/2) folding-but-converging band.

## 4. Investment nesting (V-D2-4) — the equilibrium-concept call

**MIDDLE (adoption) nests INSIDE OUTER (SCC price loop) — forced.** A
backlink makes A's adoption depend on B (D1's block-triangularity relied
on one-way links). Each outer sweep re-runs each market's investment-
wrapped solve against current neighbor prices; acyclic SCCs stay exactly
D1.

**ADOPTION-AS-OUTER-FLOOR (monotone across outer iterations), NOT
re-derive-fresh.** (1) Economics: capex sunk, irreversibility physical
(re-derive would let a firm un-adopt when a sibling price dips — false).
(2) Termination: re-derive reintroduces the binary adoption state as a
discrete oscillation source (flip in→price drops→flip out→...) that
relaxation CANNOT damp (you cannot under-relax a 0/1 state) — the
floor-cancellation family again. The monotone floor forbids it: adoptions
accumulate, bounded by ΣN_i, FREEZE after finitely many sweeps, after
which the outer loop is a pure continuous price contraction. Termination =
**eventually-continuous** (finitely many discrete sweeps, then a
contraction). (3) Reuse: splice-carrier FLOOR + monotone-one-flip host
check transfer verbatim.

Equilibrium concept: a pair ((P_m), A), A the outer-accumulated monotone
adoption set, such that (i) each market clears given siblings' converged
prices AND its accumulated adoptions; (ii) every adopted pair crossed its
trigger on SOME sweep's delivered path (ex-ante, may be intermediate —
the D1.1 asymmetry); (iii) on the FINAL converged joint path every
non-adopted flagged pair sits below trigger. **PIN: the ex-post checks
run against the CONVERGED joint price vector, never an intermediate
sweep.** Ex-post regret of an entrant depressing the joint price is
permitted; ex-ante violation is not.

## 5. Convergence norm across mixed-unit markets (V-D2-3)

**Per-market RELATIVE dimensionless change, then max across markets:**
converged ⟺ max_{m∈SCC} [ max_t |P_m^k(t) − P_m^{k−1}(t)| /
max(P_ref,m, |P_m^k(t)|) ] < tol, tol scenario-level dimensionless
(default 1e-4). P_ref,m per-market scale (default the market's max
standalone price) prevents div-by-zero at P→0 (the oversupply boundary).
Every term dimensionless → max across mixed-unit markets well-posed AND
identifies the failing market. Escape hatch: per-market absolute atol in
the market's own price_unit for markets near zero price. Rejected: mixed
max|ΔP| (dimensionally invalid); a single weighted SCC index (weights
smuggle an economic choice into a convergence test; hides the failure
locus).

**Quantity convergence — CONDITIONAL, pinned.** v1 channels are ALL
price-driven (input = φ·P; both mac_cost and invest_break_even read P), so
quantities are deterministic functions of converged prices → the price
norm SUFFICES, no quantity check in v1. BUT any future genuine quantity
channel (A's volume Q_A into B) MUST add max_m |ΔQ_coupling,m|/Q_ref,m <
tol_Q — a price fixed point with drifting coupling quantities is not an
equilibrium; may not ship price-only. back_demand_estimate stays a
diagnostic, never a channel, so does not trigger this gate.

## 6. Remaining slots

- **V-D2-1 seed — BLESSED, D1 one-way seed = solve with cycle-closing
  backlinks CUT** (their φ·P contribution set to 0 = the recursive PE of
  the spanning DAG); when any cycle-edge φ=0 the seed IS the exact answer
  (J3). Correction to the plan wording: a price backlink seeds by cutting
  the edge, not via back_demand_estimate (a quantity diagnostic).
- **V-D2-2 sweep — Gauss-Seidel default; Jacobi is D3 (parallelism only).**
  GS spectral radius ≤ Jacobi for these M-matrices → faster; for a UNIQUE
  fixed point both reach the same point. PIN: when uniqueness is NOT
  guaranteed (loop gain near/over 1), the deterministic sweep order
  (declared market order, then market_id) is part of the equilibrium
  DEFINITION — GS can select different limit points by order. Document
  sweep order as economically load-bearing in the near-critical regime.
- **V-D2-7 self-link — FORBIDDEN (R36 stays).** Own-price feedback IS the
  elastic-baseline overlay computed jointly inside the single Brent solve,
  not an outer iteration. A self-link duplicates it and creates a
  degenerate size-1 SCC.
- **V-D2-8 banking-cyclic cap — rail AND diagnostic.** Iterations to tol ≈
  log(tol)/log(ρ); tol=1e-4, ρ=0.83 ⇒ ~50 sweeps × full banking solve
  (worst-case nesting). Default max_iterations = 50 for banking-cyclic
  SCCs (competitive-inner can afford more). Beyond it: ρ ≳ 0.83 =
  near-unit-root, calibration-fragile → "near-critical coupling" WARNING,
  not merely a timeout. Non-converged ⇒ Joint Converged=0, last iterate
  stamped, never an equilibrium.

## 7. Anchors (closed-form, for the D2-6 goldens)

Construction (a)-(c): each market one participant, affine MAC
MAC_m(a)=c_m+σ_m·a ⇒ standalone price α_m = c_m+σ_m(E_m−S_m); the mac_cost
channel shifts intercept c_m ⇒ s_m=1 exactly ⇒ loop gain g=φ_AB·φ_BA
hand-computable. Linear 2×2 fixed point: P_A=(α_A+φ_AB α_B)/(1−g),
P_B=(α_B+φ_BA α_A)/(1−g).

| ID | Anchor | Assertion | Tolerance |
|----|--------|-----------|-----------|
| J1 | 2-market cyclic, α_A=100 α_B=80 φ_AB=0.4 φ_BA=0.5 ⇒ g=0.2, P_A=165.0 P_B=162.5 | converged == hand; one sweep does NOT reach (iteration required); Joint Converged=1 | atol 1e-6; ≥2 iters exact |
| J2 | Oscillation boundary, g=−1.5 (relabelled ≥0). w=1 diverges; w=0.5 eigenvalue −0.25 converges | w=1 ⇒ Joint Converged=0 AND Joint Cycle Detected=2; w=0.5 ⇒ converges to hand value | period ==2 exact; atol 1e-6 |
| J3 | SCC-collapse, φ_BA=0 (edge structurally present, inert) | joint solver == D1 recursive PE bit-identically; Joint Outer Iterations==1 | exact (assert_frame_equal) |
| J4 | Upstream invariance: acyclic C→A feeding {A,B} | C bit-identical with/without the cycle iterating | exact |
| J5 | Mixed-unit norm (A ₩/tCO2, B $/MWh) | convergence correctly declared under the per-market relative norm | per-market rel < 1e-4 |
| J6 | Discrete-MAC non-existence: both threshold MACs, g<0, step straddling the fixed point | Joint Converged=0 + Joint Cycle Detected=k, no fabricated converged number (Kakutani-ε) | flag fires; no false convergence |

## Binding calls (summary)

Joint simultaneous PE, siblings mutually endogenous, factor/income
atomicity retained. Existence: Brouwer (continuous) / Kakutani-ε
(discrete). Contraction: ρ(J)<1, J_{mn}=s_m φ_{mn}; 2-cycle |g|<1,
config-checkable WARNING. Damping w=0.5; floor-cancellation inner 2-cycle
is a mandatory sibling prerequisite, never merged with outer relaxation.
Investment: MIDDLE-inside-OUTER, adoption-as-outer-FLOOR, ex-post checks
on the converged path only. Convergence: per-market relative norm;
quantity check conditional but pinned. GS default (sweep order
equilibrium-defining near-critical); one-way seed; self-link forbidden;
banking-cyclic cap 50 = rail + near-critical diagnostic. Six hand-solvable
anchors.
