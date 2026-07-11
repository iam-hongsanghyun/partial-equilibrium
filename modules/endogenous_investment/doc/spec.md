# Endogenous Investment — Binding Specification

*(Moved from `docs/invest-feedback-spec.md` — WO-17 doc fold. Companion:
[`reference.md`](reference.md) — the technology-transition mechanism this
spec extends with a price-feedback trigger.)*

## Binding specification: endogenous investment ↔ price feedback (Phase 1)

Authored by ets-lead-economist (design gate, 2026-07-11). Binding on the
architecture and implementation. Sign-off requires equivalence-verifier
green on anchors V3/V6 plus the boundary checks in D1.3 and D3.

Paper motivation: K-MSR §7 names this gap — "the firm's investment is
post-processing on an exogenous price path, not a two-way equilibrium …
the priority extension is the investment decision as optimal stopping
against a partially credible, escalating price barrier"
(docs/k-msr-condensed.md:118-126). This feature closes it in reduced form.

## D1. Equilibrium concept

**D1.1 The object computed** — a *trigger-consistent adoption
equilibrium*: a pair (P, A), A = {(participant i, technology j) →
adoption year τ_ij}, such that:

- (market consistency) P is the approach's own equilibrium (competitive
  per-year clearing with cap rules; or the Rubin/Schennach banking
  equilibrium with its internal supply-rule fixed point) given the
  participant structure implied by A (capacity effective from τ+L, D2.4);
- (stopping consistency) every adopted pair crossed its trigger on the
  iterate that triggered it: τ_ij = min{t : P_delivered(t) ≥ P*_j(t)};
  and on the FINAL path, every non-adopted flagged pair satisfies
  P_delivered(t) < P*_j(t) for all t — a loud assertion (no missed
  adoption), the investment analogue of the window boundary checks.

Deliberate asymmetry: an adopted pair may fail its trigger on the final
path (the entrant depresses the post-adoption price) — standard discrete
entry. Adoption events may violate the trigger inequality EX POST, never
EX ANTE. Log at INFO with the margin, never silent.

**D1.2 Which prices adoption reads (competitive)** — the DELIVERED spot
path of the previous outer iterate (post-overlay, floor-clipped, clip-
last per F3); at convergence, the equilibrium path itself. Perfect-
foresight in the fixed point; the rule itself is a spot-crossing rule
(activation_year semantics). NOT configurable.
- Rejected: the expectations module's expected prices (one-year-ahead
  banking signals; double-counts waiting value — the D–P multiple already
  capitalizes deferral option value).
- Rejected: myopic within-iteration adoption (violates the lagged-state
  doctrine; the R29 rule-free inner loop extends verbatim — the adoption
  loop is strictly OUTSIDE the existing solve).
- Delivered (not pre-clip) price is load-bearing: K-MSR Results 2–3 are
  that the auction reserve delivers the trigger; the pre-clip price would
  make the paper's central instrument invisible to the investment rule.

**D1.3 Banking boundary — OUTER loop around solve_banking_path, not
inside the window fixed point.** F4 applies to supply rules (rule and
per-year lagged state are two halves of one fixed point). The investment
rule reads a WHOLE-HORIZON path object and writes the DEMAND SYSTEM
itself; a banking schedule evaluation must stay a pure function of
(prices, bank) with e_t(·) fixed, and its convergence metric is a supply
delta — mutating participants inside it breaks purity, leaves "which
iterate's prices" undefined, and measures a demand-side change with a
supply metric. The state the investment rule reads only EXISTS outside
solve_banking_path — putting the rule inside would split rule from
state. Nesting: inner = full existing banking solve fully re-converged
per adoption state (window search included — the window (a,b) shifts
with adoption); outer = adoption. The K-MSR transition feedback
(adoption → lower e_t → bigger bank → MSR intake) flows automatically
through the inner loop with ZERO MSR changes.

**D1.4 Existence, cycling, termination** — binding:
1. Monotone adoption across outer iterations (once adopted, never
   un-adopted) — this IS irreversibility; ex-post regret is the known
   deterministic-limit property of trigger rules.
2. At most ONE flip per outer iteration, tie-broken deterministically:
   earliest crossing year → largest relative exceedance
   P_delivered(τ)/P*(τ) → declared config order. Sequential-entry
   selection; reproducible (goldens are order-sensitive).
3. Termination: ≤ N_flagged + 1 outer iterations, each one inner solve.
   Combinatorial — no damping parameter, no outer tolerance.
   invest_max_outer_iters is a safety rail; exhaustion = WARNING + last
   iterate.
