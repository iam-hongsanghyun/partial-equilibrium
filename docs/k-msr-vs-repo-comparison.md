# K-MSR paper vs. this repository — divergence & depth comparison

Source papers (all three verified against the actual texts):

1. **K-MSR paper** — PLANiT, *"Leading Carbon Prices to an Irreversible
   Industrial Transition: Instrument Choice for a Market Stability Reserve
   under Weak Forward Transmission"* (working paper, July 2026). Calibrated to
   the "K-ETS partial-equilibrium model v1.0 (MAC + banking/Hotelling price
   rule)" — i.e. the engine in this repository. Its Appendix B is a numerical
   verification table; every paper-side number below is taken from it.
2. **Kollenberg & Taschini (2019)**, *"Dynamic supply adjustment and banking
   under uncertainty in an emission trading scheme: The market stability
   reserve"*, European Economic Review 118, 213–226 — the theory behind this
   repo's MSR module (`src/ets/solvers/msr.py`). Section 5 below.
3. **Benmir, Roman & Taschini (2025)**, *"Weitzman meets Taylor: EU allowance
   price drivers and carbon cap rules"*, Grantham Research Institute WP 421 —
   the source of this repo's Carbon Cap Rule (`src/ets/solvers/ccr.py`).
   Section 6 below.

The goal here is **not** to force the tool's output to equal the papers'.
It is to hold the K-MSR paper's input assumptions and reported results
**fixed**, run the tool on the same inputs, and measure **how far the tool
diverges** — and to locate that divergence in specific model variables.

Runnable (from the repo root; the venv is created by `./run.command`):

```
PYTHONPATH=src .venv/bin/python -m ets.cli --config examples/k_msr_P0_no_reserve.json
PYTHONPATH=src .venv/bin/python -m ets.cli --config examples/k_msr_P1_draft_decree.json
PYTHONPATH=src .venv/bin/python -m ets.cli --config examples/k_msr_A_reserve_price.json
PYTHONPATH=src .venv/bin/python -m ets.cli --config examples/k_msr_B_quantity_rule.json
PYTHONPATH=src .venv/bin/python -m ets.cli --config examples/k_msr_compare_suite.json   # all four
PYTHONPATH=src .venv/bin/python examples/reproduce_k_msr.py   # end-to-end: paths + cancellation sweep + chart
```

---

## 1. Inputs held fixed (paper → tool)

| Assumption | Value used | Source |
|---|---|---|
| Horizon | 2026–2040, annual | paper §3 |
| Sectors | 6 (Steel, Petrochem, Power, Cement, Refinery, Other) | repo Base |
| Cap path | 507 → 355 Mt | repo Base = K-ETS Outlook |
| BAU emissions | 531 → 458 Mt | repo Base |
| Discount / Hotelling rate | 5.5 % | paper §3 / repo Base |
| Free allocation | 0 (whole cap auctioned → Coase price) | repo Base |
| Rule A reserve price | 22,750 → 97,500 KRW by 2035, then held; unsold cancelled | paper §3 |
| Rule B | pre-committed absorption of 50 % of auction volume from 2035, cancelled in full | paper §3 |
| P1 (draft decree) | absorb-above-trigger, release 20 Mt/yr, no cancellation; proxied here as a ±15 Mt cap reprofile 2028–30 / 2031–33 | paper §3 |
| Cancellation sweep | 16 / 32 / 64 / 96 / 128 / 155 Mt over 2027–2035 | paper §4, App. B.1 |

**One input cannot be matched byte-for-byte:** the repo ships the K-ETS
calibration **v0.6**; the paper reports **v1.0**, whose MAC/cap numbers are not
published. Level offsets below are therefore expected and are themselves part of
the measured gap. The clearest symptom is the starting level: the paper's P0
opens at **22,691** KRW in 2026, the tool's at **10,000** — yet both land within
0.5 % of each other by 2040.

---

## 2. Divergence — tool output vs. paper's reported numbers (same inputs)

All paper values from Appendix B ("Numerical verification"); all tool values
re-run from the saved scenario files (see commands above).

