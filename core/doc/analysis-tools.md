# Core — Analysis Tools Reference

*(Moved from `docs/analysis-tools.md` — WO-17 doc fold.)*

## Analysis Tools

**Files:** `src/ets/analysis/calibration.py`, `src/ets/analysis/batch.py`, `src/ets/analysis/csv_import.py`, `src/ets/analysis/narrative.py`

The simulator ships four analysis tools that extend the core simulation engine. Each is exposed both as a Python function and as an HTTP API endpoint served by `src/ets/web/handlers.py`. This document covers the purpose, algorithm, input/output schema, API reference, and limitations for each tool.

---

## Overview

| Tool | Entry point | API endpoint | Purpose |
|---|---|---|---|
| Model Calibration | `calibrate_slopes()` | `POST /api/calibrate` | Fit MACC slopes to observed KAU prices |
| Batch Runner | `run_batch()` | `POST /api/batch-run` | Cartesian-product parameter sweep |
| CSV Import | `csv_to_config()` | `POST /api/import-csv` | Convert tabular data to simulation config |
| Narrative Summaries | `generate_narrative()` | `POST /api/narrative` | Rule-based plain-language summary |

---

## 1. Model Calibration

### Purpose

The calibration tool fits `abatement_cost_slope` parameters for named participants so that the simulated equilibrium carbon prices closely match a set of observed historical KAU spot prices. This is the primary method for grounding the model in observed market data before projecting forward.

### Algorithm

The calibration minimises the mean squared error (MSE) between modelled and observed prices over all years for which observations are provided:

$$\text{MSE}(\theta) = \frac{1}{T} \sum_{t=1}^{T} \left( P_\text{model}(t;\theta) - P_\text{obs}(t) \right)^2$$

ASCII: MSE(theta) = (1/T) * sum_t ( P_model(t;theta) - P_obs(t) )^2

where:

| Symbol | Description | Units |
|---|---|---|
| $\theta$ | Vector of `abatement_cost_slope` values for calibrated participants | ₩ thousands / (tCO₂e)² |
| $P_\text{model}(t;\theta)$ | Equilibrium carbon price at year $t$ under slopes $\theta$ | ₩ thousands/tCO₂e |
| $P_\text{obs}(t)$ | Observed KAU spot price at year $t$ | ₩ thousands/tCO₂e |
| $T$ | Number of overlapping (model, observed) years | — |

The optimisation uses **Nelder-Mead** simplex search (`scipy.optimize.minimize(method="Nelder-Mead")`). This gradient-free method is appropriate because the objective surface is not smooth — each evaluation calls the full simulation engine, which includes integer-like decisions (banking triggers, floor price binding), making gradient-based methods unreliable.

#### Pseudocode

```python
def _objective(theta):
    cfg = deepcopy(base_config)
    for (participant, slope) in zip(participant_names, theta):
        for year_config in cfg["scenarios"][0]["years"]:
            for p in year_config["participants"]:
                if p["name"] == participant and p["abatement_type"] == "linear":
                    p["abatement_cost_slope"] = max(0.01, slope)

    markets = build_markets_from_config(cfg)
    summary_df, _ = run_simulation(markets)
    P_model = {str(row["Year"]): float(row["Equilibrium Carbon Price"])
               for _, row in summary_df.iterrows()}

    residuals = [P_model.get(yr, 0.0) - P_obs[yr] for yr in obs_years]
    return mean(r**2 for r in residuals)

x0 = initial_slopes  # current config slopes or user-supplied
result = minimize(_objective, x0, method="Nelder-Mead",
                  options={"maxiter": max_iter, "xatol": 0.1, "fatol": 0.01})
```

Convergence tolerances: `xatol=0.1` (slope step size) and `fatol=0.01` (MSE improvement). A slope below 0.01 is clamped to avoid division-by-zero in the MAC formula.

After the optimiser converges, the final simulation is re-run with the best-fit slopes to produce `modelled_prices` for **all** scenario years, not just the observed years.

### Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `base_config` | dict | yes | Full simulation config; `scenarios[0]` is used |
| `observed_prices` | `dict[str, float]` | yes | `{"2021": 14.5, "2022": 17.8, ...}` — year strings to prices |
| `participant_names` | `list[str]` | yes | Names of participants whose slopes to calibrate |
| `initial_slopes` | `list[float]` | no | Starting point; defaults to current values in config |
| `max_iter` | int | no | Nelder-Mead iteration limit; default 500 |

### Outputs

```json
{
  "calibrated_slopes": {
    "POSCO_Pohang": 6.42,
    "Hyundai_Steel": 7.18,
    "LG_Chem_Yeosu": 8.01,
    "Lotte_Chemical": 9.33
  },
  "final_mse": 0.24,
  "iterations": 183,
  "success": true,
  "modelled_prices": {
    "2021": 14.6,
    "2022": 17.7,
    "2023": 19.3,
    "2024": 21.1,
    "2025": 22.4
  },
  "observed_prices": {
    "2021": 14.5,
    "2022": 17.8,
    "2023": 19.2,
    "2024": 21.0,
    "2025": 22.5
  }
}
```

| Field | Type | Description |
|---|---|---|
| `calibrated_slopes` | `dict[str, float]` | Best-fit slope per calibrated participant |
| `final_mse` | float | MSE at convergence (price units squared) |
| `iterations` | int | Number of Nelder-Mead iterations consumed |
| `success` | bool | `true` if Nelder-Mead reported successful convergence |
| `modelled_prices` | `dict[str, float]` | Simulated prices at best-fit slopes for all scenario years |
| `observed_prices` | `dict[str, float]` | Echo of the input observation dict |

### API reference

#### `POST /api/calibrate`

**Request body:**

```json
{
  "config": { "scenarios": [...] },
  "observed_prices": { "2021": 14.5, "2022": 17.8, "2023": 19.2 },
  "participant_names": ["POSCO_Pohang", "Hyundai_Steel"]
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `config` | object | yes | Full simulation config |
| `observed_prices` | object | yes | Keys are year strings; values are prices in the same units as the simulation |
| `participant_names` | array | yes | Must match `name` of linear-MAC participants |
| `initial_slopes` | array | no | Length must match `participant_names` |
| `max_iter` | int | no | Default 500 |

**Response:** JSON object matching the output schema above.

**Example:** See `examples/k_ets_calibration_request.json`.

### Limitations

- Only calibrates participants with `abatement_type: "linear"`. Piecewise and threshold participants are silently skipped.
- Calibrates one scenario at a time (`scenarios[0]`).
- Nelder-Mead is not guaranteed to find the global minimum. Provide reasonable `initial_slopes` when the default (current config values) may be far from the true value.
- If no `observed_prices` year overlaps with the scenario years, the objective is constant and the optimiser returns the initial slopes unchanged.
- The tool only calibrates `abatement_cost_slope`. It does not calibrate `max_abatement`, piecewise blocks, discount rates, or any structural parameter.

---

## 2. Batch / Sensitivity Runner

### Purpose

The batch runner performs a multi-dimensional parameter sweep over any numeric or string fields in the config. It constructs the **Cartesian product** of all sweep axes and runs the full simulation for each combination, collecting year-by-year equilibrium outputs. This is the primary tool for sensitivity analysis and scenario comparison.

### Algorithm

Each sweep axis specifies a **JSON-path** into the config and a list of candidate values. The `[*]` wildcard applies the same value to every element of the parent list simultaneously — enabling a single axis to shift `eua_price` uniformly across all years.

```python
paths  = [s["path"]   for s in sweeps]
values = [s["values"] for s in sweeps]

for combo in itertools.product(*values):
    cfg = deepcopy(base_config)
    for (path, val) in zip(paths, combo):
        cfg = _set_path(cfg, path, val)

    markets = build_markets_from_config(cfg)
    summary_df, _ = run_simulation(markets)
    # record year-by-year outputs for this combo
