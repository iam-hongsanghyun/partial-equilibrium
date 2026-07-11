# Banking — Reference

*(Moved from `docs/banking-equilibrium.md` — WO-17 doc fold.)*

## Banking equilibrium solver (`model_approach: "banking"`)

Implements the deterministic, risk-neutral Rubin/Schennach banking
equilibrium (Rubin 1996; Schennach 2000) — the price-formation rule the K-MSR
working paper's Appendix A.1 builds on — with an **endogenous banking
window**, in `src/ets/solvers/banking.py`.

## Mechanism

```
P_t = P_a · (1+g)^(t−a)      inside the window [a, b]   (no-arbitrage carry)
Σ e_t(P_t) = B_in + Σ S_t    over the window            (cumulative budget)
B_t ≥ 0 inside, B_b = 0                                  (bank validity)
e_t(P_t) = S_t − h_t         outside the window          (static clearing)
```

with `g = discount_rate + risk_premium`, supply `S_t` = free allocation +
auction volume, and no-arbitrage validity checks at both window boundaries
(banking must not be profitable to start earlier or extend later). The window
`[a, b]` is searched — earliest feasible start, longest valid extent — with
the start-year price solved by Brent root-finding on the window budget.

## Configuration

```json
{
  "model_approach": "banking",
  "discount_rate": 0.055,
  "banking_initial_bank": 89.0,
  "banking_strict_no_arbitrage": true,
  "years": [ { "...": "...", "hoarding_inflow": 0.0 } ]
}
```

- `banking_initial_bank` — bank carried into the first year [Mt].
- `hoarding_inflow` (per year) — reduced-form structural hoarding for λ ≈ 0
  markets: the volume clears out of that year's supply (raising its static
  price), accumulates in the bank, and re-enters the window budget when the
  drawdown window opens. Default 0 = textbook equilibrium.
- `banking_strict_no_arbitrage` — `false` keeps the best candidate window
  even when a static segment violates the boundary inequalities (logged), for
  calibrating to markets that structurally hoard without pricing the carry.
- Bank-triggered MSR (`msr_*` fields) and reserve-price floors with
  `unsold_treatment: "cancel"` compose through a schedule fixed point: solve →
  recompute supply from the new bank/prices → re-solve until stable.
- **Hoarding years are static-regime years by definition**: the window never
  starts at or before a year with `hoarding_inflow > 0`, and pre-window
  no-arbitrage checks exempt transitions out of hoarding years (the λ≈0
  friction *is* a documented no-arbitrage violation).

## K-MSR decree modes (`msr_mode`)

The draft-decree rule, parameterized from the PLANiT kets-outlook dashboard
(`src/lib/msr.ts`, K-ETS MSR policy — rule finalization 2026-08):

```json
{
  "msr_enabled": true,
  "msr_mode": "hybrid",              // "price_band" | "surplus_rule" | "hybrid"
  "msr_initial_reserve_mt": 85.277328,
  "msr_price_band_high": 25000.0,    // prev price ≥ high → release
  "msr_price_band_low": 15000.0,     // prev price ≤ low  → intake
  "msr_surplus_upper_ratio": 0.18,   // prev bank/emissions ≥ 18% → intake
  "msr_surplus_lower_ratio": 0.05,   // ≤ 5% → release
  "msr_max_intake_mt": 20.0,
  "msr_max_release_mt": 20.0
}
```

All triggers read previous-year state; `hybrid` takes the majority of the two
signals (ties neutral); releases are capped by the reserve stock. The default
`msr_mode: "bank_threshold"` keeps the original EU-style MSR behaviour.