| Quantity | Paper (v1.0) | Tool (this repo) | Divergence | Driver |
|---|---|---|---|---|
| P0 price, 2026 | 22,691 | **10,000** | −56 % | calibration v0.6 vs v1.0 level offset |
| P0 price, 2040 | 67,461 | **67,828** | **+0.5 %** — essentially identical | calibrations converge at the horizon |
| Waterbed: P1 2040 = P0 | yes (both 67,461) | **yes (both 67,828)** | **matches exactly** | cap-neutrality holds structurally |
| P1 collapse depth (2031) | −18.2 % (48,452 → 39,638) | **−9.6 % (55,000 → 49,716)** | **~half as deep** | bank-triggered MSR vs. cap-reprofile proxy + MAC steps |
| Max drawdown A / P1 / B | 7.7 % / 18.2 % / 18.6 % | **0 % / 9.6 % / 2.8 %** | tool paths far smoother | zero bank + discrete MAC quantization |
| A floor tracking | pinned 22,750 → 97,500; steel activation 2035 | **pinned exactly; hits 97,500 in 2035** | **0** | floor binds at the auction by construction |
| A price, 2030 | 55,972 (all λ regimes) | **55,972** | **matches exactly** | both = the same linear floor schedule, binding |
| B early premium (2026) | 35,732 (= P0 + 13,041 anticipation) | **10,000 (= P0, no premium)** | tool ≡ paper's λ→0 "relapse" case | tool has no forward transmission — structurally λ = 0 |
| Cancellation, 2035 rise (155 Mt) | +11,198 (26.0 % of the 43,055 required) | **+20,037 (46.5 %)** | overshoots ~1.8× | discrete MAC staircase vs smooth convex curve |
| Cancellation sweep shape | smooth, convex-increasing: +434 / +1,708 / +3,414 / +6,315 / +9,673 / +11,198 at 16→155 Mt | **step function: +7,100 at 16–32 Mt, +20,037 at 64–155 Mt** | non-convex, lumpy | price snaps between MAC block costs (62,100 / 75,037) |
| Discount-rate sensitivity (App. B.2) | A invariant in r; B sensitive (B-2030 falls 57,120 → 51,825, e-NCC slips 2039 → 2037 as r: 4 → 10 %) | **A and B both trivially r-invariant** | B's sensitivity not reproducible | tool runs the no-banking competitive limit; r enters only via banking |
| Banking-limit robustness (App. B.3) | B_max 90/70 Mt lifts no-policy 2030 (41,355 → 54,198), 2040 unchanged at 67,461 | **not runnable as an experiment** — tool's path is already the zero-bank limit | n/a | repo's competitive path clears at the cap with zero bank |
| λ instrument-choice result | central result (three regimes λ→0 / 0.55 / 0.9; floor-aware re-solve ψ=−0.25 → 49,098 / 59,151 / 64,386 in 2030) | **now representable** — `forward_transmission_lambda` blends static/Hotelling prices, floor clipped last; three-regime run delivers an identical floor path from 2028 (paper: from 2030), 2030 = 55,972 in both | regimes differ only above the floor, as in the paper | reduced-form blend (see `modules/transmission/doc/reference.md`); the floor-aware ψ re-solve remains out of scope |
| Dixit–Pindyck trigger, 3.86× → 1.83× (6.4× at empirical σ≈0.48) | central result | **now computable** — `ets.analysis.investment_trigger` reproduces 2.86× (σ=0.20), 3.86× (σ=0.30), 6.4× (σ=0.48), r/y ≈ 1.83× (σ→0) | matches paper's worked values (regression-tested) | post-processing on solved paths; σ is an input, not an engine output |

Reproduced four-scenario price paths (KRW/tCO₂, from the saved files):

| Year | P0 | P1 (reprofile) | A (reserve price) | B (quantity) |
|---|---|---|---|---|
| 2026 | 10,000 | 10,000 | 22,750 | 10,000 |
| 2028 | 34,500 | 50,000 | 39,361 | 34,500 |
| 2031 | 55,000 | **49,716** | 64,278 | 55,000 |
| 2035 | 55,000 | 55,000 | **97,500** | 75,037 |
| 2040 | **67,828** | **67,828** | 97,500 | 114,403 |