- Rejected: fractional adoption smoothing (destroys the discrete
  irreversible state); tâtonnement-then-commit (computes the maximal
  consistent set, an open-loop planner, can cycle).

## D2. Decision rule — reuse analysis/investment_trigger.py as the
single source of the math; the feature adds state, never re-derives

**D2.1 Trigger** P*_j(t) = M_j · θ_j(t):
- θ_j(t): Marshallian break-even, scalar or {year: value} (the paper's
  input-price-endogenous thresholds), activation_year semantics incl.
  missing-year ValueError. REQUIRED, no default.
- M_j = trigger_multiple(σ_eff, r, y); σ_eff = effective_volatility(σ_j,
  q) = (1−q)·σ_j. The interior credibility mapping (linear-in-σ) is a
  documented modelling choice, not a paper result (A.10 — AMBIGUOUS,
  question recorded for the authors).
- trigger_mode="break_even" sets M ≡ 1 (the paper's own activation
  dating; needed for V1a).
- σ_j exogenous per technology (the clearing engine is deterministic; σ
  is an input, not an engine output). No in-model volatility in Phase 1.
- r defaults to scenario discount_rate; overridable per technology.
- y (payout_yield) per technology, REQUIRED — r/y is the certainty-limit
  hurdle; a defaulted y is an economic constant hiding in a fallback.

**D2.2 Credibility & policy events** — q is CONFIG STATE (per-technology
credibility; scenario invest_credibility override). An announced decree
raises credibility IFF the event declares it: policy_events[k].changes =
{"invest_credibility": …} through the existing events mechanism —
announcement-dated credibility comes free from segment re-solving.
- Rejected: hardwiring "floor configured ⇒ q=1". A guaranteed price is
  not a guaranteed investment (paper §6); Kydland–Prescott — the model
  must not automatically believe announced rules either.

**D2.3 Lag** — decision at τ (first crossing on the triggering iterate);
capacity at τ+L (L ∈ ℤ≥0). In [τ, τ+L): structurally unchanged, no cost
booked. State flips at τ (that is what carries across splices).

**D2.4 Capacity** — one irreversible tranche per (participant,
technology): adoption makes the flagged TechnologyOption available at
its configured max_activity_share. Incremental adoption = multiple
flagged options. Post-adoption UTILIZATION is reversible (the existing
SLSQP portfolio chooses within the cap). Capex irreversible, dispatch
reversible. fixed_cost semantics unchanged (per-period overhead while
active); one-time capex belongs inside θ ONLY (V5 guards the double
count).

**D2.5 Supersession of the reversible choice** — a technology flagged
with an invest_trigger block is REMOVED from the reversible choice set
until τ+L, entering at its cap thereafter. Unflagged technologies keep
today's semantics bit-identically. Consequence (binding, subtle):
"feature ON but never triggered" == "same scenario with the flagged
option DELETED" — not "with the flag removed" (V3). With no flags
anywhere, no code path changes (all 37 goldens bit-identical).

## D3. Vintaging — availability gating; never mutate MAC blocks or
initial_emissions

**D3.1** Adoption = the flagged option joining the participant's
technology set from τ+L: explicit portfolio member with its own MAC and
its own lower initial_emissions through share aggregation. Rejected:
mutating base-technology MAC blocks (uninspectable; double-counts);
scaling participant.initial_emissions (already three writers in a pinned
precedence chain: sector → trajectory → OBA; plus the Option A
multiplier — a fourth writer is the exact cross-feature hazard the
builder pins).

**D3.2** The adoption mask is SOLVE-TIME STATE, not a build transform:
applied where the technology list is read (compliance), per year, after
the entire build pipeline. Pinned order: sector → trajectory → OBA
(build) → Option A multiplier (in-clearing) → adoption mask (outer
state). Stamping follows the stamp_and_attach precedent: one sanctioned
mutator, loud guard — flagged options with invest_feedback_enabled false
is a ValueError, never a silent ignore. The outer loop owns an
AdoptionState object; shared participants are never mutated mid-solve.

**D3.3** Banking/MSR interaction — the window's e_t(p) reaches
compliance through total_net_demand at pinned prices, so a per-year mask
makes post-adoption demand visible to the window budget with zero solver
changes: cumulative e_t falls → bank grows → MSR Observables.begin_bank
sees it → intake responds. That chain IS the K-MSR transition claim's
missing feedback. No MSR changes; the F2 freeze untouched.

