# Block-graph composition rules (economic validation spec)

Authored by ets-lead-economist (validation lead, modularization programme).
This is the spec for `src/ets/blocks/validate.py`. Every rule is grounded in
the engine as of the baseline SHA; file:line references are to that state.

## 0. Engine findings the validator must know about

**F1 — INCORRECT: MSR overwrites the CCR cap adjustment when both are enabled
(competitive path).** `src/ets/solvers/simulation.py:116` initialises
`effective_carry = carry_forward_allowances`; `:146` adds the CCR adjustment
(`effective_carry += ccr_adjustment`); but `:173` then reassigns
`effective_carry = carry_forward_allowances + msr_net`, silently discarding
`ccr_adjustment` whenever the MSR is active in the same year. Correct
equation: `effective_carry = carry_forward_allowances + ccr_adjustment +
(msr_released − msr_withheld)`, i.e. `Q_t = Q̄ + ΔQ_t^CCR + ΔQ_t^MSR`.
**Status: FIXED** (Order 1b, `effective_carry += msr_net`; regression tests in
`tests/test_msr_ccr_composition.py`; golden baselines unaffected — no example
enables both rules). R10 downgraded accordingly.

**F2 — INCORRECT (inconsistency): Nash path ignores `msr_start_year` and the
CCR entirely.** Competitive gates the MSR on `msr_start_year`
(`simulation.py:148-155`); Nash applies the MSR unconditionally when enabled
(`nash.py:289-303`) and never constructs a `CCRState`. Hotelling applies
neither (result rows hardcode `msr_* = 0.0`, `hotelling.py:123-125`). Silent
no-ops → R8, R9, R16.

**F3 — CORRECT (documented, load-bearing): blend-then-clip in the λ overlay.**
`transmission.py:246-263` solves both components floor-stripped
(`_strip_floors`, `:98-109`) and applies `max(blend, floor)` last — the
paper's transmission-immunity property; a drawn graph must never reorder it
(docstring `:43-56`; `docs/forward-transmission.md:27-42`).

**F4 — CORRECT (documented): supply rules and the state they read live on the
same side of the banking solver boundary.** `banking.py:622-650` iterates
window-solve ↔ supply-schedule to a fixed point; rules read only
beginning-of-year state (`banking.py:86-87`, `:492`, `:516`). Any GUI
decomposition that moves the MSR outside this fixed point computes a
different equilibrium.

**F5 — AMBIGUOUS: participant-level banking under `model_approach:
"banking"`.** The aggregate bank is the solver's state variable, yet
`banking.py:660-667` re-runs participants at delivered prices with per-year
`banking_allowed` honoured (`compliance.py:87`), so participant frames can
show a second, uncoordinated bank on top of the solver's aggregate bank.
Until resolved: WARNING (R17).

**F6 — CORRECT: CBAM is a post-clearing reporting overlay, not a price
channel.** CBAM liability is computed only in `market/results.py:28-90`;
`participant/compliance.py` has no CBAM term. The GUI must render CBAM as a
diagnostics block downstream of price formation, never as an input to it.

## 1. Required / exclusive matrix

Price-formation blocks are mutually exclusive by construction: one
`model_approach` per scenario, dispatched at `simulation.py:299` / `:337-370`;
allowed set `{competitive, hotelling, banking, nash_cournot, all}`
(`normalize.py:27`). `all` is a comparison harness (`simulation.py:355-365`),
exposed as a compare button, not a block.