The three paper results survive **qualitatively**: (1) the reprofiling reserve is
cap-neutral — P1 returns to the P0 level by 2040; (2) the reserve-price rule
leads the level — A tracks the floor to the 97,500 steel threshold; (3) scarcity
alone cannot lead cleanly — cancellation moves the price only in coarse MAC-step
jumps. And one alignment is exact for an instructive reason: A-2030 = 55,972 in
both, because in both the delivered price *is* the (identical) floor schedule —
the paper's Layer-1 theorem ("the auction floor is mechanical, independent of
banking, liquidity, or transmission") is precisely the mechanism the tool
implements.

---

## 3. Where the divergence lives (the adjustable variables)

1. **Calibration version.** Repo = v0.6 export; paper = v1.0. Explains the
   2026 level offset (10,000 vs 22,691); the near-identical P0-2040 (+0.5 %)
   shows the cumulative cap–BAU balance is close.
2. **Bank dynamics.** The repo's competitive path clears at the cap with a
   **zero bank**, so the bank-triggered MSR never auto-fires. The paper's
   banking/Hotelling path carries a positive bank (89 Mt in 2026, peaking at
   114 Mt in 2028–29, exhausted by 2039) that the MSR acts on. P1 here is a
   cap-reprofile *proxy* (±15 Mt), which is why its collapse is half as deep
   (−9.6 % vs −18.2 %). The zero bank also removes the discount rate from
   price formation, which is why the paper's discount-rate result (price rule
   invariant, quantity rule sensitive — App. B.2) cannot even be posed here.
3. **Discrete MAC.** The repo uses piecewise MAC **blocks**, so the price snaps
   to cost steps (10k, 12k, 34.5k, 55k, 62.1k, 75k, …). This quantizes both the
   collapse and the cancellation response: the sweep is a two-step staircase
   (+7,100 then +20,037) instead of the paper's smooth convex bridge
   (+434 → +11,198), and it *overshoots* the paper at 64+ Mt (46.5 % vs
   7.9–26.0 % of the required rise) because one cancelled block boundary can
   jump the clearing price a full cost step.