```

Each run is fully independent with no shared state.

#### JSON-path notation

| Pattern | Meaning |
|---|---|
| `key` | Root-level key in the config dict |
| `a.b.c` | Nested dotted path |
| `a[0]` | Index into a list |
| `a[*].key` | Set `key` on every element of list `a` |
| `a[0].b[*].c` | Set `c` on every element of nested list `b` |

The implementation in `_set_path()` converts `[` and `]` to dots, splits on `.`, and walks the object. When a `*` token is encountered, it recurses inplace over each list element for the remaining path.

### Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `base_config` | dict | yes | Base simulation config; each run deep-copies this |
| `sweeps` | array | yes | List of sweep axis objects (see below) |

**Sweep axis object:**

| Field | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | JSON-path to the field to vary |
| `values` | array | yes | List of values to try on this axis |
| `label` | string | no | Human-readable label; defaults to `path` |

### Outputs

```json
{
  "sweep_axes": [
    {
      "path": "scenarios[0].years[*].eua_price",
      "label": "EUA price (₩ thousands/tCO2)",
      "values": [40, 60, 80, 100, 120]
    }
  ],
  "n_runs": 10,
  "n_errors": 0,
  "runs": [
    {
      "params": {
        "scenarios[0].years[*].eua_price": 40,
        "scenarios[0].price_floor_trajectory.end_value": 40
      },
      "results": [
        {
          "year": "2026",
          "price": 21.3,
          "total_abatement": 14.2,
          "total_compliance_cost": 48600,
          "total_cbam_liability": 12000,
          "total_auction_revenue": 9800
        }
      ],
      "error": null
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `sweep_axes` | array | Echo of sweep specification with labels |
| `n_runs` | int | Total combinations run |
| `n_errors` | int | Runs that raised an exception |
| `runs[].params` | object | `path → value` mapping for this run |
| `runs[].results` | array | Per-year summary rows |
| `runs[].results[].year` | string | Year string |
| `runs[].results[].price` | float | Equilibrium carbon price |
| `runs[].results[].total_abatement` | float | Mt CO₂e |
| `runs[].results[].total_compliance_cost` | float | Monetary units |
| `runs[].results[].total_cbam_liability` | float | Monetary units |
| `runs[].results[].total_auction_revenue` | float | Monetary units |
| `runs[].error` | string or null | Exception message if the run failed |

### API reference

#### `POST /api/batch-run`

**Request body:**

```json
{
  "config": { "scenarios": [...] },
  "sweeps": [
    {
      "path": "scenarios[0].years[*].eua_price",
      "label": "EUA price",
      "values": [40, 60, 80, 100, 120]
    },
    {
      "path": "scenarios[0].price_floor_trajectory.end_value",
      "label": "Price floor 2035",
      "values": [40, 70]
    }
  ]
}
```

**Response:** JSON object matching the output schema above.

**Example:** See `examples/k_ets_batch_eua_sweep.json`. That example sweeps 5 EUA price values × 2 price floor targets = 10 total runs.

### Limitations

- Total runs = product of axis lengths. A 5×5×5 sweep is 125 runs. Large sweeps should be run headlessly, not via the GUI.
- Only one base config is swept per call. To compare two base scenarios, run the batch tool twice.
- The `[*]` wildcard applies the same value to every list element simultaneously. There is no syntax for setting different values per element within a single axis.
- Runs execute sequentially — no parallelism.
- If a path does not exist in the config, `_set_path` raises `KeyError`. Validate paths before submitting large sweeps.

---

## 3. CSV Import

### Purpose

The CSV import tool converts a tabular participant dataset into a valid ETS simulation config dict. This allows analysts to prepare participant data in spreadsheets and import it without writing JSON by hand.

### Expected CSV format

The CSV must have a header row with column names in lowercase `snake_case`. Two columns are required; all others are optional and receive sensible defaults.

| Column | Required | Default | Description |
|---|---|---|---|
| `year` | yes | — | Year string, e.g. `"2026"` |
| `participant_name` | yes | — | Unique participant name within a year |
| `sector_group` | no | `""` | Sector label for grouping |
| `initial_emissions` | no | `0.0` | BAU emissions (Mt CO₂e) |
| `free_allocation_ratio` | no | `0.0` | Free allocation fraction |
| `penalty_price` | no | `100.0` | Penalty (₩ thousands/tCO₂e) |
| `abatement_cost_slope` | no | `5.0` | MACC slope |
| `max_abatement_share` | no | `0.5` | Max abatement as fraction of `initial_emissions` |
| `cbam_export_share` | no | `0.0` | Export share to CBAM jurisdictions |
| `cbam_coverage_ratio` | no | `1.0` | CBAM coverage fraction |
| `electricity_consumption` | no | `0.0` | Indirect electricity (MWh or TJ) |
| `grid_emission_factor` | no | `0.0` | Grid factor (tCO₂e/unit) |
| `scope2_cbam_coverage` | no | `0.0` | Scope 2 CBAM-eligible fraction |
| `production_output` | no | `0.0` | OBA output (physical units/year) |
| `benchmark_emission_intensity` | no | `0.0` | OBA benchmark (tCO₂e/unit) |
| `sector_allocation_share` | no | `0.0` | Share of sector cap |

### Derivation logic

For each year the importer:

1. Groups rows by `year` (string sort order determines year sequence).
2. Creates one participant per row; sets `max_abatement = initial_emissions × max_abatement_share`.
3. Derives `total_cap = sum(initial_emissions) × 0.95`.
4. Derives `auction_offered = sum(initial_emissions) × 0.05`.
5. Applies fixed defaults: `auction_mode="explicit"`, `price_lower_bound=0.0`, `price_upper_bound=200.0`, `banking_allowed=true`, `borrowing_allowed=false`, `expectation_rule="next_year_baseline"`.
6. All participants receive `abatement_type="linear"`.

### Example CSV

```csv
year,participant_name,sector_group,initial_emissions,free_allocation_ratio,abatement_cost_slope
2026,POSCO_Pohang,Steel,82.0,0.95,6.5
2026,Hyundai_Steel,Steel,24.0,0.95,7.0
2026,LG_Chem_Yeosu,Petrochemical,15.0,0.93,8.5
2027,POSCO_Pohang,Steel,80.0,0.94,6.5
2027,Hyundai_Steel,Steel,23.5,0.94,7.0
```

### API reference

#### `POST /api/import-csv`

**Request body:** `multipart/form-data` or `application/x-www-form-urlencoded` with field `csv_text`. Optional field `scenario_name`.

**Response:**

```json
{
  "config": {
    "scenarios": [{
      "name": "Imported Scenario",
      "model_approach": "competitive",
      "years": [
        {
          "year": "2026",
          "total_cap": 115.9,
          "auction_offered": 6.1,
          "participants": [ ... ]
        }
      ]
    }]
  }
}
```

The returned config is ready to submit to `POST /api/run` without modification.

### Error handling

| Condition | Behaviour |
|---|---|
| Missing `year` column value | Row silently skipped |
| Missing `participant_name` value | Row silently skipped |
| Non-numeric value in numeric column | Replaced by column default |
| Empty CSV | Returns config with `"years": []` |
| Duplicate participant names within a year | Both included |

### Limitations

- All imported participants receive `abatement_type="linear"`. Piecewise and threshold models are not supported via CSV.
- The derived `total_cap` (95%) and `auction_offered` (5%) are heuristics. Override these in the returned config before running the simulation for production use.
- No `sectors[]` array is created — sector-pool allocation is not available via CSV import.
- `model_approach` is hard-coded to `"competitive"`. Edit the returned config for Hotelling or Nash scenarios.

---

## 4. Narrative Summaries

### Purpose

The narrative tool converts simulation results into a plain-language summary paragraph, suitable for policy briefs or GUI summary cards. It is rule-based — no language model is involved — making the output deterministic and auditable.

### Algorithm

The generator reads the per-year summary rows and applies a fixed rule set:

```
1. Extract prices[t] from "Equilibrium Carbon Price"
2. Determine direction: rises / falls / remains stable
3. Compute change%  = (P_last - P_first) / P_first × 100
4. Sum cumulatives:
     total_abatement, total_compliance_cost,
     total_cbam_liability, cbam_foregone_revenue,
     total_auction_revenue
5. Compose sentences:
   a. Opening (always):  price direction, first year → last year, change%
   b. Abatement (always): cumulative Mt and compliance cost
   c. CBAM (if total_cbam_liability > 0): exposure + foregone revenue
   d. Auction (if total_auction_revenue > 0): domestic revenue
6. Join with spaces → single paragraph
```

### Columns consumed

| Column key | Description |
|---|---|
| `Equilibrium Carbon Price` | Price direction and change |
| `Total Abatement` | Mt CO₂e, cumulative |
| `Total Compliance Cost` | Monetary, cumulative |
| `Total CBAM Liability` | Monetary; triggers CBAM sentence if > 0 |
| `CBAM Foregone Revenue` | Monetary, within CBAM sentence |
| `Total Auction Revenue` | Monetary; triggers auction sentence if > 0 |

Missing columns are treated as 0.

### Example output

```
Scenario 'K-ETS Phase 4': The equilibrium carbon price rises from ₩18,000/t
in 2026 to ₩44,200/t in 2030 (+145.6% over the period). Cumulative abatement
across the pathway totals 48.3 Mt CO₂e, with total compliance costs of
₩2,340,000. CBAM exposure amounts to ₩890,000 cumulatively. Of this,
₩340,000 represents revenue foregone to the EU — funds that would remain in
Korea if KAU prices equalled EUA levels. Domestic auction revenue totals
₩420,000, available for reinvestment in green transition programmes.
```

### API reference

#### `POST /api/narrative`

**Request body:**

```json
{
  "simulation_results": [
    {
      "year": "2026",
      "summary": {
        "Equilibrium Carbon Price": 18.4,
        "Total Abatement": 8.2,
        "Total Compliance Cost": 480000,
        "Total CBAM Liability": 180000,
        "CBAM Foregone Revenue": 62000,
        "Total Auction Revenue": 84000
      }
    }
  ],
  "scenario_name": "K-ETS Phase 4"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `simulation_results` | array | yes | Per-year result dicts, each with a `"summary"` sub-dict |
| `scenario_name` | string | no | Included in opening sentence when provided |

**Response:**

```json
{
  "narrative": "Scenario 'K-ETS Phase 4': The equilibrium carbon price rises..."
}
```

### Limitations

- Output currency notation is ₩ (Korean Won) regardless of the config's actual currency convention.
- The rule set is fixed — it does not describe per-participant outcomes, technology switching, banking/borrowing behaviour, or sector-level dynamics.
- If `simulation_results` is empty or contains no `"summary"` keys, returns `"No results available."` rather than an error.
- The narrative does not distinguish between binding and non-binding price floors or ceilings.

---

## Combining the tools: a typical workflow

```
1. Prepare participant data in a spreadsheet
       POST /api/import-csv  →  base config

2. Edit the config in the GUI: adjust total_cap, auction_offered,
   add OBA fields, set model_approach

3. Calibrate abatement slopes against historical KAU prices (Phase 1–3)
       POST /api/calibrate  →  calibrated_slopes

4. Inject calibrated_slopes into the base config for the projection period

5. Sweep EUA price scenarios and price floor ambition levels
       POST /api/batch-run  →  runs[]

6. Select the preferred scenario from batch results; run in full detail
       POST /api/run  →  year-by-year results

7. Generate a plain-language paragraph from the preferred-scenario results
       POST /api/narrative  →  report paragraph
```

---

## See also

- [Algorithm Overview](../../docs/algorithm-overview.md) — core simulation algorithms that these tools wrap
- [Data Model & Config Schema](data-model.md) — all config fields referenced by CSV import and batch runner
- [OBA Allocation](../../modules/oba/doc/reference.md) — OBA fields supported in CSV import
- [Multi-Year Simulation](multi-year-simulation.md) — the simulation engine that calibration and batch invoke
- `examples/k_ets_calibration_request.json` — ready-to-POST calibration example
- `examples/k_ets_batch_eua_sweep.json` — ready-to-POST batch sweep example (5 EUA × 2 floor = 10 runs)