Observed P1 on the v0.6 calibration (89 Mt carry-in, relaxed mode): the
release rule fires 2032–2036 (20 Mt/yr until the 85.28 Mt reserve is
exhausted), P1 runs up to 10.2 % below P0 mid-path and rejoins P0 exactly at
67,828 by 2040 — cap-neutrality with no cancellation, the paper's Result 1
shape (paper depth −18.2 % at the v1.0 calibration). Saved as
`examples/k_msr_P1_decree_banking.json`. Policy scenarios that perturb supply
generally need `banking_strict_no_arbitrage: false` — the perturbed windows
are not textbook equilibria, which is the point.

Summary output gains `Banking Aggregate Bank`, `Banking Regime`
(static/hotelling), `Banking Window Start/End`, `Banking Floor Cancelled`.

## Policy events: announcement vs execution timing

Rules can be introduced mid-horizon at two distinct levels:

- **Execution timing** — `msr_start_year` / `ccr_start_year` (scenario
  fields), or per-year fields (floors, cancellations). A forward-looking
  solver still *knows* these from the first year.
- **Information timing** — `policy_events`: dated config changes the solver
  does not see before their announcement year. Each announcement re-solves
  the remaining horizon with the expanded information set, inheriting the
  aggregate bank and MSR reserve pool across the splice
  (`src/ets/solvers/events.py`):

```json
"policy_events": [
  {
    "announced": "2031",
    "changes":        { "msr_enabled": true, "msr_mode": "hybrid" },
    "year_overrides": { "2031": { "cancelled_allowances": 16.0 } }
  }
]
```

`examples/k_msr_event_timing_2x2.json` runs the same cancellation (16 Mt/yr,
2031–35) across {banking | static} × {announced 2026 | announced 2031}: under
banking, the price moves at the *announcement* (immediately if announced
up front; +11 % off the no-policy path in 2031 if announced then) and nothing
happens at execution; under static (λ≈0) clearing the two announcement dates
produce **identical** paths — only execution moves the price. That inversion
is the paper's instrument-choice argument as a computable experiment.

Limitations: participant-level bank balances are not carried across splices
(the aggregate bank is the banking solver's state variable), and the
bank-threshold MSR pool resets per segment (the decree modes carry theirs via
`msr_initial_reserve_mt`).

## Status vs the K-MSR paper (Appendix B scoreboard)

`tests/test_paper_appendix_b.py` runs the shipped v0.6 calibration with the
paper's carried-in bank (89 Mt, r = 5.5%). Current verdicts:

| Anchor (paper) | Tool (v0.6) | Verdict |
|---|---|---|
| P0 2040 = 67,461 | 67,828 (+0.5%) | **PASS** (rtol 0.75%) |
| Bank exhausted by 2039 | 4.4 Mt residual | **PASS** |
| Bank peak year 2028–29 | 2029 | **PASS** |
| 5.5%/yr carry inside window | exact | **PASS** |
| P0 2030 = 41,355 | 40,511 (−2.0%) | xfail — calibration vintage |
| 2035 baseline = 54,445 | 52,947 (−2.8%) | xfail — calibration vintage |
| Bank peak = 114 Mt | 130.3 (+14%) | xfail — calibration vintage |
| P0 2026 = 22,691 | 32,701 | xfail — spec: hoarding-shaped early segment |

The 2026 miss is structural, not a bug: the paper's P0 rises ≈16%/yr over
2026–29 **while the bank grows** — a shape textbook no-arbitrage forbids and
the paper itself attributes to Korea's λ ≈ 0 hoarding regime. It becomes
representable here via per-year `hoarding_inflow` once the v1.0 MAC tables
and the hoarding series are available (Phase 0 of the reproduction plan in
docs/k-msr-vs-repo-comparison.md); the xfail flips to a failure the moment
calibration closes it, forcing promotion to a plain assert.

## Analytic test anchors

`tests/test_banking.py` pins the solver to closed forms on a two/three-year
linear-MAC economy: window price `P_a = c(ΣE − ΣS − B_in)/(Σ(1+g)^k)`,
static fallback when banking is unprofitable, deferred windows when the early
bank would go negative, waterbed neutrality of within-window reprofiling, and
the hoarding budget identity.
