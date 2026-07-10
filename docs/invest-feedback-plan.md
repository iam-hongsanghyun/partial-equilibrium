# Phase 1 architecture: endogenous investment ↔ price feedback

Authored by lead-modeller; binding economic spec: `docs/invest-feedback-spec.md`
(ets-lead-economist). ARBITRATION NOTE (coordinator): where this plan and the
spec differed, the spec governs — the outer loop has NO price relaxation and
NO price tolerance; termination is combinatorial (monotone adoption + at most
ONE flip per iteration, deterministic tie-break: earliest crossing year →
largest relative exceedance → declared config order → ≤ N_flagged + 1
iterations). `investment_relaxation` and `investment_tolerance` are dropped
from the schema; `investment_max_iterations` remains as a safety rail
(default N_flagged + 1, exhaustion = WARNING + last iterate).

## Architecture decisions

- **D1** Dixit–Pindyck math moves VERBATIM `analysis/investment_trigger.py`
  → `core/investment.py` (T0; features may import core only); analysis
  module becomes a permanent re-export facade.
- **D2** The outer loop lives in `engine/feedback.py` — self-coupling
  sibling of `coupling/loop.py`; wraps ANY approach's full path solve via a
  dispatch-extracted per-approach solver closure; dispatch gains exactly one
  lazily-importing guarded branch (`_investment_configured(m0)`).
- **D3** Adoption diagnostics are path-solver diagnostics patched in
  `core/ledger.py:collect_path_results` under key-presence guards (the
  banking-columns precedent) — NEVER in the `_SUMMARY_REPORTERS_*` literals.
  Rationale: `test_golden_baselines._walk_diff` walks key unions, so any new
  always-on column fails all 40 goldens; the operative invariant (column set
  = deterministic function of config) survives. New columns (tail):
  "Investment Adoptions" (sorted JSON), "Investment Newly Effective",
  "Investment Feedback Iterations", "Investment Converged". Participant
  frame gains NO columns in v1. `tests/core/test_reporting_columns.py`
  gains a fourth pinned scenario.
- **D4** Catalogue: new category `"feedback"`, block `endogenous_investment`
  reusing the policy out-port kind (no market-port surgery);
  `technology_option` gains an `investment_trigger` dict ParamSpec; the
  requires-competitive-or-banking constraint becomes validator rule R33 +
  MCP suggestion (requires= is conjunctive-only).

## Kernel contracts (core/protocols.py)

