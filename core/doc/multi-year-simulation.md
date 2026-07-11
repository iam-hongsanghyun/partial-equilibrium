# Core — Multi-Year Simulation Reference

*(Moved from `docs/multi-year-simulation.md` — WO-17 doc fold.)*

## Multi-Year Simulation, Banking, Borrowing & Expectation Formation

**Files:** `src/ets/solvers/simulation.py`, `src/ets/solvers/expectations.py`, `src/ets/solvers/hotelling.py`, `src/ets/solvers/nash.py`, `src/ets/solvers/msr.py`

A single-year equilibrium is straightforward — find the price where supply meets demand. The multi-year simulation adds four complications: (1) BAU emissions may change year by year via trajectories; (2) allowances can be saved between years (banking); (3) allowances can be borrowed from the future (borrowing); and (4) all intertemporal decisions depend on what participants *expect* future prices to be. This document explains how all these interact, and how the Hotelling and Nash-Cournot price paths extend the base competitive model.

---

## Why multiple years matter

In a single-year model, each year is completely independent. In reality, ETS participants are forward-looking:

- A company with cheap abatement might over-abate today, bank surplus allowances, and sell them when prices are higher.
- A company facing a spike in emissions might borrow next year's allowances to avoid buying at a high spot price.
- Both decisions shift supply and demand in every year they affect, changing the equilibrium price trajectory.
- If BAU emissions are declining (e.g. due to structural change), the compliance obligation changes year by year even without policy tightening.

The multi-year simulation captures these dynamics by passing **bank balances** and **carry-forward supply** forward in time, by modelling **BAU trajectories** that modify initial emissions per year, and by solving for **consistent expectations** about future prices.

---

## State carried between years

Three pieces of state propagate from year `t` to year `t+1`:

### 1. Bank balances

A `dict[participant_name → float]` tracking the cumulative allowances each participant has saved (positive) or borrowed (negative):

```python
bank_balances_t+1 = {
    row["Participant"]: row["Ending Bank Balance"]
    for _, row in participant_df.iterrows()
}
```

### 2. MSR reserve pool

