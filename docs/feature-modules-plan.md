# Feature-module architecture and migration plan

Authored by lead-modeller (architecture co-lead). Companion docs:
`docs/blocks-composition-rules.md` (F1–F6, R1–R32),
`docs/blocks-graph-plan.md`. Status: pending ets-lead-economist boundary
review, then execution.

Mission: convert `src/ets` from layer-based to feature-based packaging —
one feature per isolated directory, isolation enforced by test, behaviour
preserved bit-exactly against the committed golden baselines
(`uv run pytest`, pinned environment).

## 1. The import contract ("isolated", operationally)

Five tiers, enforced by AST, not convention:

| Tier | Packages | May import |
|---|---|---|
| T0 kernel | `ets/core/` (market primitives, participant model, costs, expectations, ledger, rule protocols, policy defaults, paths, logger) | stdlib, third-party, `ets.core.*` only |
| T1 data boundary | `ets/config_io/` — the only JSON parser | T0 |
| T2 model features | `ets/features/<name>/` | T0 only. Never another feature. Never T1 |
| T3 composition | `ets/engine/` — the only importer of features; solve dispatch, rule wiring, policy-event splicing | T0–T2 |
| T4 workflows | `ets/analysis/*` (isolated leaves), `ets/coupling/`, `ets/blocks/` | T0, T1, T3 — never each other |
| T5 apps | `ets/web/`, `ets/cli.py` | everything below |

Supplementary: (a) underscore names never cross tier boundaries except in
listed compat shims; (b) each feature's `__init__.py` is its entire public
surface; (c) anything two features both need is, by definition, kernel.

### The banking ↔ decree-MSR seam

F4 is about evaluation timing, not code ownership. Decision: **kernel
protocol + engine injection**. `core/rules.py` defines `SupplyRule` and
`CapAdjustmentRule` protocols (observables in → adjustment + diagnostics
out; stateful across years). The msr feature implements them (decree rule,
bank-threshold rule); the banking solver takes `supply_rules` and evaluates
them inside every fixed-point iteration exactly as today; the engine wires
rules from `msr_*` flags. Import isolation ≠ equilibrium isolation — F4
stands; moving rule evaluation outside the fixed point changes solved
numbers and only the golden gate can catch that.

### Features challenged / merged

- market_clearing → kernel (`core/market/clearing.py`): imported by every
  price-formation feature; that is the kernel criterion.
- expectations → kernel: imported by three features and config_io.
- price_controls → NOT a directory: floor logic lives in three
  algorithmically distinct places (static clearing, banking supply rule,
  transmission blend-then-clip/F3); extraction would force forbidden arrows
  and tempt the reordering F3 forbids. It stays a catalogue block.
- cancellation → NOT a directory: parameters of the mechanisms that own it.
- oba/cbam/sectors → kernel overlays, explicitly not isolatable: OBA is
  inside the participant demand function; CBAM is post-clearing kernel
  reporting (F6); sectors are attributes + aggregation + normalization.
  Declared, not faked.
- policy_events → engine module: splicing re-invokes full dispatch — that
  IS composition.
- feedback_coupling/calibration/batch → workflows (T4), they drive the
  engine from above. narrative/csv_import/investment_trigger: already
  isolated leaves (zero ets imports).
- blocks stays T4 and engine-blind (imports config_io only) — its contract
  is the config schema; it survives any solver refactor.

## 2. Target tree