4. **Forward-transmission λ — now a knob (reduced-form).** The paper's central
   innovation — a coefficient λ ∈ [0,1] mixing the static and Hotelling
   prices — is now implemented as the scenario field
   `forward_transmission_lambda` (`src/ets/solvers/transmission.py`): the
   delivered price is max(blend, floor), blend first, floor clipped last —
   the operation order that makes the floor λ-independent while the price
   above it varies with λ. The three-regime run on the K-ETS calibration
   (`examples/k_msr_lambda_regimes.json`) delivers an identical floor path
   from 2028 onward (paper: from 2030; both give 2030 = 55,972) with regimes
   differing only above the floor (2026: 22,750 / 24,211 / 33,254 vs the
   paper's up-to-~6,700 KRW pre-2030 spread). The tool's default (no λ) B path
   remains the paper's λ→0 "relapse" case — no early anticipation premium.
   Still out of scope: the floor-aware expectations re-solve (ψ = −0.25) and
   feeding λ back into abatement/investment decisions (that would leave
   partial equilibrium; the paper itself brands λ "reduced-form").
5. **Irreversible-investment channel — now computable as post-processing.**
   The Dixit–Pindyck trigger multiple is available in
   `ets.analysis.investment_trigger` and reproduces the paper's worked values
   (2.86× at σ = 0.20; 3.86× at σ = 0.30; ≈6.4× at the KAU-estimated σ ≈ 0.48;
   r/y ≈ 1.83× in the full-credibility limit), plus activation dating on any
   solved price path. The clearing engine itself stays deterministic — σ is an
   input, and the partial-credibility interior σ_eff(q) is an illustrative
   interpolation the paper leaves unidentified. See
   `modules/transmission/doc/reference.md`.

   **Status update (Phase 1, endogenous investment feedback): this specific
   gap — "post-processing on an exogenous price path, not a two-way
   equilibrium" — is now closed, in reduced form.** `engine/feedback.py`
   wraps the full path solve (competitive or Rubin/Schennach banking) in an
   outer loop that irreversibly adopts a flagged technology the iteration it
   crosses its Dixit–Pindyck trigger on the DELIVERED price path, then
   re-solves; adoption and price are now a joint fixed point, not a reading
   taken off a finished path. `examples/k_msr_decree_induces_investment.json`
   runs the paper's central transition claim as this equilibrium: the
   credible decree package (hybrid MSR + rising auction reserve,
   `invest_credibility=0.8`) delivers Steel/H2-DRI adoption in **2029**,
   while its uncredible twin (`invest_credibility=0.0`, same fundamentals,
   no reserve) **never adopts** — the pure banking ramp tops out around
   9,222 KRW, roughly a third of the uncredible trigger (≈31,931 KRW). The
   math itself is unchanged (`core/investment.py`, the same closed-form β
   and the σ→0 → r/y correction); what changed is that the trigger now reads
   a price path that reacts to its own adoption decisions. See
   `docs/invest-feedback-spec.md` (binding spec) and
   `docs/algorithm-overview.md`, "Endogenous Investment Feedback (Phase 1)".

---

## 4. Theoretical depth vs engineering breadth

**The paper is deeper on a narrow question; the repo is broader but shallower.**

The paper chains five established theory blocks and adds a sixth of its own
(its Table 1 maps each reference to the argument): banking equilibrium (Rubin
1996; Schennach 2000), the waterbed/cap-neutrality theorem with its EU
empirics and refinements (Perino & Willner 2016, 2017, 2019; Perino, Ritz &
van Benthem 2025), reserve-as-supply-rule (Kollenberg & Taschini 2016, 2019),
Weitzman prices-vs-quantities (with Parsons & Taschini 2013 on permanent
shocks), time-consistency/credibility (Kydland & Prescott 1977; Helm, Hepburn
& Mash 2003; Brunner et al. 2012; Sitarz et al. 2024), and Dixit–Pindyck
irreversible investment (with Grüll & Taschini 2011 on the floor as a put
option) — then introduces the **forward-transmission coefficient λ** as an
instrument-choice criterion orthogonal to Weitzman cost-curvature. That is a
genuine analytical contribution with propositions, an appendix of derivations,
and a KRX-calibrated λ ≈ 0 (median cross-vintage carry ≈ 0 %/yr against a
5.5 %/yr Hotelling benchmark).

The repository is a **superset in engineering coverage** of the allowance
market: three price-formation mechanisms (competitive / Hotelling / Nash–Cournot),
MSR, the Carbon Cap Rule (Benmir–Roman–Taschini 2025), multi-jurisdiction CBAM,
Output-Based Allocation, Scope-2 indirect emissions, technology-switching
portfolios, calibration and batch tooling. But on the paper's *specific*
argument it was, until the July 2026 refresh, a **subset in theoretical
depth**: it lacked precisely the two constructs the paper's headline results
turn on. Both now exist as faithful reduced-form ports —

- a **forward-transmission λ** (`forward_transmission_lambda`,
  `src/ets/solvers/transmission.py`), and
- an **irreversible-investment trigger** (`ets.analysis.investment_trigger`),

with the caveats in Section 3 (items 4–5): the λ blend and the trigger make
the paper's results *runnable* here; they do not replace the paper's
derivations (the λ-invariance propositions, the credibility treatment). One
of the deeper extensions — optimal stopping against a partially credible
barrier — is now also a repo feature *in reduced form* (Phase 1, endogenous
investment feedback, Section 3 item 5 status update above); the interior
credibility mapping σ_eff(q) remains the modelling choice the paper itself
leaves unidentified, not a derivation. A floor-aware expectations path and λ
microfoundation remain the paper's open problems, not repo features.

Symmetrically, the repo models mechanisms the paper does not: strategic market
power (Nash–Cournot), border adjustment (CBAM), benchmarked free allocation
(OBA), and endogenous technology choice.

**Bottom line.** The repo reproduces the paper's Result 1 (cap-neutrality and
the cancellation scale wall) natively, Result 2/3's *price-floor mechanics*
faithfully — the P0 level matches within 0.5 % at the horizon and the
delivered floor path is identical where it binds — and, since the July 2026
refresh, the λ-regime comparison and the trigger-multiple arithmetic as
reduced-form modules. What remains the paper's alone is the theory: the
λ-invariance derivation, the identification of λ, and the partially credible
optimal-stopping treatment.