When `msr_enabled = true`, the `MSRState.reserve_pool` accumulates withheld allowances and persists across years. See the [MSR Integration](#msr-integration) section below.

### 3. Carry-forward allowances

Unsold auction allowances re-enter the next year's supply if `unsold_treatment = "carry_forward"`:

```python
carry_forward_t+1 = (
    equilibrium["unsold_allowances"]
    if market.unsold_treatment == "carry_forward"
    else 0.0
)
```

---

## BAU Emissions Trajectory

### What it is

The `initial_emissions_trajectory` field on a participant specifies a smoothly changing **business-as-usual** gross emissions level across the simulation horizon. This replaces the need to specify a different `initial_emissions` in every year config.

### Structure

```json
"initial_emissions_trajectory": {
  "start_year": "2026",
  "end_year": "2035",
  "start_value": 82.0,
  "end_value": 58.0
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `start_year` | string | Yes | Year label matching first year of trajectory window |
| `end_year` | string | Yes | Year label matching last year of trajectory window |
| `start_value` | float | Yes | BAU emissions at `start_year` (Mt CO₂e) |
| `end_value` | float | Yes | BAU emissions at `end_year` (Mt CO₂e) |

### Interpolation formula

$$E_0(t) = E_{start} + (E_{end} - E_{start}) \cdot \frac{t - t_{start}}{t_{end} - t_{start}}$$

Years before `start_year` receive `E_{start}`. Years after `end_year` receive `E_{end}`.

### Example: POSCO BAU decline 2026–2035

```
Year 2026: E₀ = 82.0 Mt
Year 2030: E₀ = 82 + (58-82) × (2030-2026)/(2035-2026) = 82 - 10.7 = 71.3 Mt
Year 2035: E₀ = 58.0 Mt
```

### Interaction with per-year `initial_emissions`

The trajectory **overrides** the per-year `initial_emissions` field:

```python
# From builder.py
ie_traj = participant.get("initial_emissions_trajectory") or {}
if ie_traj:
    overridden = _interp_value(year_num, ie_traj)
    if overridden is not None:
        participant["initial_emissions"] = max(0.0, overridden)
```

The per-year value is still required in the JSON for compatibility (it provides a default if the trajectory is not active or outside the window), but is silently replaced when the trajectory is active. This design allows the same participant dict to be used in all years while the trajectory handles year-specific values.

### Why use BAU trajectories instead of per-year values

1. **Less repetition:** A single trajectory replaces identical year-by-year copy-paste.
2. **Consistency:** Trajectory values are guaranteed to be linearly interpolated — no risk of non-monotone accidental entries.
3. **Policy interaction:** OBA benchmarks are also declining over time (see [oba-allocation.md](../../modules/oba/doc/reference.md)), and BAU trajectories let you model structural efficiency improvements separately from benchmark tightening.

---

## Grid Emission Factor Trajectory

### Purpose

As the Korean electricity grid decarbonises (renewables growth, nuclear expansion), the emission intensity of purchased electricity falls. `grid_emission_factor_trajectory` models this without specifying `grid_emission_factor` in every year config.

### Structure

Identical four-key schema as `initial_emissions_trajectory`:

```json
"grid_emission_factor_trajectory": {
  "start_year": "2026",
  "end_year": "2035",
  "start_value": 0.450,
  "end_value": 0.280
}
```

This models the Korean grid declining from 0.45 tCO₂/MWh (2026) to 0.28 tCO₂/MWh (2035), consistent with KEPCO decarbonisation plans.

### Effect on Scope 2 calculation

Each year, the interpolated `grid_emission_factor` is used in:

$$\text{indirect\_emissions} = \text{electricity\_consumption} \times G(t)$$

where $G(t)$ is the trajectory-interpolated grid factor. This causes Scope 2 emissions (and Scope 2 CBAM liability) to decline over time even if electricity consumption stays constant — reflecting the grid mix improvement.

### Combined example (electricity + declining grid)

A participant with `electricity_consumption = 1000 MWh` and a grid factor declining from 0.45 to 0.28:

| Year | Grid factor | Indirect emissions | Scope 2 CBAM (at €72 vs ₩35k gap) |
|---|---|---|---|
| 2026 | 0.450 tCO₂/MWh | 450 t CO₂ | Proportional to 450 t |
| 2030 | 0.366 tCO₂/MWh | 366 t CO₂ | Proportional to 366 t |
| 2035 | 0.280 tCO₂/MWh | 280 t CO₂ | Proportional to 280 t |

---

## Banking: saving allowances for the future

**Enabled by:** `banking_allowed: true` in year config

When a participant ends a year with a natural surplus, they can either sell the surplus immediately or bank it for a future year.

### Banking decision rule

```python
natural_balance = free_allocation + starting_bank_balance - residual_emissions

if natural_balance >= 0.0:                          # surplus
    if banking_allowed and expected_future_price > carbon_price:
        ending_bank_balance = natural_balance       # bank it
    else:
        ending_bank_balance = 0.0                   # sell now
```

**Intuition:** Bank if and only if the future price exceeds the current price. Saving an allowance and selling next year is like earning a return equal to `(P_future - P_current) / P_current`. Banking continues until this return equals zero (prices equalise), which is the competitive arbitrage condition.

### Balance sheet mechanics

```
Starting bank balance   B₀   (carried from previous year; 0 in first year)
Free allocation         F    (= initial_emissions × free_allocation_ratio)
Residual emissions      E_r  (= initial_emissions − abatement)
──────────────────────────────────────────────────────────────
Natural position        N = F + B₀ − E_r

  N > 0: surplus → bank or sell
  N < 0: shortage → borrow or buy
```

### Effect on market equilibrium

Banked allowances reduce a participant's net demand in the current year. In future years, they increase supply. This creates a **price-smoothing arbitrage**: participants front-run price differentials until the differences are arbitraged away.

---

## Borrowing: using future allowances today

**Enabled by:** `borrowing_allowed: true` + `borrowing_limit > 0`

### Borrowing decision rule

```python
if natural_balance < 0.0:                           # shortage
    if borrowing_allowed and carbon_price > expected_future_price:
        ending_bank_balance = max(-borrowing_limit, natural_balance)
    else:
        ending_bank_balance = 0.0                   # buy on market now
```

**Intuition:** Borrow if the current price exceeds the expected future price. You are effectively pre-paying future compliance at a higher price — borrowing lets you wait and pay at the lower future price instead.

`ending_bank_balance` is negative when borrowing. Repayment is implicit: in the following year, the negative starting balance increases the participant's effective shortage, raising their demand in that year.

---

## Expectation formation rules

Configured per year via `expectation_rule`. Governs the `P_future` used in banking and borrowing decisions.

### Rule 1: `myopic`

$$P_f = 0$$

Participants ignore the future entirely. No banking (surplus is always sold because $P_f < P^*$ always). Borrowing fires vacuously (current price always exceeds zero) but is bounded by `borrowing_limit`. Useful as a baseline that eliminates intertemporal arbitrage.

**Use case:** Calibration baseline, short-horizon compliance behaviour, stress testing.

### Rule 2: `next_year_baseline` (default)

$$P_f = \text{baseline\_price}(\text{next\_year})$$

`baseline_prices` is the independent equilibrium price of each year solved in isolation (no banking, no carry-forward). This is model-consistent and does not create a circular dependency. It is the most practical default for most simulations.

**Use case:** Standard multi-year K-ETS analysis.

### Rule 3: `perfect_foresight`

$$P_f = P^*_{\text{next\_year}}$$

Participants know the actual future equilibrium price. Creates a circular dependency (expectations → banking → prices → expectations) resolved by the fixed-point iteration described below.

**Use case:** Economic theory benchmark, long-run policy analysis, internal consistency checks.

### Rule 4: `manual`

$$P_f = \text{manual\_expected\_price}$$

User-specified constant expected price. No iteration required. Does not change across years unless set differently in each year config.

**Use case:** Sensitivity analysis, anchored futures-market expectations, scenario where participants observe forward prices directly.

---

## Perfect foresight — rational expectations equilibrium

`perfect_foresight` creates a circular dependency (expectations → decisions → outcomes → prices → expectations). Resolved by **fixed-point iteration**:

```
Step 0: Initial guess
    expected_prices = { year: baseline_equilibrium_price(year) }

Step 1–25: Iterate
    a) Simulate full path using expected_prices → realised_prices
       (MSR is NOT applied during this inner loop — only in the final path)
    b) Update: expected_prices ← realised_prices  (for perfect_foresight years only)
    c) max_delta = max |new_expected[y] − old_expected[y]|
    d) If max_delta ≤ solver_competitive_tolerance: CONVERGED