| Block | REQUIRES | EXCLUDES / silently ignored under | Silent interactions |
|---|---|---|---|
| Participants | ≥1 participant (`core.py:28-29`); piecewise ⇒ non-empty ordered `mac_blocks` (`normalize.py:285-289`); penalty ≥ floor (`normalize.py:134-142`) | — | OBA and sector allocation both rewrite `free_allocation_ratio`; precedence OBA > sector > per-year (`builder.py:357-424`) |
| Market mechanism (year) | `price_upper_bound > price_lower_bound` (`normalize.py:93-97`); free+auction+reserved+cancelled ≤ cap (`builder.py:494-503`) | — | no `price_upper_bound` ⇒ ceiling = max penalty × multiplier (`equilibrium.py:115-122`); penalty 0 + no ceiling breaks the bracket |
| Competitive clearing | valid market | — | floor and `minimum_bid_coverage` inside the clearing (`equilibrium.py:124, 151-170`); `unsold_treatment: carry_forward` feeds next year (`simulation.py:209-213`) |
| Banking (Rubin/Schennach) | `discount_rate + risk_premium ≥ 0` (`banking.py:577-581`) | ignores per-year `expectation_rule` (`banking.py:661`); ignores `unsold_treatment: carry_forward` (`banking.py:115-117`); ceiling not enforced in-window (`banking.py:319-334`); borrowing contradicts B_t ≥ 0 | `hoarding_inflow` forces window start after last hoarding year (`banking.py:259-267`); `strict_no_arbitrage=False` is the documented λ≈0 violation (`banking.py:61-72`) |
| Hotelling | positive cumulative budget: `carbon_budget` per year, fallback Σ`total_cap` with warning (`hotelling.py:187-199, 213-218`); both zero ⇒ silent competitive fallback (`:251-257`) | MSR, CCR, floor, λ overlay all ignored; price clamped only to bounds (`hotelling.py:93-95`) — binding clamp silently breaks budget exhaustion | banks propagate at pinned prices (`hotelling.py:84-131`) |
| Nash–Cournot | strategic names ∩ participant names ≠ ∅, else silent competitive (`nash.py:107-109`); empty list ⇒ all strategic (`nash.py:265-266`) | CCR ignored; `msr_start_year` ignored (F2) | same expectations block as competitive (`nash.py:268-272`) |
| λ forward-transmission | `model_approach = competitive` (`simulation.py:320-334`); λ ∈ [0,1] | any other approach (engine warns and drops) | MSR/CCR live inside the competitive component only (`transmission.py:60-61`) |
| Expectations rule | consumed only by competitive (`simulation.py:44-70`) and Nash (`nash.py:268-272`) | decorative under banking / hotelling / λ-overlay | `perfect_foresight` fixed point excludes MSR/CCR (`simulation.py:52-70, 83-90`), documented (`docs/algorithm-overview.md:291, 574`) |
| MSR `bank_threshold` | a bank state: competitive/Nash ⇒ Σ participant banks (`simulation.py:157`) needing ≥1 year `banking_allowed: true` AND non-myopic expectations (`compliance.py:87`); banking ⇒ aggregate solver bank (`banking.py:515-531`) | hotelling (F2) | enters `effective_carry` before clearing (`simulation.py:170-173`); only `msr_cancel_excess` defeats the waterbed (`msr.py:83-89`) |
| MSR decree (`price_band`/`surplus_rule`/`hybrid`) | `model_approach = banking` — only `banking.py:479-514` reads `msr_mode` | competitive, hotelling, nash (silently degrade to bank_threshold) | signals read previous-year price/surplus (`banking.py:398-400, 412-413`); `msr_initial_reserve_mt` funds releases only here (`banking.py:480`) |
| CCR | `model_approach = competitive` (`simulation.py:122-146`); ≥1 reference > 0 else inert (`ccr.py:135-145`) | banking, hotelling, nash | lagged signal e_{t−1}, z_{t−1} (`ccr.py:61-70`); recorded post-clearing (`simulation.py:202-207`); φ units are cap-scale (`ccr.py:48-53`) |
| Price floor | per-year `auction_reserve_price` or `price_floor_trajectory` (`builder.py:459-464`) | hotelling: not enforced | competitive: inside clearing with unsold volume (`equilibrium.py:151-170`); banking: cancel-rule inside fixed point (`banking.py:533-538`) + delivered clip last (`:653-656`); λ-overlay: clip after blend (F3) |
| Price ceiling | — | banking: warning only (`banking.py:319-334`) | competitive: it is the Brent bracket top — binding ceiling ⇒ infeasible, not clipped |
| Cancellation | one of: year `cancelled_allowances` (`builder.py:452, 496`); `unsold_treatment: "cancel"` (needs a floor to bind); `msr_cancel_excess` (needs MSR) | — | only cancellation defeats the waterbed under banking |
| OBA | `production_output > 0` AND `benchmark_emission_intensity > 0` AND `initial_emissions > 0` together (`builder.py:417-423`) | — | overrides sector-derived and manual ratios; capped at 100% |
| Sectors | every non-empty `sector_group` names a defined sector (`builder.py:140-148`) | — | sector-derived cap/auction override trajectories (`builder.py:468-474`) |
| CBAM | a reference price: `eua_price` / `eua_prices` / jurisdiction `reference_price` (`results.py:46-58`) | — | reporting only (F6) |
| Policy events | `announced` ∈ scenario years (`events.py:92-96`) | — | carries bank + decree reserve across splices (`events.py:142-143, 171-196`); bank_threshold pool resets per segment (`docs/banking-equilibrium.md:117-120`) |
| Hoarding | `model_approach = banking` (`banking.py:130-141, 245-267`) | others: decorative | usually needs `banking_strict_no_arbitrage: false` |