**D3.4** Policy-event carrier — summary column "Investment Adoptions"
(serialized participant/technology:adoption_year pairs) on every year
row; carrier stamps invest_adopted into the next segment, ALWAYS-carry.
Stamped adoptions are FLOORS on later segments' adoption sets — a late
announcement cannot un-adopt an earlier investment (irreversibility
doing policy work: late reversals are economically costly in-model).
SpliceCarrier carries scalar column→field today; serializing the mapping
vs extending the protocol is the architect's choice; the monotone-
across-segments semantics are not negotiable.

## D4. Identities (loud assertions)

1. Fixed-cap waterbed: no cancellation, MSR net-neutral ⇒ cumulative
   residual emissions = cumulative circulating supply + initial bank −
   terminal bank; ON vs OFF equal to 1e-3 Mt. Adoption shifts who/when,
   never the total.
2. Release-valve accounting: with cancellation/MSR intake active,
   Δ(cum emissions) = −Δ(cum floor_unsold_cancelled + net MSR retention)
   to 1e-3 Mt. The only legal channel for totals to change.
3. Bank non-negativity: unchanged.
4. Irreversibility: τ written at most once; availability monotone in t,
   in outer iteration k, and across event segments.
5. No double-counting: zero share/fixed-cost/abatement pre-adoption;
   base MACs bytewise identical pre/post; capex never in both θ and
   post-adoption fixed_cost.
6. Trigger consistency (D1.1): final-path assertion for non-adopted;
   INFO log with margin for ex-post-below-trigger adopted.

## D5. Validation anchors

CORRECTION to the tasking: lim σ→0 of the D–P multiple is r/y (≈1.83 at
r=.055, y=.03), NOT 1 — the certainty limit retains the pure timing
wedge (paper A.10). NPV break-even dating is trigger_mode="break_even",
a mode, not a limit.

| ID | Anchor | Assertion | Tolerance |
|----|--------|-----------|-----------|
| V1a | Break-even dating, hand-solved 3-yr competitive path | adoption year == hand value | exact |
| V1b | σ=0, r=.055, y=.03 | multiple == r/y == credible_floor_multiple | rtol 1e-12 |
| V1c | σ ∈ {.20,.30,.48} | multiples ≈ {2.86,3.86,6.4} via trigger_multiple (never re-derived) | rtol 5e-3 |
| V2 | 2-period 1-technology worked example (linear MAC, L=0, prices straddle Mθ) | adoption year 2; post-adoption P₂ == hand value; year-1 row bit-identical to OFF | atol 1e-6; year-1 exact |
| V3 | Trigger above path supremum | output == flagged option DELETED (assert_frame_equal exact); AND all 37 goldens bit-identical | exact |
| V4 | Floor F≤F′, credibility q≤q′, σ≥σ′ | adoption weakly earlier under F′/q′/σ′ | weak inequality |
| V5 | Capex in θ and fixed_cost simultaneously | pinned correct total; spec-compliant config books once | atol 1e-6 |
| V6 | D4.1–D4.2, banking, MSR×cancellation on/off | identities hold ON vs OFF | 1e-3 Mt |
| V7 | Event announced after adoption tries to price the tech out | adoption persists; invest_adopted stamped; monotone across segments | exact |
| V8 | N adversarial triggers | converges ≤ N+1 outer iterations, one flip each, tie-break order | exact count |

## D6. Parameters (all defaults inert)

Per flagged technology (`invest_trigger` sub-block; presence IS the flag):
break_even (currency/tCO2, scalar or {year: value}, REQUIRED) ·
payout_yield (1/yr, REQUIRED) · sigma (1/√yr, default 0.0) ·
discount_rate (1/yr, default scenario discount_rate) · credibility
([0,1], default 0.0) · trigger_mode ({dixit_pindyck, break_even},
default dixit_pindyck) · build_lag_years (yr int ≥0, default 0).

Scenario: invest_feedback_enabled (bool, default FALSE — master gate;
flags present with gate off = loud ValueError) · invest_credibility
([0,1], default None — the field policy events raise) ·
invest_max_outer_iters (default N_flagged+1, safety rail only) ·
invest_adopted (mapping, stamped by the carrier; user-settable to
pre-commit adoptions).

Not a parameter by decision: the price signal (delivered path — a toggle
would silently change the equilibrium concept). Capacity comes from the
existing max_activity_share.

Inertness proof obligation (equivalence-verifier gate): with no
invest_trigger blocks and the gate absent, zero solver code paths change;
all 37 goldens bit-identical (V3 second clause).