```

**Why exclude MSR from the inner loop:** The MSR rule is discontinuous (bank crosses a threshold → discrete supply change). Including it in the convergence loop would prevent clean convergence. The MSR is applied in the final path only, after prices have converged under the smooth (no-MSR) model.

### Example convergence trace (3-year scenario)

```
Year    Baseline   Iteration 1   Iteration 2   Converged
2026      18,500       21,000        20,200       20,200
2030      25,000       20,500        21,000       21,000
2035      35,000       35,000        35,000       35,000
```

Note: the last year always receives `P_f = 0` (no next year), so it anchors the convergence. Interior years converge inward from the boundary.

---

## Hotelling price path

**File:** `src/ets/solvers/hotelling.py`
**Activated by:** `model_approach: "hotelling"`

### Theory

The Hotelling Rule (1931) states that for an exhaustible resource in competitive equilibrium, the net price (royalty) must rise at the rate of interest. Applied to carbon allowances with an optional risk premium $\rho$:

$$P^*(t) = \lambda \cdot (1 + r + \rho)^{t - t_0}$$

If prices rose faster than `r + ρ`, participants would bank heavily today, cutting current supply and driving prices up. If prices rose slower, they would front-load compliance, reducing future demand. The Hotelling condition is the no-arbitrage path consistent with exhausting the budget exactly.

### Bisection on λ

`λ` is found by bisection:

```
1. Bracket: find [λ_low, λ_high] such that
   total_emissions(λ_low) > total_budget AND
   total_emissions(λ_high) < total_budget