```
src/ets/
├── __init__.py                    # unchanged public surface
├── core/                          # T0
│   ├── paths.py                   # ← ets/config.py (incl. MPLCONFIGDIR side effect)
│   ├── defaults.py                # ← MSR_DEFAULTS, CCR_DEFAULTS, BANKING_DEFAULTS
│   ├── logger.py                  # NEW (CLAUDE.md mandate)
│   ├── costs.py                   # ← ets/costs.py
│   ├── expectations.py            # ← solvers/expectations.py
│   ├── rules.py                   # NEW: SupplyRule, CapAdjustmentRule protocols
│   ├── ledger.py                  # ← simulation.py:_simulate_path_details (→ simulate_path_details),
│   │                              #   _collect_path_results, _market_year_sort_key
│   ├── market/                    # ← market/ (core.py→model.py, equilibrium.py→clearing.py,
│   │                              #   results.py→reporting.py; __init__ verbatim)
│   └── participant/               # ← participant/ (verbatim)
├── config_io/                     # T1, stays; imports rewritten to core
├── features/                      # T2 — mutually isolated
│   ├── competitive/solver.py      # ← solve_scenario_path, _simulate_realized_prices (+cap_rules)
│   ├── banking/{window,solver}.py # ← banking.py split; rule-injected; floor-cancellation stays here
│   ├── hotelling/solver.py        # ← hotelling.py (cap_rules replaces MSRState import)
│   ├── nash_cournot/solver.py     # ← nash.py (injected duck-typed msr state; F2 preserved bit-for-bit)
│   ├── transmission/solver.py     # ← transmission.py (component solvers injected; F3 stays internal)
│   ├── msr/{state,decree,rules}.py# ← msr.py + banking's _decree_msr_action + threshold rule +
│   │                              #   MSRCapRule (lifted from simulation.py per-year pipeline)
│   └── ccr/{state,rules}.py       # ← ccr.py + CCRCapRule (lifted from simulation.py)
├── engine/                        # T3 — sole importer of features
│   ├── dispatch.py                # ← run_simulation, _rename_markets, run_simulation_from_config/file
│   ├── wiring.py                  # NEW: default_cap_rules/default_supply_rules per approach —
│   │                              #   reproduces F2's inconsistencies EXACTLY (documented, not fixed)
│   └── events.py                  # ← solvers/events.py
├── analysis/, coupling/, blocks/  # T4 (blocks unchanged; batch/calibration/loop → engine)
├── web/, cli.py                   # T5 (import lines only; payloads byte-identical)
└── shims (DeprecationWarning, retire 0.3.0): solvers/*, market/*,
    participant/*, config.py, costs.py, and the existing flat shims.
    DELETE dead flat market.py, participant.py (shadowed by packages).
```

Tests mirror: `tests/{core,features/*,engine,workflows,apps}/` — moves only.

## 3. Isolation enforcement — tests/test_module_isolation.py

AST-walk all of `src/ets` (function-level imports count), resolve relative
imports, classify by tier, assert edge-by-edge: (a) no feature→feature;
(b) features import only core+stdlib/3rd-party (never config_io);
(c) features imported only from engine (and shims); (d) core imports only
core; (e) config_io imports only core; (f) engine imports nothing from
T4/T5; (g) analysis leaves don't import each other, blocks imports only
config_io+itself, coupling only {core,config_io,engine,itself}; (h) no
underscore name crosses a tier boundary except from listed shims.
`PENDING_VIOLATIONS` allowlist maps existing bad edges → the work order
that removes them; the test fails on new edges AND on stale allowlist
entries (ratchet). Final order: empty.

## 4. Work orders (gates: G1 = `uv run pytest -q -m "not slow"`; G2 = full)