`AdoptionSpec` (frozen kw-only: participant_name, technology_name, sigma
[1/√yr], payout_yield [1/yr] REQUIRED, credibility [0,1], build_lag_years
int≥0, trigger_mode {dixit_pindyck, break_even}, trigger_multiple_override
≥1 | None, break_even scalar|{year: value} REQUIRED) · `AdoptionEvent`
(participant, technology, adoption_year) · `AdoptionState` = sorted tuple of
events (value equality = convergence test; deterministic serialization) ·
`PathFeedback` protocol: propose(price_path, state, markets) →
(state', metrics); apply(ordered_markets, state) → vintaged markets; wired
as factories, fresh per outer iteration; the host-owned AdoptionState is the
only cross-iteration state. `MarketParticipant.adoption_specs: tuple = ()`
(demand_overlays pattern; TechnologyOption unchanged — specs reference by
name).

## Feature module

```
features/endogenous_investment/
  plugin.py    normalize_investment_trigger (config validation),
               attach_adoption_specs (the ONLY sanctioned writer; loud
               guard: flag true + zero specs = ValueError; specs + flag
               false = ValueError per spec D3.2),
               ADOPTION_CARRIER (SpliceCarrier: column "Investment
               Adoptions" → field investment_initial_adoptions,
               carry_if = feature ran; adoptions are FLOORS on later
               segments — a late announcement cannot un-adopt)
  rule.py      InvestmentRule (PathFeedback): trigger evaluation on the
               DELIVERED price path via core.investment (single source of
               math — never re-derived); P* = M·θ(t); σ_eff=(1−q)σ;
               one-flip selection with the spec's tie-break
  vintage.py   apply_adoption_state: per-year availability gating —
               flagged options REMOVED from the reversible choice set
               until τ+lag, enter at max_activity_share thereafter
               (utilization stays reversible — capex irreversible,
               dispatch reversible); NEVER mutates MAC blocks or
               initial_emissions; empty specs+state returns the same
               list object (identity-tested)
```

## Outer loop (engine/feedback.py) — spec D1 form

```
state_0 = carried adoptions (splice/config); k = 0
loop:
  markets_k = rule.apply(base_markets, state_k)      # vintaging + masking
  path_k    = path_solver(markets_k)                 # FULL untouched solve
  P_k       = delivered price path
  proposal  = fresh_rule().propose(P_k, state_k, markets_k)
  host enforces: proposal ⊇ state_k, never-later re-dating, ≤1 new flip
  if proposal == state_k: converged (final = path_k)  # combinatorial
  state_{k+1} = proposal
ex-post checks: no non-adopted flagged pair crosses its trigger on the
final path (assertion); adopted-below-trigger logged INFO with margin.
```

Strictly outside the expectations inner loop (R29 verbatim) and outside
solve_banking_path (spec D1.3 — each iteration re-runs the full banking
solve including window search). Events: ADOPTION_CARRIER appended LAST to
SPLICE_CARRIERS (bank, reserve, adoptions); carried adoptions monotone
across segments. v1 approach coverage: competitive + banking; other
approaches + feature = loud ValueError at normalize (R33 mirrors).

## Config schema (all defaults inert)

Scenario: investment_feedback_enabled (false) ·
investment_max_iterations (default N_flagged+1, safety rail) ·
investment_initial_adoptions ([]; carrier landing field, user-settable to
pre-commit). Technology option: optional `investment_trigger` sub-dict
{break_even_price | break_even_prices REQUIRED, payout_yield REQUIRED,
sigma 0.0, credibility 0.0, discount_rate → scenario default, trigger_mode
dixit_pindyck, build_lag_years 0}. Scenario invest_credibility override —
the field policy events raise via changes={} (existing mechanism).

## Off-by-default proof chain (each link tested)

no flags → normalize adds default keys only → builder attach flag-gated →
adoption_specs == () everywhere → dispatch guard False → feedback module
never imported (lazy-activation test) → no investment_* detail keys → no
new summary columns → carrier no-op → decompile emits nothing. Merge
blocker: ALL committed goldens bit-identical + reporting-column pins +
ratchet empty + Appendix B + dedicated neutrality test (params present,
flag false ≡ params stripped, frame-equal).

## Work orders

EI-1 (policy-mechanism-modeller): math → core/investment.py verbatim;
facade. EI-2 (developer): dispatch pure refactor — per-approach solver
closures; G2 full-golden gate. EI-3 (policy-mechanism-modeller): kernel
contracts + adoption_specs field. EI-4 (policy-mechanism-modeller):
feature runtime + anchors V1a-c + masking/identity tests. EI-5
(banking-equilibrium-modeller): engine/feedback.py + dispatch guard +
ledger patch + events carrier + lazy-activation extension + termination
tests (V8) — merge-blocking bit-identity gate. EI-6 (developer): config
door, catalogue/decompile/manifest/R33/MCP. EI-7 (both modellers):
economist anchors V2-V7 as tests + two goldens
(investment_competitive_transition; k_msr_decree_induces_investment —
small horizon, the decree-lowers-σ_eff-accelerates-adoption narrative vs
its P0 twin) + fourth column pin. EI-8 (developer): frontend feature
module + adoption timeline panel + registry line. EI-9 (developer): docs.
Sequence: 1 → 2 → 3 → 4 → 5 → {6,7} → 8 → 9. Gates per order as listed;
equivalence-verifier runs every G2; reproduction-verifier signs EI-7;
ets-lead-economist final sign-off closes the phase.