2. Bisect until:
   |total_emissions(λ_mid) − total_budget| / total_budget ≤ solver_hotelling_convergence_tol
```

### Config fields

| Field | Role |
|---|---|
| `carbon_budget` | Per-year budget contributing to cumulative target; sum across years |
| `discount_rate` | Annual discount rate `r` in `(1+r+ρ)^t` |
| `risk_premium` | Policy risk premium `ρ` steepening the price path |
| `solver_hotelling_max_bisection_iters` | Maximum bisection steps (default 80) |
| `solver_hotelling_max_lambda_expansions` | Bracket expansion attempts (default 20) |
| `solver_hotelling_convergence_tol` | Relative tolerance on cumulative emissions (default 1e-4) |

### Key difference from competitive

In competitive mode, each year's price is determined by supply-demand clearing. In Hotelling mode, prices are **pinned** to the theoretical path; participants are still price-takers at the pinned price but the price itself is exogenous from the solver's perspective.

---

## Nash-Cournot price path

**File:** `src/ets/solvers/nash.py`
**Activated by:** `model_approach: "nash_cournot"`

### When it applies

When a small number of large participants can move the market price by changing their abatement or purchase decisions, the competitive model overstates equilibrium abatement. Nash-Cournot captures this market-power effect.

### Config fields

| Field | Role |
|---|---|
| `nash_strategic_participants` | Names of strategic participants; empty = all |
| `solver_nash_price_step` | Finite-difference step for `dP/dQ` estimation |
| `solver_nash_max_iters` | Maximum Jacobi iterations per year |
| `solver_nash_convergence_tol` | Convergence tolerance on abatement (Mt) |

See [algorithm-overview.md](../../docs/algorithm-overview.md) for the full Nash-Cournot algorithm.

---

## Sector-level dynamics

When `sectors[]` is defined at the scenario level, multi-year dynamics change in three ways:

### 1. Sector caps decline over time

Each sector has a `cap_trajectory` that linearly interpolates the sector's total cap per year. The sum of all sector caps replaces the per-year `total_cap`:

$$\text{total\_cap}(t) = \sum_s \text{sector\_cap}_s(t)$$

### 2. Auction share by sector evolves

Each sector has an `auction_share_trajectory`. The fraction of the sector cap auctioned rises over time (reflecting phase-out of free allocation):

$$\text{auction\_offered}(t) = \sum_s \text{sector\_cap}_s(t) \times \text{auction\_share}_s(t)$$

### 3. Per-participant free allocation changes automatically

As the sector cap and auction share change, each participant's derived free allocation changes:

$$\text{free\_allocation\_ratio}_i(t) = \min\!\left(1,\; \frac{(\text{sector\_cap}_s(t) - \text{sector\_auction}_s(t)) \times \sigma_i}{E_{0,i}(t)}\right)$$

where $\sigma_i$ = `sector_allocation_share`. As the auction share rises, the free pool shrinks, so `free_allocation_ratio` automatically declines over the pathway — no per-year specification needed.

---

## Policy trajectories

Four types of smooth policy trajectories avoid the need to repeat values in every year config. All use linear interpolation:

$$\text{value}(t) = v_{start} + (v_{end} - v_{start}) \cdot \frac{t - t_{start}}{t_{end} - t_{start}}$$

### Free-allocation phase-out (`free_allocation_trajectories`)

```json
"free_allocation_trajectories": [
  {
    "participant_name": "Steel Plant A",
    "start_year": "2026",
    "end_year": "2034",
    "start_ratio": 1.0,
    "end_ratio": 0.0
  }
]
```

**Interaction with `cap_trajectory`:** The cap consistency check (`free_allocs + auction ≤ cap`) runs **after** all trajectories are applied. This means you can safely specify a high per-year `free_allocation_ratio` in the JSON while the trajectory reduces it, without triggering a false validation error.

### Cap trajectory (`cap_trajectory`)

Overrides `total_cap` for years within the window. When `sectors[]` is also defined, the sector-derived total cap takes precedence over this trajectory.

### Price floor trajectory (`price_floor_trajectory`)

Overrides `price_lower_bound` per year. Used to model rising carbon price floors as in the K-ETS 4th Allocation Plan.

### Price ceiling trajectory (`price_ceiling_trajectory`)

Overrides `price_upper_bound` per year. Useful for modelling widening price bands over time.

### Trajectory application order (build time)

```
1. Raw JSON loaded, normalised (config-time validation)
2. Sector derivations: total_cap, auction_offered, sector_pools
3. BAU trajectories: initial_emissions per participant
4. Grid factor trajectories: grid_emission_factor per participant
5. OBA overrides: free_allocation_ratio from benchmark × output
6. Cap trajectory: total_cap override
7. Price floor/ceiling trajectories: price bounds
8. Free allocation trajectories: per-participant ratio override
9. Cap consistency check (build-time validation)
```

---

## MSR integration

**File:** `src/ets/solvers/msr.py`
**Enabled by:** `msr_enabled: true`

The MSR adjusts auction supply **before each year's market clearing**. The sequence within Layer 3 for each year `t` is:

```
1. Compute total_bank = Σ_i starting_bank_balance_i