- **O0** ratchet test in place, allowlist seeded from today's graph. G1.
- **O1** kernel scaffold: core/{paths,defaults,rules,logger}.py;
  templates.py → core.defaults (kills config_io→solvers #1); config.py
  becomes shim; DELETE dead flat market.py/participant.py. Risk:
  MPLCONFIGDIR side-effect ordering on Vercel. G1 + web tests.
- **O2** costs.py + participant/ → core/. Shim package. G1.
- **O3** market/ → core/market/. Shim package incl. per-module shims. G1 +
  banking + appendix B tests.
- **O4** expectations → core (kills config_io→solvers #2). G1.
- **O5** REFACTOR-NO-MOVE: cap-rule injection in the per-year pipeline
  (MSRCapRule, CCRCapRule lifted verbatim; application order CCR then MSR
  per F1; diagnostics keys identical). **G2 checkpoint** + composition tests.
- **O6** REFACTOR-NO-MOVE: supply-rule injection in the banking fixed point
  (DecreeSupplyRule, ThresholdMSRSupplyRule; floor-cancellation stays
  banking-owned; fixed-point loop untouched). **G2** + K-MSR gates.
- **O7** ledger → kernel (underscore names re-exported via shims). G1.
- **O8** engine/ + features/msr + features/ccr; dispatch/events/wiring;
  rewrite analysis/coupling/web/cli/__init__. **G2 checkpoint**.
- **O9** features/banking (window.py + solver.py; engine-bound shim). G1 +
  appendix B.
- **O10** features/competitive. G1 + web tests.
- **O11** features/hotelling + features/nash_cournot (F2 preserved
  bit-for-bit, documented as intentionally inconsistent). G1 + goldens -k.
- **O12** features/transmission (F3 invariant never split). G1 +
  transmission + lambda_regimes golden.
- **O13** app-tier import tidy + DeprecationWarnings on all new shims
  (milestone 0.3.0); record underscore-leakage retirement list. G1.
- **O14** tests mirror + flip the ratchet (empty allowlist). **G2 final** +
  isolation test + ruff + Vercel import smoke.

## 5. Risks (declared)

- Economically impossible isolations are declared, not faked (F3/F4/F6).
  Import isolation cannot detect moving decree evaluation outside the
  fixed point — only the golden gate can; both are permanent.
- Cycles: engine.dispatch ↔ engine.events stays lazy (as today);
  participant models ↔ compliance laziness moved intact.
- No pickle anywhere; the real serialization risk is DataFrame column
  order vs bit-exact baselines — statement order preserved verbatim.
- Vercel: api/index.py path unchanged; vercel.json includeFiles covers new
  dirs; requirements.txt is Vercel's install manifest — KEEP (annotate as
  deploy-only).
- Frontend contract untouched; web tests gate every T5-adjacent order.
- F2 (nash/hotelling MSR-CCR inconsistencies) becomes visible in
  engine/wiring.py — fixing it is a math change requiring economist
  sign-off + new baselines; out of scope for every order above.

---

# PLAN v2 — rewrites authorized (supersedes conflicting v1 sections)

Owner directive: "every market mechanism can be rewritten to be modular."
Economist v1 verdicts folded in (rule purity via factories/reset, observable
spec, CCR split gating, transmission rule wiring, splice pins).

## Two-door features

Each feature has (a) `plugin.py` — config-facing door: field specs,
build-time transforms, attachable behaviour objects (reporters, overlays,
carriers); imports core+stdlib only; (b) runtime modules (solver/rules/state)
— import core + same-feature siblings; imported only by engine. config_io
may import `features.<X>.plugin` ONLY, composed via reviewed source literals
(`_PARTICIPANT_TRANSFORMS`, reporter stage literals) — never registry
mutation. blocks/ stays config_io-only (Vercel graph path loads no solver).

## Protocol family (core/protocols.py)

DemandOverlay (elastic baseline, inside compliance at today's call site) ·
ParticipantTransform (sectors, OBA — builder pipeline literal in today's
order) · CapRule pre_clear/post_clear with split gating (CCR record has NO
start-year gate — economics) · SupplyRule + frozen Observables dataclass
(threshold/decree MSR, floor-cancellation; inside the banking fixed point,
F4; rules constructed/reset per schedule evaluation — pure across
iterations, factories wired by engine) · PriceOverlay (delivered floor,
clip-last) · Friction (hoarding inflow; window-start math stays host) ·
ParticipantReporter/SummaryReporter staged literals (CBAM, sectors, MSR/CCR
placeholders — column order pinned by a fast regression test) ·
SpliceCarrier (bank + decree reserve across event segments, same
msr_ran_last_segment condition).

## Feature verdicts v2

REAL MODULES: oba (build-time transform, builder.py:412-424 — plugin-only),
elastic_baseline (models.py:193-197 formula → overlay; kernel guard raises
loud if ε>0 without overlay — the one deliberate API change),
cbam (reporters only; F6 becomes a mechanically gated invariant),
sectors (transform + summary reporter), hoarding (fields + Friction;
window-start constraint a > max{t: h_t>0} stays banking host),
price_controls (trajectory plugin + FloorCancellationRule + DeliveredFloor;
REMAINDER: the in-clearing floor branch equilibrium.py:104-181 stays kernel
— with floor=0 it is the oversupply boundary condition P=0, sold=e(0);
without it clearing cannot bracket; host guarantee documented + property
test). NO cancellation/ directory: the cancel clause is a joint predicate
with the floor (price_controls), msr_cancel_excess is MSR's, carry-forward
is the kernel conservation identity S_{t+1} += U_t.

## Work orders v2

O0–O6 as v1 (rules.py → protocols.py, full family, protocols only; O5/O6
carry the economist's factory/reset lifecycle + observable spec + split
gating + regression tests: ccr_start_year>first, expectations-inner-loop
rule-free, λ+MSR before transmission, splice pins before ledger move).
NEW: O7 reporting host + cbam + sectors reporters (column-order test, G2
checkpoint) · O8 demand-overlay hook + elastic_baseline (gate incl.
feedback_a golden + dashboard payload) · O9 builder host pipeline + oba +
sectors transforms (gate incl. oba/subsector goldens) · O10 price_controls
+ hoarding (G2; MSR-then-floor order preserved in wiring literal;
DeliveredFloor attach-always is exact since max(p,0)=p for p≥0).
O11–O19 = v1 O7–O14 renumbered (ledger→kernel, engine+msr/ccr features,
banking/competitive/hotelling+nash/transmission moves, tidy+shims, tests
mirror + ratchet flip now also arming the F6 mechanical check and
literal-pinning tests). G2 checkpoints: after O7, O10, engine order, final.

## Risks v2 delta

Out-of-repo direct constructors get base columns + loud elastic-baseline
error (documented; in-repo provably unchanged). config_io→plugin widening
contained by door-granular isolation test. All v1 risks carried (F4
honesty, F2 freeze, requirements.txt is Vercel's manifest, frontend payload
frozen).

---

# Arbitration outcomes (binding, economist design gate on v2)

Overall: PROCEED WITH CHANGES for O7-O10; O0-O6 verdicts stand.

- **O8 (blocking design fix)**: reference_carbon_price is SCENARIO-level,
  stamped onto participants post-construction (builder.py:443-448) — the
  elastic_baseline plugin OWNS that stamping step and attaches the overlay
  at stamp time per participant (ε>0); the loud guard is enforced at every
  P_ref assignment (checked setter or revalidation after stamp), not
  __post_init__ only.
- **O7**: cbam summary stage literal includes results.py:234-245
  (per-jurisdiction totals, EUA-ensemble totals with the order-sensitive
  `col not in summary` dedup, Scope-2 totals) after the revenue tracker;
  SummaryReporter signature takes the ACCUMULATING summary dict (stages
  are not independent); reporters attach-always (unconfigured scenarios
  keep zero-valued columns); Year placement is per-host (summary mid-dict
  after CCR placeholders, participant record tail).
- **O9 literal-pin additions**: OBA must stay after the trajectory patch
  (reads patched initial_emissions, builder.py:419) and its overwrite of
  the sectors-written free_allocation_ratio (389 vs 422) is a pinned
  cross-feature coupling through the raw-dict medium; transforms declare
  read/write fields.
- **O10**: hoarding host set extends to banking.py:247 (static-year
  supply reduction S_t − h_t) and :278-282 (no-arbitrage prune exemption —
  the documented λ≈0 violation); the Friction protocol docstring pins
  those semantics as the contract (exogenous withdrawal, forced static
  regime, inflow accrues to window budget) rather than implying
  generality; the price_controls remainder property test (floor=0
  oversupply boundary bracketing) is PERMANENT, alongside the F4 golden.
- **Item-1/3/4/5/6 verdicts**: OBA build-time reading CORRECT; loud-guard
  API change ENDORSED; reporter staging CORRECT under the four conditions;
  price_controls three-way split CORRECT (the in-clearing branch is the
  complementary-slackness boundary of static clearing — equilibrium
  concept, not policy instrument); hoarding split CORRECT with the
  extended host set; two-door contract CLEAN given door-granular isolation
  testing and declared-fields discipline.