## 2. Ordering semantics

Fixed by the implementation (GUI renders read-only):

1. Competitive per-year pipeline: CCR cap adjustment (`simulation.py:122-146`)
   → MSR supply adjustment (`:148-173`) → clearing with floor inside
   (`:175-179`) → CCR records realised aggregates (`:202-207`) → unsold
   disposition / bank carry (`:209-217`). Rules read beginning-of-year state.
2. Expectations fixed point excludes MSR/CCR (`simulation.py:83-90`) —
   documented equilibrium choice.
3. Banking: supply rules (MSR then floor-cancellation, `banking.py:459-465`)
   inside the schedule fixed point (`:622-650`); reserve-floor clip on
   delivered prices last (`:653-656`).
4. λ overlay: strip floors → solve components → blend → clip (F3).
5. Hotelling: bound-clamp inside λ-bisection (`hotelling.py:93-95`), budget
   bisection outermost.
6. Policy events: apply announced changes → re-solve remaining horizon → keep
   segment → carry state (`events.py:150-197`), chronological (`events.py:113`).

**Edge semantics: an edge is a state dependency the engine actually has.**
Edges are typed port connections compiling 1:1 to a config field or state
read. Edges between two policy blocks are forbidden — their order is
engine-fixed; a decorative edge must be rejected at compile time. Diagnostics
blocks (CBAM, investment trigger) accept the solved price path and emit no
edges back into the solve.

## 3. Defaults and minimum viable graph

Minimum viable graph: Participants (≥1) → Market mechanism (≥1 year) →
Competitive clearing. Defaults for a fresh drag-out:

- Participant: `initial_emissions > 0` (e.g. 100), `abatement_type: linear`
  with `max_abatement > 0`, `cost_slope > 0`, `penalty_price >
  price_lower_bound`, `free_allocation_ratio ∈ [0,1]`.
- Market year: `total_cap` ≥ free+auction; `price_upper_bound: 100 >
  price_lower_bound: 0`; `unsold_treatment: "reserve"`; `banking_allowed:
  false`.
- Price formation: competitive; `discount_rate 0.04`, `risk_premium 0.0`.
- MSR: `MSR_DEFAULTS` (`msr.py:98-106`) + `msr_mode: bank_threshold`; dropping
  the block auto-requires a bank source (R6).
- CCR: `CCR_DEFAULTS` (`ccr.py:177-183`) are deliberately inert — force the
  user to set references before run (R11); never pre-fill paper values (units
  mismatch, `ccr.py:48-53`).
- Hotelling: require `carbon_budget` at drop time (R14).

## 4. Validator rule list (spec for `src/ets/blocks/validate.py`)

ERROR = refuse to run; WARNING = run with notice.

Graph shape:
- **R1 ERROR** — exactly one price-formation block per market (`simulation.py:299`).
- **R2 ERROR** — ≥1 participant with `initial_emissions > 0` and ≥1 market year (`core.py:28-29`).
- **R3 ERROR** — every edge must compile to a config field or engine state read; decorative edges rejected.
- **R4 ERROR** — no user-drawn edges between policy blocks; order is engine-fixed (`simulation.py:122-179`; `banking.py:459-465`).