---

## 5. The repo's MSR module vs Kollenberg & Taschini (2019)

The K-MSR paper's own Appendix A.2 states the relationship exactly: the K-ETS
model (and hence this repo) "is the risk-neutral, deterministic limit" of the
Kollenberg–Taschini supply-adjustment framework. KT (2019) is purely
analytical — it reports no numerical calibration — so the comparison is
structural, not numerical.

What the repo's `msr.py` **does capture** (KT pp. 214, 217, 221):

- The **bank-triggered intake/release mechanics**: withhold a rate-share of the
  auction when the aggregate bank exceeds an upper threshold, release from the
  pool below a lower threshold, optional permanent cancellation of the pool
  above a cap — a faithful deterministic transcription of the EC MSR rule KT
  generalize (833 M / 400 M thresholds, 24 %/12 % intake, batch release).
- The **cap-neutrality condition**: KT show an SMM changes abatement/price
  paths iff it changes the expected required abatement or the bank-depletion
  date τ (their Eq. 3) — i.e. iff the no-borrowing availability constraint
  binds. That is a deterministic statement, and it is exactly the waterbed
  logic the repo reproduces in Section 2 above.
- The **quantity channel of cancellation**: cancellation = permanent cap cut =
  more required abatement = higher price — a deterministic comparative static
  the repo runs natively (the sweep above).

What it **structurally cannot** (KT pp. 215–221, Eqs. 4–6):

- The **risk premium** q_t and the paper's headline result: for risk-averse
  firms, a cap-preserving MSR *raises* price volatility, raises the premium,
  accelerates bank depletion and **lowers** abatement and prices — the
  opposite of the MSR's stated goal. A risk-neutral deterministic engine
  mechanically predicts zero effect from any cap-preserving reallocation that
  doesn't bind the availability constraint, never a negative premium effect.
- The **distribution of τ** and "instantaneous breakdown" — the probability
  that a demand shock exceeds the current bank. There is no variance in the
  repo for the SMM to act on (KT model intake as σ(B_t) with ∂σ/∂B < 0).
- The **risk-premium channel of cancellation** (anticipated cancellation
  lowering the riskiness of abatement investment and sustaining prices) —
  only the quantity channel survives determinism.

---

## 6. The repo's Carbon Cap Rule vs Benmir, Roman & Taschini (2025)

BRT (2025) propose the CCR inside a two-sector monthly DSGE, Bayesian-estimated
on EU Phase-3 data (2013–2019), with seven stochastic shocks. The repo's
`ccr.py` ports the rule into the annual deterministic engine.

What **transfers faithfully**:

- The **exact functional form** (BRT §6): Q_t = Q̄ + φ_e·(e−ē)/ē + φ_z·(z−z̄)/z̄.
- The **timing variant**: BRT's main text writes contemporaneous e_t but the
  notes to their Tables 1–2 print **lagged** e_{t−1} — an inconsistency the
  paper never reconciles. The repo implements the lagged form (condition on
  period t−1 realized emissions and abatement cost), which is both the Tables
  1–2 variant and the only causally implementable one for an annual regulator.
- The **sign structure and weighting insight** of the optimum: φ_z > 0 (ease
  the cap when abatement costs run high), φ_e < 0 (tighten on emissions
  overshoot), and φ_z ≫ |φ_e| (their optimum φ_z = 0.1853, φ_e = −0.0027, a
  ~70× ratio) — the rule is closer to a cost-containment mechanism than an
  emissions-tracker. The repo deliberately does **not** hardcode the paper's
  coefficients: they are monthly, normalized-model units and must be rescaled
  to the scenario's cap (see `modules/ccr/doc/reference.md`).
