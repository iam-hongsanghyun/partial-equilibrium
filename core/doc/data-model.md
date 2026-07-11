# Core — Data Model & Configuration Schema Reference

*(Moved from `docs/data-model.md` — WO-17 doc fold.)*

## Data Model & Configuration Schema

**Files:** `src/ets/config_io/normalize.py`, `src/ets/config_io/builder.py`

All simulation inputs are represented as a single JSON object. This document describes every field — its type, default, validation rule, example value, and how it interacts with other fields. Two-stage validation (config-time and build-time) is documented at the end.

---

## Top-level structure

```json
{
  "scenarios": [
    { ...scenario_object },
    { ...scenario_object }
  ]
}
```

A config must contain at least one scenario. Multiple scenarios run independently and are compared in the Scenario tab. Each scenario contains one or more year objects, and each year contains one or more participant objects.

---

## Scenario object

```json
{
  "name": "K-ETS Phase 4 Baseline",
  "model_approach": "competitive",
  "discount_rate": 0.04,
  "risk_premium": 0.0,
  "nash_strategic_participants": [],
  "msr_enabled": false,
  "msr_upper_threshold": 200.0,
  "msr_lower_threshold": 50.0,
  "msr_withhold_rate": 0.12,
  "msr_release_rate": 50.0,
  "msr_cancel_excess": false,
  "msr_cancel_threshold": 400.0,
  "solver_competitive_max_iters": 25,
  "solver_competitive_tolerance": 0.001,
  "solver_hotelling_max_bisection_iters": 80,
  "solver_hotelling_max_lambda_expansions": 20,
  "solver_hotelling_convergence_tol": 0.0001,
  "solver_nash_price_step": 0.5,
  "solver_nash_max_iters": 120,
  "solver_nash_convergence_tol": 0.001,
  "solver_penalty_price_multiplier": 1.25,
  "cap_trajectory": { "start_year": "2026", "end_year": "2035",
                       "start_value": 560.0, "end_value": 400.0 },
  "price_floor_trajectory": {},
  "price_ceiling_trajectory": {},
  "free_allocation_trajectories": [],
  "sectors": [],
  "years": [ { ...year_object } ]
}
```

### Core scenario fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `name` | string | — | Required; non-empty | `"K-ETS Baseline"` | Error: scenario must have a name |
| `model_approach` | string | `"competitive"` | One of `"competitive"`, `"hotelling"`, `"nash_cournot"`, `"all"` | `"hotelling"` | Defaults to competitive |
| `discount_rate` | float | `0.04` | Any float; used only when `model_approach = "hotelling"` | `0.04` | Defaults to 4% — only relevant for Hotelling |
| `risk_premium` | float | `0.0` | Any float ≥ 0; used only for Hotelling | `0.02` | Zero risk premium — pure Hotelling |
| `nash_strategic_participants` | string[] | `[]` | Names must match participants; empty = all are strategic | `["POSCO"]` | All participants are strategic when Nash mode is used |
| `years` | array | — | Required; at least one element | — | Error: must have years |

### MSR fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `msr_enabled` | bool | `false` | — | `true` | MSR inactive; `effective_auction = auction_offered` |
| `msr_upper_threshold` | float | `200.0` | > 0; Mt CO₂e | `200.0` | Uses default; only relevant when MSR enabled |
| `msr_lower_threshold` | float | `50.0` | ≥ 0; < `msr_upper_threshold` | `50.0` | Uses default; only relevant when MSR enabled |
| `msr_withhold_rate` | float | `0.12` | [0, 1] | `0.12` | 12% of auction withheld when bank is high |
| `msr_release_rate` | float | `50.0` | ≥ 0; Mt | `50.0` | 50 Mt released per year when bank is low |
| `msr_cancel_excess` | bool | `false` | — | `true` | No cancellation; pool grows without limit |
| `msr_cancel_threshold` | float | `400.0` | ≥ 0; Mt | `400.0` | Only relevant when `msr_cancel_excess = true` |

### CCR fields (Carbon Cap Rule)

The CCR is an adaptive Taylor-rule cap mechanism that adjusts the quantity of permits issued each period in response to deviations in aggregate emissions and abatement cost from their reference levels. See [carbon-cap-rule.md](../../modules/ccr/doc/reference.md) for the full algorithm and calibration guide. For how CCR interacts with the price-elastic baseline channel, see [feedback-coupling.md](../../docs/feedback-coupling.md).

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `ccr_enabled` | bool | `false` | — | `true` | CCR inactive; cap issued equals `total_cap` unchanged |
| `ccr_phi_emissions` | float | `0.0` | Any float | `-0.003` | 0 — emissions gap has no effect on the cap |
| `ccr_phi_abatement_cost` | float | `0.0` | Any float | `0.185` | 0 — abatement-cost gap has no effect on the cap |
| `ccr_reference_emissions` | float | `0.0` | ≥ 0; Mt CO₂e | `480.0` | 0 — disables the CCR emissions term entirely |
| `ccr_reference_abatement_cost` | float | `0.0` | ≥ 0 | `1200.0` | 0 — disables the CCR abatement-cost term entirely |