Policy ↔ price-formation compatibility:
- **R5 ERROR** — MSR decree modes require the banking block (`banking.py:479-514`).
- **R6 ERROR** — MSR under competitive/Nash requires ≥1 year `banking_allowed: true` AND ≥1 non-myopic expectation rule (`compliance.py:87-90`, `simulation.py:72`).
- **R7 ERROR** — `msr_initial_reserve_mt > 0` requires a decree mode (`simulation.py:72` constructs zero-reserve MSRState on competitive).
- **R8 ERROR** — MSR + Hotelling cannot coexist (`hotelling.py:123-125`; waterbed-neutral under a fixed budget anyway).
- **R9 ERROR** — CCR requires competitive (`simulation.py:122-146` is the only code path).
- **R10 — RESOLVED, now allowed** — MSR and CCR both enabled on one competitive scenario. F1 was fixed (Order 1b): `effective_carry` now composes additively (`+= msr_net`), so `Q_t = Q̄ + ΔQ_t^CCR + ΔQ_t^MSR`; regression coverage in `tests/test_msr_ccr_composition.py`. The validator treats this combination as valid.
- **R11 ERROR** — CCR enabled with both references = 0 (`ccr.py:135-145`).
- **R12 WARNING** — CCR φ signs opposite the paper's optimum (φ_e > 0 or φ_z < 0, `ccr.py:55-59`).
- **R13 ERROR** — λ overlay requires competitive (`simulation.py:320-334`).
- **R14 ERROR** — Hotelling requires Σ`carbon_budget` > 0 or Σ`total_cap` > 0; WARNING when only the fallback is available (`hotelling.py:187-199, 251-257`).
- **R15 ERROR** — declared `nash_strategic_participants` must be a non-empty subset of participant names (`nash.py:107-109`).
- **R16 WARNING** — Nash + MSR with `msr_start_year` set: ignored in the Nash path (`nash.py:289-303`).

Banking-specific:
- **R17 WARNING** — banking approach + any year `banking_allowed: true` (F5 double-bank ambiguity).
- **R18 ERROR** — banking approach + `borrowing_allowed: true` (`banking.py:25-26, 303`; Rubin no-borrowing).
- **R19 ERROR** — `hoarding_inflow > 0` requires the banking block (`banking.py:130-141`).
- **R20 WARNING** — hoarding/supply-perturbing policy under `banking_strict_no_arbitrage: true`: likely static fallback (`banking.py:364-370`); suggest relaxed mode explicitly (`banking.py:61-72`).
- **R21 WARNING** — price ceiling + banking: advisory in-window (`banking.py:319-334`).
- **R22 WARNING** — `unsold_treatment: "carry_forward"` under banking/hotelling/λ-overlay: only competitive and Nash implement the carry (`simulation.py:209-213`; `nash.py:328-332`).
- **R23 ERROR** — `discount_rate + risk_premium < 0` with banking (`banking.py:577-581`).

Market mechanism / floors / ceilings:
- **R24 ERROR** — `auction_reserve_price > price_upper_bound` in any year (`equilibrium.py:124`; empty feasible set).
- **R25 ERROR** — no price ceiling and max `penalty_price = 0` in a year with `auction_offered > 0` (`equilibrium.py:115-122`; unbounded bracket).
- **R26 ERROR** — cap consistency and Σ`sector_allocation_share` ≤ 1 per sector (`builder.py:494-503`).
- **R27 WARNING** — `unsold_treatment: "cancel"` with no floor: confirm intent (paper's Rule A is floor-driven).

Expectations / timing / diagnostics:
- **R28 WARNING** — expectations block attached to banking/hotelling/λ-overlay: not consumed (`banking.py:661`; `hotelling.py:98`; `transmission.py:152-153`).
- **R29 WARNING (informational)** — `perfect_foresight` + MSR/CCR: expectations formed on the rule-free path (`simulation.py:83-90`); anticipated-policy pricing requires the banking block.
- **R30 ERROR** — policy event `announced` must be a scenario year (`events.py:92-96`); WARNING when a splice crosses a bank_threshold MSR (`docs/banking-equilibrium.md:117-120`).
- **R31 WARNING** — CBAM with all reference prices = 0 (`results.py:46-58`); GUI-level: no edge from CBAM into price formation (F6).
- **R32 WARNING** — OBA fields half-set (`builder.py:417-423`): override never fires.
- **R33 ERROR** — `endogenous_investment` requires competitive_clearing or rubin_schennach_banking price formation; v1 approach coverage is competitive + banking only (`docs/invest-feedback-spec.md` D1.3; `docs/invest-feedback-plan.md` "v1 approach coverage" — other approaches + the feature raise a loud `ValueError` at normalize).