- The **price = MAC identity** as the rule's observable — native to a
  MAC-block model.

What **cannot transfer** (do not quote these numbers as reproducible here):

- Every volatility statistic — the ~80× excess volatility vs the SCC-aligned
  optimum, the price-std reduction (19.17 % → 3.51 %, the paper's stated
  "≈55 %" cut), and the ≈40 % welfare-loss cut in consumption-equivalence
  terms (0.006 % → 0.0036 % CE). All require estimated stochastic shock
  processes and second-order simulation; a deterministic annual model has no
  variance to reduce.
- The variance/historical decomposition by shock (abatement, energy,
  transition demand, supply) and the estimation of unobservable abatement
  shocks.

One extension runs the **other way**: BRT's model has **no banking** — their
CCR is a per-period cap with no intertemporal permit transfer. The repo's CCR
composes with banking/Hotelling scenarios, which is genuinely beyond the
paper's setup (an extension, not a replication — flag it as such in any
write-up).

---

## 7. Exact-reproduction programme (status)

The gap analysis above led to a four-phase plan to make the tool match the
paper exactly; current status:

- **Phase 0 — v1.0 ground truth (open, blocking).** The paper's calibration
  ("K-ETS PE model v1.0", output `msr_results_v1.0`) is PLANiT-internal.
  Without its MAC/cap tables, "exact" means anchor-exact against Appendix B,
  not bit-exact. **Also open: a spec question for the authors** — the
  published P0 rises ≈16 %/yr over 2026–29 while the bank grows 89 → 114 Mt,
  which violates the paper's own A.1 no-arbitrage rule; the tool represents
  this via the reduced-form `hoarding_inflow` (λ ≈ 0 hoarding), but the
  paper's actual mechanism needs confirmation.
- **Phase 1 — banking equilibrium solver: DONE.**
  `model_approach: "banking"` (Rubin/Schennach, endogenous window, bank ≥ 0,
  boundary no-arbitrage checks, MSR/floor composition via schedule fixed
  point, `hoarding_inflow` hook). See modules/banking/doc/reference.md. On the
  unchanged v0.6 calibration with the paper's 89 Mt carry-in it already
  reproduces the paper's P0 architecture: window 2026–2039, bank peak 2029,
  exhaustion by 2039, static 2040 at 67,828 (+0.5 %), 2030 at 40,511 (−2.0 %).
- **Phase 2 — v1.0 calibration: BLOCKED on Phase 0** (else inverse-calibrate
  against Appendix B; smooth parametric MAC and input-price-indexed
  thresholds still to add).
- **Phase 3 — declarative operator pipeline: PARTIAL.** The banking solver
  composes supply rules as re-runnable schedule functions inside its fixed
  point (the architectural prerequisite); the scenario-level
  `policy_pipeline` field and typed-lane validation are still to come.
- **Phase 4 — Appendix B regression suite: RUNNING.**
  `tests/test_paper_appendix_b.py`: 4 anchors PASS (terminal level, carry
  rate, bank shape/exhaustion), 4 documented misses as strict xfails with
  drivers (three calibration-vintage, one the Phase-0 spec question).

## 8. Reproduction notes (July 2026 refresh)

- All tool-side numbers in Section 2 re-verified by running the five configs
  and `examples/reproduce_k_msr.py` (outputs: `k_msr_results.csv`,
  `k_msr_summary.md`, `k_msr_price_paths.png`).
- All paper-side numbers re-verified against the K-MSR paper's Appendix B
  (numerical verification table), and Sections 5–6 against the actual texts of
  KT (2019) and BRT (2025).
- Two fixes were needed to make the reproduction runnable end-to-end:
  `python -m ets.cli` previously did nothing (missing `__main__` guard), and
  the script's P1 scenario expressed the reprofile as auction > cap, which the
  config builder rejects — it now reprofiles `total_cap` directly, matching
  `k_msr_P1_draft_decree.json`.