2. Apply MSR:
   effective_auction, withheld, released = msr_state.apply(
       total_bank, auction_offered, upper_threshold, lower_threshold,
       withhold_rate, release_rate, cancel_excess, cancel_threshold
   )

3. Solve equilibrium with effective_auction as the supply target

4. Update msr_state.reserve_pool (persists to year t+1)
```

MSR withholding/release amounts appear in year-level outputs (`MSR Withheld`, `MSR Released`, `MSR Reserve Pool`). The equilibrium solver has no visibility into whether supply was adjusted by the MSR.

---

## CBAM: post-equilibrium computation

CBAM liability is computed after $P^*$ is determined for each year. It does not feed back into the market-clearing equation.

### Direct CBAM

$$\text{CBAM}_i(t) = \max(0,\; P_{EUA}(t) - P^*(t)) \times E_{r,i}(t) \times s_i \times c_i$$

### Multi-jurisdiction CBAM

$$\text{CBAM}_i(t) = \sum_j \max(0,\; P_j(t) - P^*(t)) \times E_{r,i}(t) \times s_{ij} \times c_{ij}$$

### Scope 2 CBAM

$$\text{Scope2\_CBAM}_i(t) = \max(0,\; P_{EUA}(t) - P^*(t)) \times E_{elec,i}(t) \times G_i(t) \times k_i$$

where $G_i(t)$ is the trajectory-interpolated grid emission factor.

---

## Auction revenue decomposition

The scenario summary automatically computes three metrics after each year's clearing:

### Domestic Retained Revenue

$$\text{DRR}(t) = P^*(t) \times \text{auction\_sold}(t)$$

Revenue that flows directly to the Korean government's climate fund. This is the primary auction revenue metric.

### CBAM Foregone Revenue

$$\text{CFR}(t) = \sum_i \text{CBAM\_liability}_i(t)$$

The total CBAM liability paid by Korean participants to their importing jurisdictions (EU, UK, etc.). This represents money that *would have remained in Korea* as domestic auction revenue if the KAU price equalled the EUA price. It is a measure of the fiscal cost of the K-ETS/ETS price gap.

### Potential Revenue if KAU = EUA

$$\text{PRE}(t) = \text{DRR}(t) + \text{CFR}(t)$$

The domestic auction revenue that Korea *could* have if the carbon price gap were closed. This is an upper bound on the domestic revenue benefit of K-ETS tightening.

**Policy interpretation:** The difference between PRE and DRR is the "price gap penalty" — the revenue lost to foreign CBAM because the domestic price lags the reference price. Tracking this over time shows the fiscal urgency of converging KAU and EUA prices.

---

## Sequential year execution

The inner simulation loop runs each year in order:

```python
bank_balances = {p.name: 0.0 for p in first_year_participants}
carry_forward = 0.0
msr_state = MSRState() if msr_enabled else None