**Sign convention** (from the paper's optimal coefficients):

- `ccr_phi_emissions` should be **negative**: emissions above the reference → fewer permits issued → tighten the cap.
- `ccr_phi_abatement_cost` should be **positive**: abatement costs above the reference → more permits issued → ease cost pressure.

**Discrete-time behaviour:** The CCR conditions period *t*'s adjustment on the **previously realised** (period *t*−1) emissions and abatement cost. The first year of a multi-year run therefore carries no adjustment (Q₀ = Q̄).

**Cap formula:**

$$Q_t = \overline{Q} + \phi_e \frac{e_{t-1} - \bar{e}}{\bar{e}} + \phi_z \frac{z_{t-1} - \bar{z}}{\bar{z}}$$

where Q̄ is the year's `total_cap`, ē is `ccr_reference_emissions`, and z̄ is `ccr_reference_abatement_cost`.

### Price-elastic feedback field

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `reference_carbon_price` | float | `0.0` | ≥ 0 | `30.0` | 0 — price-elastic baseline channel disabled scenario-wide |

`reference_carbon_price` is the undistorted (P_ref) carbon price that anchors the price-elastic activity baseline (Feedback A). When set to a positive value, each participant whose `output_price_elasticity` is also positive will see their BAU activity — and hence their initial emissions — contract as the market price rises above P_ref. Setting this to `0` disables the channel for the whole scenario regardless of participant-level elasticities. See [feedback-price-elastic-baseline.md](../../modules/elastic_baseline/doc/reference.md) for the full formula and calibration guidance.

### Solver parameter fields

| Field | Type | Default | What it controls |
|---|---|---|---|
| `solver_competitive_max_iters` | int | `25` | Maximum perfect-foresight fixed-point iterations |
| `solver_competitive_tolerance` | float | `0.001` | Convergence threshold for perfect-foresight iteration (₩/t) |
| `solver_hotelling_max_bisection_iters` | int | `80` | Maximum bisection steps for finding shadow price λ |
| `solver_hotelling_max_lambda_expansions` | int | `20` | Maximum attempts to expand the λ bracket |
| `solver_hotelling_convergence_tol` | float | `0.0001` | Relative tolerance on cumulative emissions for Hotelling |
| `solver_nash_price_step` | float | `0.5` | Finite-difference step (₩/t) for estimating dP/dQ |
| `solver_nash_max_iters` | int | `120` | Maximum Jacobi best-response iterations per year |
| `solver_nash_convergence_tol` | float | `0.001` | Max abatement change (Mt) for Nash convergence |
| `solver_penalty_price_multiplier` | float | `1.25` | Upper bracket = `max(penalty_price) × multiplier` |

### Trajectory fields (scenario-level)

All trajectory objects follow the same four-key schema:

```json
{
  "start_year": "2026",
  "end_year": "2035",
  "start_value": 560.0,
  "end_value": 400.0
}
```

An empty object `{}` disables the trajectory. If any of the four keys is missing or unparseable, the trajectory is silently disabled.

| Field | Overrides | Applied to | When omitted |
|---|---|---|---|
| `cap_trajectory` | `total_cap` per year | All years in scenario | Per-year `total_cap` used as-is |
| `price_floor_trajectory` | `price_lower_bound` per year | All years | Per-year value used |
| `price_ceiling_trajectory` | `price_upper_bound` per year | All years | Per-year value used |
| `free_allocation_trajectories[]` | `free_allocation_ratio` per named participant | Named participants only | Per-year ratio used as-is |

#### Free-allocation trajectory array element

```json
{
  "participant_name": "Steel Plant A",
  "start_year": "2026",
  "end_year": "2034",
  "start_ratio": 1.0,
  "end_ratio": 0.0
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `participant_name` | string | Yes | Must match a participant name exactly |
| `start_year` | string | Yes | Year at which `start_ratio` applies |
| `end_year` | string | Yes | Year at which `end_ratio` applies |
| `start_ratio` | float [0,1] | Yes | `free_allocation_ratio` at `start_year` |
| `end_ratio` | float [0,1] | Yes | `free_allocation_ratio` at `end_year` |

### Sectors array

When `sectors[]` is non-empty, the simulator derives `total_cap`, `auction_offered`, and per-participant `free_allocation_ratio` from sector-level definitions, overriding per-year values. See [sector-config.md](../../modules/sectors/doc/reference.md) for full documentation.

#### Sector object

```json
{
  "name": "Steel",
  "cap_trajectory": { "start_year": "2026", "end_year": "2035",
                       "start_value": 120.0, "end_value": 80.0 },
  "auction_share_trajectory": { "start_year": "2026", "end_year": "2035",
                                  "start_value": 0.03, "end_value": 0.15 },
  "carbon_budget": 0.0
}
```

| Field | Type | Default | Validation | Description |
|---|---|---|---|---|
| `name` | string | — | Required; non-empty; must match `sector_group` on participants | Sector identifier |
| `cap_trajectory` | object | `{}` | Four-key trajectory | Sector's total cap declining over years (Mt CO₂e) |
| `auction_share_trajectory` | object | `{}` | Four-key trajectory; values in [0,1] | Fraction of sector cap offered at auction |
| `carbon_budget` | float | `0.0` | ≥ 0 | Cumulative budget for Hotelling path within this sector (reserved for future use) |

---

## Year object

One year object configures a complete market period.

```json
{
  "year": "2030",
  "total_cap": 500.0,
  "auction_mode": "explicit",
  "auction_offered": 300.0,
  "reserved_allowances": 0.0,
  "cancelled_allowances": 20.0,
  "auction_reserve_price": 15.0,
  "minimum_bid_coverage": 0.8,
  "unsold_treatment": "reserve",
  "price_lower_bound": 10.0,
  "price_upper_bound": 200.0,
  "banking_allowed": true,
  "borrowing_allowed": false,
  "borrowing_limit": 0.0,
  "expectation_rule": "next_year_baseline",
  "manual_expected_price": 0.0,
  "carbon_budget": 0.0,
  "eua_price": 72.0,
  "eua_prices": { "EU": 72.0, "UK": 58.0 },
  "eua_price_ensemble": { "EC": 70.0, "Enerdata": 75.0, "BNEF": 82.0 },
  "participants": [ { ...participant_object } ]
}
```

### Market structure fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `year` | string | `"2030"` | Non-empty | `"2030"` | Error: year label required |
| `total_cap` | float | `0.0` | ≥ 0 | `500.0` | 0 — no effective cap (solver proceeds but cap constraint never binds) |
| `auction_mode` | string | `"explicit"` | `"explicit"` or `"derive_from_cap"` | `"derive_from_cap"` | Defaults to explicit |
| `auction_offered` | float | `0.0` | ≥ 0; used only when `auction_mode = "explicit"` | `300.0` | 0 — no auction |
| `reserved_allowances` | float | `0.0` | ≥ 0 | `10.0` | 0 — nothing held in reserve |
| `cancelled_allowances` | float | `0.0` | ≥ 0 | `5.0` | 0 — no cancellations |

**Supply identity:** `free_allocations + auction_offered + reserved + cancelled ≤ total_cap`. Validated at build time (after trajectories applied).

**`auction_mode = "derive_from_cap"` formula:**

```
auction_offered = total_cap - free_allocations - reserved - cancelled
```

Raises `ValueError` if the result is negative.

### Auction design fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `auction_reserve_price` | float | `0.0` | ≥ 0 | `15.0` | No reserve — auction clears at any price |
| `minimum_bid_coverage` | float | `0.0` | [0, 1] | `0.8` | No coverage requirement — auction always proceeds |
| `unsold_treatment` | string | `"reserve"` | `"reserve"`, `"cancel"`, `"carry_forward"` | `"carry_forward"` | Unsold allowances go to government reserve |

**`unsold_treatment` behaviour:**

| Value | Effect on unsold allowances |
|---|---|
| `"reserve"` | Held by government; do not re-enter the market in any future year |
| `"cancel"` | Permanently retired; treated identically to `"reserve"` in the current model |
| `"carry_forward"` | Added to next year's `auction_offered` via `carry_forward_in` parameter |

### Price bound fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `price_lower_bound` | float | `0.0` | ≥ 0; must be < `price_upper_bound` | `10.0` | 0 — no price floor |
| `price_upper_bound` | float | `100.0` | > `price_lower_bound` | `200.0` | 100 — serves as upper bracket for Brent's method |

If `price_upper_bound ≤ price_lower_bound`, `ValueError` is raised immediately during config normalisation.

### Banking and borrowing fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `banking_allowed` | bool | `false` | — | `true` | Banking disabled; surpluses must be sold |
| `borrowing_allowed` | bool | `false` | — | `true` | Borrowing disabled; deficits must be bought |
| `borrowing_limit` | float | `0.0` | ≥ 0 | `20.0` | 0 — zero borrow limit (borrowing effectively disabled even if `borrowing_allowed = true`) |

### Expectation fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `expectation_rule` | string | `"next_year_baseline"` | One of four values | `"perfect_foresight"` | Uses `next_year_baseline` |
| `manual_expected_price` | float | `0.0` | ≥ 0 | `35000.0` | 0 — only relevant when rule = `"manual"` |
| `carbon_budget` | float | `0.0` | ≥ 0 | `520.0` | 0 — Hotelling falls back to `total_cap` |

**Allowed `expectation_rule` values:**

| Value | Expected future price | Notes |
|---|---|---|
| `"myopic"` | `0.0` | No intertemporal behaviour; no banking |
| `"next_year_baseline"` | Independent equilibrium price of next year | Default; no circular dependency |
| `"perfect_foresight"` | Actual realised price of next year | Requires fixed-point iteration |
| `"manual"` | `manual_expected_price` value | Used for sensitivity analysis |

### CBAM / EUA price fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `eua_price` | float | `0.0` | ≥ 0 | `72.0` | 0 — no CBAM liability |
| `eua_prices` | object | `{}` | Values are floats; keys are jurisdiction names | `{"EU": 72.0, "UK": 58.0}` | Empty — single-jurisdiction `eua_price` used as fallback |
| `eua_price_ensemble` | object | `{}` | Values are floats; keys are forecast source names | `{"EC": 70.0, "BNEF": 82.0}` | Empty — no ensemble columns generated |

`eua_prices` is used when participants have `cbam_jurisdictions`. The lookup is: per-jurisdiction `reference_price` → `eua_prices[name]` → scalar `eua_price` → 0. When omitted, no multi-jurisdiction CBAM is computed.

`eua_price_ensemble` generates one additional `CBAM Liability (source)` column per entry in participant results, without affecting the base CBAM calculation.

---

## Participant object

```json
{
  "name": "POSCO_Pohang",
  "sector_group": "Steel",
  "sector_allocation_share": 0.60,
  "initial_emissions": 82.0,
  "initial_emissions_trajectory": {
    "start_year": "2026",
    "end_year": "2035",
    "start_value": 82.0,
    "end_value": 58.0
  },
  "free_allocation_ratio": 0.0,
  "penalty_price": 120.0,
  "abatement_type": "linear",
  "max_abatement": 22.0,
  "cost_slope": 6.5,
  "threshold_cost": 0.0,
  "mac_blocks": [],
  "production_output": 20.0,
  "benchmark_emission_intensity": 1.80,
  "cbam_export_share": 0.35,
  "cbam_coverage_ratio": 1.0,
  "cbam_jurisdictions": [],
  "electricity_consumption": 0.0,
  "grid_emission_factor": 0.0,
  "grid_emission_factor_trajectory": {},
  "scope2_cbam_coverage": 0.0,
  "technology_options": []
}
```

### Identification and sector fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `name` | string | `"New Participant"` | Non-empty; unique within year | `"POSCO_Pohang"` | Error: name required |
| `sector_group` | string | `""` | Free text; must match a sector `name` when `sectors[]` is defined | `"Steel"` | No sector grouping; participant excluded from sector aggregates |
| `sector_allocation_share` | float | `0.0` | [0, 1]; participant's share of sector's free pool | `0.60` | 0 — sector-derived allocation not applied |

**Interaction:** `sector_allocation_share` is only used when `sectors[]` is defined at the scenario level and the participant's `sector_group` matches a defined sector. When both conditions are true, the sector pool is split according to shares, overriding `free_allocation_ratio`.

### Emissions and allocation fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `initial_emissions` | float | `0.0` | ≥ 0 | `82.0` | 0 — participant has no emissions |
| `initial_emissions_trajectory` | object | `{}` | Four-key trajectory (`start_year`, `end_year`, `start_value`, `end_value`) | See below | Disabled — per-year `initial_emissions` used |
| `free_allocation_ratio` | float | `0.0` | [0, 1] | `0.90` | 0 — participant buys all allowances at market |
| `penalty_price` | float | `100.0` | > 0; must be ≥ `price_lower_bound` | `120.0` | 100 — all compliance obligations must be met |

**`initial_emissions_trajectory` example:**

```json
"initial_emissions_trajectory": {
  "start_year": "2026",
  "end_year": "2035",
  "start_value": 82.0,
  "end_value": 58.0
}
```

When active, this overrides the per-year `initial_emissions` in every year within the window. The per-year value is still required in the JSON for schema compatibility but is ignored when the trajectory is present. BAU emissions outside the trajectory window use the boundary values (`start_value` before `start_year`, `end_value` after `end_year`).

**`free_allocation_ratio` override priority:** OBA > sector-derived > this field. When `production_output > 0` and `benchmark_emission_intensity > 0`, this field is overridden at build time.

### Abatement model fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `abatement_type` | string | `"linear"` | `"linear"`, `"piecewise"`, `"threshold"` | `"piecewise"` | Defaults to linear |

**Linear MAC** (`abatement_type = "linear"`):

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `max_abatement` | float | `0.0` | ≥ 0; Mt CO₂e | `22.0` | 0 — no abatement possible |
| `cost_slope` | float | `1.0` | > 0; ₩/t per Mt | `6.5` | 1 — very flat MAC |

Total abatement cost formula: $C = \frac{1}{2} \cdot \sigma \cdot a^2$ where $\sigma$ = `cost_slope`.

**Piecewise MAC** (`abatement_type = "piecewise"`):

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `mac_blocks` | array | `[]` | Non-empty; blocks ordered by non-decreasing `marginal_cost` | See below | Error: piecewise requires at least one block |

```json
"mac_blocks": [
  {"amount": 5.0,  "marginal_cost": -10.0},
  {"amount": 6.0,  "marginal_cost": 20.0},
  {"amount": 8.0,  "marginal_cost": 55.0},
  {"amount": 8.0,  "marginal_cost": 110.0}
]
```

Each block: `{"amount": float ≥ 0, "marginal_cost": float}`. Total max abatement = sum of all `amount` values. Blocks must be ordered by non-decreasing `marginal_cost`.

**`amount`** must be ≥ 0. **`marginal_cost` may be negative.** Negative-cost blocks represent "no-regret" abatement measures — efficiency improvements or co-benefit options that are worth taking regardless of the carbon price (e.g. fuel-switching that also reduces fuel costs). These blocks appear first under the non-decreasing ordering rule and are applied before zero- or positive-cost measures. There is no lower bound on `marginal_cost`.

**Threshold MAC** (`abatement_type = "threshold"`):

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `max_abatement` | float | `0.0` | ≥ 0; Mt CO₂e | `15.0` | 0 — no abatement even if threshold is crossed |
| `threshold_cost` | float | `0.0` | ≥ 0; ₩/t | `45.0` | 0 — abatement fires at any positive price |

### OBA (Output-Based Allocation) and activity fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `production_output` | float | `0.0` | ≥ 0; physical units/year (e.g. Mt steel) | `20.0` | 0 — OBA override inactive |
| `benchmark_emission_intensity` | float | `0.0` | ≥ 0; tCO₂/unit | `1.80` | 0 — OBA override inactive |
| `output_price_elasticity` | float | `0.0` | ≥ 0 | `0.3` | 0 — participant activity is inelastic to carbon price |

Both `production_output` and `benchmark_emission_intensity` must be `> 0` for OBA to override `free_allocation_ratio`. The resulting free allocation is:

$$\text{free\_allocation} = \text{benchmark\_emission\_intensity} \times \text{production\_output}$$

See [oba-allocation.md](../../modules/oba/doc/reference.md) for worked examples.

**`output_price_elasticity`** (ε) is the Feedback A price-elastic activity parameter. When the scenario's `reference_carbon_price` is positive and ε > 0, the participant's baseline activity — and hence BAU emissions — contracts as the market price rises above the reference price. The contraction follows:

$$\text{activity}(P) = \text{activity}_0 \times \left(1 - \varepsilon \cdot \frac{P - P_\text{ref}}{P_\text{ref}}\right)$$

Setting ε = 0 (the default) leaves the participant's activity inelastic regardless of the scenario's `reference_carbon_price`. See [feedback-price-elastic-baseline.md](../../modules/elastic_baseline/doc/reference.md).

### CBAM exposure fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `cbam_export_share` | float | `0.0` | [0, 1]; ignored when `cbam_jurisdictions` non-empty | `0.35` | 0 — no CBAM liability |
| `cbam_coverage_ratio` | float | `1.0` | [0, 1]; ignored when `cbam_jurisdictions` non-empty | `1.0` | 1 — full coverage |
| `cbam_jurisdictions` | array | `[]` | Each entry: `{name, export_share, coverage_ratio, [reference_price]}` | See below | Empty — use scalar fields |

When `cbam_jurisdictions` is non-empty, it completely overrides `cbam_export_share` and `cbam_coverage_ratio`. Results appear as per-jurisdiction columns.

```json
"cbam_jurisdictions": [
  {"name": "EU", "export_share": 0.35, "coverage_ratio": 1.0},
  {"name": "UK", "export_share": 0.08, "coverage_ratio": 1.0, "reference_price": 55.0}
]
```

| Sub-field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Jurisdiction name; used as key in `eua_prices` lookup |
| `export_share` | float [0,1] | `0.0` | Fraction of activity exported to this jurisdiction |
| `coverage_ratio` | float [0,1] | `1.0` | Fraction of exported emissions within CBAM scope |
| `reference_price` | float | none | Per-jurisdiction price override; takes precedence over `eua_prices[name]` |

### Scope 2 / indirect emissions fields

| Field | Type | Default | Validation | Example | When omitted |
|---|---|---|---|---|---|
| `electricity_consumption` | float | `0.0` | ≥ 0; MWh | `500000.0` | 0 — no indirect emissions |
| `grid_emission_factor` | float | `0.0` | ≥ 0; tCO₂/MWh | `0.45` | 0 — no indirect emissions |
| `grid_emission_factor_trajectory` | object | `{}` | Four-key trajectory | `{"start_year":"2026","end_year":"2035","start_value":0.45,"end_value":0.25}` | Disabled — per-year `grid_emission_factor` used |
| `scope2_cbam_coverage` | float | `0.0` | [0, 1] | `0.5` | 0 — Scope 2 not in CBAM scope |

**Derived fields:**

```
indirect_emissions = electricity_consumption × grid_emission_factor
scope2_cbam_liability = max(0, eua_price − P*) × indirect_emissions × scope2_cbam_coverage
```

These appear in participant outputs but do not feed back into market clearing.

The `grid_emission_factor_trajectory` follows the same interpolation formula as `initial_emissions_trajectory` and overrides `grid_emission_factor` for years within the trajectory window. This models a progressively decarbonising electricity grid.

### Technology option fields

See the [Technology Options](#technology-option-object) section below and [technology-transition.md](../../modules/endogenous_investment/doc/reference.md).

| Field | Type | Default | Description |
|---|---|---|---|
| `technology_options` | array | `[]` | List of alternative technologies; if non-empty, triggers technology-choice optimisation |

---

## Technology option object

Technology options allow a participant to choose between or blend multiple production modes endogenously.

```json
{
  "name": "Hydrogen DRI",
  "initial_emissions": 70.0,
  "free_allocation_ratio": 0.65,
  "penalty_price": 150.0,
  "abatement_type": "piecewise",
  "max_abatement": 0.0,
  "cost_slope": 1.0,
  "threshold_cost": 0.0,
  "mac_blocks": [
    {"amount": 8,  "marginal_cost": 15},
    {"amount": 10, "marginal_cost": 35},
    {"amount": 8,  "marginal_cost": 70}
  ],
  "fixed_cost": 200.0,
  "max_activity_share": 0.5
}
```

| Field | Type | Default | Validation | Description |
|---|---|---|---|---|
| `name` | string | `"New Technology"` | Non-empty | Technology label |
| `initial_emissions` | float | `0.0` | ≥ 0 | BAU emissions if 100% of activity uses this technology |
| `free_allocation_ratio` | float | `0.0` | [0, 1] | Free allowance share for this technology |
| `penalty_price` | float | `100.0` | > 0 | Fine per uncovered tonne |
| `abatement_type` | string | `"linear"` | One of three values | MAC model for this technology |
| `mac_blocks` | array | `[]` | Required if piecewise | MAC blocks for this technology |
| `max_abatement` | float | `0.0` | ≥ 0 | Used by linear and threshold models |
| `cost_slope` | float | `1.0` | > 0 | Used by linear model |
| `threshold_cost` | float | `0.0` | ≥ 0 | Used by threshold model |
| `fixed_cost` | float | `0.0` | ≥ 0 | One-time adoption cost per year this technology is active (₩M) |
| `max_activity_share` | float | `1.0` | [0, 1] | Maximum fraction of participant activity using this technology |

**Constraint on `max_activity_share`:** Across all technology options, the sum of `max_activity_share` values must be ≥ 1.0. This ensures the participant can cover 100% of activity. Validated at build time.

**When mixed portfolio optimisation triggers:** If any option has `max_activity_share < 1 - 1e-9`, the simulator uses SLSQP to optimise the continuous activity share vector `s = [s₁, ..., sₙ]` subject to `Σsᵢ = 1` and `0 ≤ sᵢ ≤ max_activity_share_i`. Otherwise, each technology is evaluated independently and the cheapest is chosen.

---

## Derived / computed fields

These are not in the JSON config but are computed from config fields during market construction:

| Field | Where computed | Formula |
|---|---|---|
| `free_allocation` | `participant.py` | `initial_emissions × free_allocation_ratio` |
| `max_abatement` (property) | `participant.py` | `initial_emissions × max_abatement_share` |
| `unallocated_allowances` | `market/core.py` | `max(0, total_cap - free_allocs - auction - reserved - cancelled)` |
| `effective_auction_offered` | `market/core.py` | `auction_offered + carry_forward_in` |
| `indirect_emissions` | `market/results.py` | `electricity_consumption × grid_emission_factor` |

## Output / summary columns

These columns appear in the multi-year scenario summary table produced by `scenario_summary()` in `market/results.py` and `solvers/simulation.py`. They are **not** config inputs.

### CCR summary columns

The following three columns are always present in the summary output. They are zero in every year unless `ccr_enabled = true` **and** the scenario has at least two years of history (the first year carries no adjustment).

| Column | Type | Description |
|---|---|---|
| `CCR Cap Adjustment` | float (Mt) | ΔQ_t — Mt added to (positive) or subtracted from (negative) the baseline cap in this period |
| `CCR Emissions Deviation` | float | (e_{t-1} − ē) / ē — fractional deviation of the prior year's aggregate emissions from the reference; 0 when `ccr_reference_emissions = 0` |
| `CCR Cost Deviation` | float | (z_{t-1} − z̄) / z̄ — fractional deviation of the prior year's aggregate abatement cost from the reference; 0 when `ccr_reference_abatement_cost = 0` |

See [carbon-cap-rule.md](../../modules/ccr/doc/reference.md) for interpretation guidance and sign conventions.

---

## JSON ↔ Python object mapping

| JSON path | Python class | Python attribute |
|---|---|---|
| `scenarios[].name` | `CarbonMarket` | `scenario_name` |
| `scenarios[].years[].year` | `CarbonMarket` | `year` |
| `scenarios[].years[].total_cap` | `CarbonMarket` | `total_cap` |
| `scenarios[].years[].auction_offered` | `CarbonMarket` | `auction_offered` |
| `scenarios[].years[].price_lower_bound` | `CarbonMarket` | `price_lower_bound` |
| `scenarios[].years[].price_upper_bound` | `CarbonMarket` | `price_upper_bound` |
| `scenarios[].years[].banking_allowed` | `CarbonMarket` | `banking_allowed` |
| `scenarios[].years[].expectation_rule` | `CarbonMarket` | `expectation_rule` |
| `scenarios[].years[].eua_price` | `CarbonMarket` | `eua_price` (dynamic attribute) |
| `scenarios[].years[].eua_prices` | `CarbonMarket` | `eua_prices` (dynamic attribute) |
| `scenarios[].years[].eua_price_ensemble` | `CarbonMarket` | `eua_price_ensemble` (dynamic attribute) |
| `scenarios[].model_approach` | `CarbonMarket` | `model_approach` (dynamic attribute) |
| `scenarios[].reference_carbon_price` | `CarbonMarket` | `reference_carbon_price` (stamped onto each `MarketParticipant`) |
| `scenarios[].ccr_enabled` | `CarbonMarket` | `ccr_enabled` (dynamic attribute) |
| `scenarios[].ccr_phi_emissions` | `CarbonMarket` | `ccr_phi_emissions` (dynamic attribute) |
| `scenarios[].ccr_phi_abatement_cost` | `CarbonMarket` | `ccr_phi_abatement_cost` (dynamic attribute) |
| `scenarios[].ccr_reference_emissions` | `CarbonMarket` | `ccr_reference_emissions` (dynamic attribute) |
| `scenarios[].ccr_reference_abatement_cost` | `CarbonMarket` | `ccr_reference_abatement_cost` (dynamic attribute) |
| `scenarios[].years[].participants[].name` | `MarketParticipant` | `name` |
| `scenarios[].years[].participants[].initial_emissions` | `MarketParticipant` | `initial_emissions` |
| `scenarios[].years[].participants[].free_allocation_ratio` | `MarketParticipant` | `free_allocation_ratio` |
| `scenarios[].years[].participants[].penalty_price` | `MarketParticipant` | `penalty_price` |
| `scenarios[].years[].participants[].mac_blocks` | `MarketParticipant` | `marginal_abatement_cost` (callable via factory) |
| `scenarios[].years[].participants[].sector_group` | `MarketParticipant` | `sector_group` |
| `scenarios[].years[].participants[].sector_allocation_share` | `MarketParticipant` | `sector_allocation_share` |
| `scenarios[].years[].participants[].production_output` | `MarketParticipant` | `production_output` |
| `scenarios[].years[].participants[].benchmark_emission_intensity` | `MarketParticipant` | `benchmark_emission_intensity` |
| `scenarios[].years[].participants[].output_price_elasticity` | `MarketParticipant` | `output_price_elasticity` |
| `scenarios[].years[].participants[].electricity_consumption` | `MarketParticipant` | `electricity_consumption` |
| `scenarios[].years[].participants[].grid_emission_factor` | `MarketParticipant` | `grid_emission_factor` |
| `scenarios[].years[].participants[].scope2_cbam_coverage` | `MarketParticipant` | `scope2_cbam_coverage` |
| `scenarios[].years[].participants[].cbam_jurisdictions` | `MarketParticipant` | `cbam_jurisdictions` |
| `scenarios[].years[].participants[].technology_options[]` | `MarketParticipant` | `technology_options` (list of `TechnologyOption`) |

---

## Validation summary

### Config-time rules (raised by `normalize_year` and `normalize_participant`)

| Rule | Checked on | Error message pattern |
|---|---|---|
| Missing `scenarios` list | Top-level | `"Config must contain a 'scenarios' list."` |
| Empty scenario name | Scenario | `"Each scenario must have a non-empty name."` |
| Missing or empty `years` | Scenario | `"Scenario '...' must contain a non-empty 'years' list."` |
| Empty year label | Year | `"Each yearly configuration must have a non-empty year label."` |
| Invalid `auction_mode` | Year | `"Year '...' has invalid auction_mode '...'"` |
| `price_upper_bound ≤ price_lower_bound` | Year | `"Year '...' must have price_upper_bound greater than price_lower_bound."` |
| `minimum_bid_coverage` outside [0, 1] | Year | `"Year '...' minimum_bid_coverage must be between 0 and 1."` |
| Negative `auction_reserve_price` | Year | `"Year '...' auction_reserve_price must be non-negative."` |
| Invalid `unsold_treatment` | Year | `"Year '...' unsold_treatment must be one of reserve, cancel, carry_forward."` |
| Invalid `expectation_rule` | Year | `"Year '...' expectation_rule must be one of ..."` |
| Duplicate participant names | Year | `"Year '...' has duplicate participant name(s): [...]."` |
| Penalty price below price floor | Year + Participant | `"Year '...', participant '...': penalty_price (...) is below price_lower_bound (...)"` |
| Empty participant name | Participant | `"Each participant must have a non-empty name."` |
| Invalid `abatement_type` | Participant | `"Participant '...' has invalid abatement_type '...'"` |
| Piecewise with no blocks | Participant | `"Participant '...' piecewise abatement requires mac_blocks."` |
| MAC block `amount` < 0 | Participant | `"Participant '...' MAC block N amount must be non-negative."` |
| MAC blocks out of order | Participant | `"Participant '...' mac_blocks must be ordered by non-decreasing marginal_cost."` (note: `marginal_cost` may be negative; ordering is still non-decreasing) |
| `scope2_cbam_coverage` outside [0, 1] | Participant | `"Participant '...' scope2_cbam_coverage must be between 0 and 1."` |
| `cbam_export_share` outside [0, 1] | Participant | `"Participant '...' cbam_export_share must be between 0 and 1."` |
| `sector_allocation_share` outside [0, 1] | Participant | `"Participant '...' sector_allocation_share must be between 0 and 1."` |
| `output_price_elasticity` < 0 | Participant | `"Participant '...' output_price_elasticity must be non-negative."` |
| Sector group mismatch | Scenario | `"Participant '...' has sector_group '...' which does not match any defined sector."` |

### Build-time rules (raised by `build_market_from_year`)

| Rule | Error message pattern |
|---|---|
| Supply exceeds cap | `"Scenario '...' year '...': allowance supply (...) exceeds total_cap (...). Reduce auction_offered..."` |
| Negative auction supply | `"Scenario '...' year '...' implies negative auction offered."` |
| `max_activity_share` sum < 1 | `"technology max_activity_share values sum to less than 1.0."` |

---

## Minimal valid config

The smallest config that will run without error:

```json
{
  "scenarios": [
    {
      "name": "Minimal",
      "years": [
        {
          "year": "2030",
          "total_cap": 100.0,
          "auction_mode": "explicit",
          "auction_offered": 80.0,
          "price_lower_bound": 0.0,
          "price_upper_bound": 200.0,
          "participants": [
            {
              "name": "Industry A",
              "initial_emissions": 100.0,
              "free_allocation_ratio": 0.2,
              "penalty_price": 150.0,
              "abatement_type": "linear",
              "max_abatement": 20.0,
              "cost_slope": 3.0
            }
          ]
        }
      ]
    }
  ]
}
```

---

## See also

- [Algorithm Overview](../../docs/algorithm-overview.md) — how config flows into the simulation
- [Multi-Year Simulation](multi-year-simulation.md) — banking, borrowing, trajectories
- [Output-Based Allocation](../../modules/oba/doc/reference.md) — OBA fields in depth
- [Sector Configuration](../../modules/sectors/doc/reference.md) — sectors array in depth
- [MAC & Abatement Models](mac-abatement.md) — abatement field details
- [Technology Transition](../../modules/endogenous_investment/doc/reference.md) — technology_options field details
- [Carbon Cap Rule](../../modules/ccr/doc/reference.md) — CCR algorithm, calibration, and output interpretation
- [Price-Elastic Baseline](../../modules/elastic_baseline/doc/reference.md) — Feedback A (`output_price_elasticity`, `reference_carbon_price`)
- [Feedback Coupling](../../docs/feedback-coupling.md) — how CCR and price-elastic baseline interact