for market in ordered_markets:
    P_future = expected_prices[str(market.year)]
    B_start  = dict(bank_balances)

    # ── 1. MSR supply adjustment ─────────────────────────────
    if msr_state and market.msr_enabled:
        total_bank = sum(bank_balances.values())
        adj_auction, withheld, released = msr_state.apply(
            total_bank, market.auction_offered,
            upper_threshold, lower_threshold,
            withhold_rate, release_rate, cancel_excess, cancel_threshold,
        )
        effective_carry = carry_forward + released - withheld
    else:
        effective_carry = carry_forward

    # ── 2. Equilibrium (Layer 2) ─────────────────────────────
    equilibrium = market.solve_equilibrium(
        bank_balances=bank_balances,
        expected_future_price=P_future,
        carry_forward_in=effective_carry,
    )
    P_star = equilibrium["price"]

    # ── 3. Participant outcomes + CBAM (Layer 1 + post-process)
    participant_df = market.participant_results(
        P_star, bank_balances, P_future
    )

    # ── 4. State update ───────────────────────────────────────
    carry_forward = (
        equilibrium["unsold_allowances"]
        if market.unsold_treatment == "carry_forward" else 0.0
    )
    bank_balances = {
        row["Participant"]: row["Ending Bank Balance"]
        for _, row in participant_df.iterrows()
    }
```

---

## Edge cases and guards

| Situation | Handling |
|---|---|
| First year (no prior bank balance) | All `starting_bank_balance = 0` |
| Last year (no next year) | `expected_future_price = 0` regardless of rule — correct: no future price to expect |
| Participant added mid-pathway | Starts with `bank_balance = 0` (not in prior year's dict) |
| Borrowing limit = 0 | Disables borrowing even if `borrowing_allowed = true` |
| `perfect_foresight` on only some years | Other years use their own rules; iteration only updates perfect_foresight years |
| MSR disabled | `reserve_pool` never created; `effective_auction = auction_offered` throughout |
| `carbon_budget = 0` with Hotelling | Falls back to `total_cap` per year as budget; logs a warning |
| Nash with no strategic participants | Falls back to competitive equilibrium immediately |
| BAU trajectory outside window | Before `start_year`: uses `start_value`; after `end_year`: uses `end_value` |
| OBA fields present but one is zero | OBA override does not fire; `free_allocation_ratio` used as-is |

---

## Interaction between banking and price trajectory

Banking creates a **price-smoothing arbitrage**. Consider a scenario where the cap tightens sharply in 2035:

**Without banking:**

```
2026: P* = 18,500 ₩/t   (loose cap, low price)
2035: P* = 65,000 ₩/t   (tight cap, price spikes)
```

**With banking + `next_year_baseline` expectations:**

```
2026: P* = 32,000 ₩/t   (participants bank → less current supply → price rises)
2035: P* = 38,000 ₩/t   (banked allowances re-enter → price falls from 65k)
```

Banking arbitrages the price difference down until the differential equals the opportunity cost of holding allowances. The exact level depends on the discount rate, expectation rule, and available surplus.

---

## See also

- [Market Equilibrium Solver](market-equilibrium.md) — how each year's price is found
- [MAC & Abatement Models](mac-abatement.md) — how participant demand responds to price
- [Algorithm Overview](../../docs/algorithm-overview.md) — full execution flow and modelling approaches
- [Output-Based Allocation](../../modules/oba/doc/reference.md) — OBA interaction with trajectories
- [Sector Configuration](../../modules/sectors/doc/reference.md) — sector-level dynamics in depth
