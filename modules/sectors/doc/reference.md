# Sectors — Reference

*(Moved from `docs/sector-config.md` — WO-17 doc fold.)*

## Sector Configuration

**Files:** `src/ets/config_io/builder.py` (sector derivation block, `_normalize_sectors`), `src/ets/participant/models.py` (participant fields)

The `sectors[]` array enables sector-level cap decomposition inside a scenario. When defined, the simulator derives `total_cap`, `auction_offered`, and per-participant `free_allocation_ratio` from sector-level trajectories rather than from per-year scalar values. This is the mechanism used to model the K-ETS National Allocation Plan structure, where sectoral caps are set independently and participants receive allowances based on their share of the sector free pool.

---

## Enabling sectors

Add a `sectors` array at the **scenario level** (not inside `years[]`). Each element describes one sector:

```json
{
  "scenarios": [
    {
      "name": "K-ETS Phase 4",
      "model_approach": "competitive",
      "sectors": [
        {
          "name": "Steel",
          "cap_trajectory": { "start_year": "2026", "end_year": "2030",
                               "start_value": 123.0, "end_value": 95.0 },
          "auction_share_trajectory": { "start_year": "2026", "end_year": "2030",
                                        "start_value": 0.03, "end_value": 0.10 }
        },
        {
          "name": "Petrochemical",
          "cap_trajectory": { "start_year": "2026", "end_year": "2030",
                               "start_value": 25.0, "end_value": 18.0 },
          "auction_share_trajectory": { "start_year": "2026", "end_year": "2030",
                                        "start_value": 0.05, "end_value": 0.15 }
        }
      ],
      "years": [ ... ]
    }
  ]
}
```

When `sectors` is absent or empty, the simulator falls back to per-year `total_cap` and `auction_offered` scalars.

---

## Sector object fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | — | Unique sector name; must match `sector_group` values on participants |
| `cap_trajectory` | trajectory object | no | `{}` | Sector total cap in Mt CO₂e, linearly interpolated per year |
| `auction_share_trajectory` | trajectory object | no | `{}` | Fraction of sector cap sold at auction; linearly interpolated |
| `carbon_budget` | float | no | `0.0` | Reserved for future Hotelling integration; not yet used in derivation |

**Trajectory object** (all four keys required if the object is present):

| Key | Type | Description |
|---|---|---|
| `start_year` | string | First year of the interpolation range (e.g. `"2026"`) |
| `end_year` | string | Last year of the interpolation range (e.g. `"2035"`) |
| `start_value` | float | Value at `start_year` |
| `end_value` | float | Value at `end_year` |

Values outside the range are clamped: years before `start_year` receive `start_value`; years after `end_year` receive `end_value`.

---

## Derivation logic

At build time (`build_market_from_year` in `builder.py`), when `sectors` is non-empty the following steps execute **before** participant objects are constructed:

### Step 1 — Interpolate sector cap and auction share

For each sector $s$ at year $t$:

$$\text{cap}_s(t) = \text{interp}\!\left(t,\;\text{cap\_trajectory}_s\right)$$

$$\text{auction\_share}_s(t) = \text{interp}\!\left(t,\;\text{auction\_share\_trajectory}_s\right)$$

$$\text{auction}_s(t) = \text{cap}_s(t) \times \text{auction\_share}_s(t)$$

$$\text{free\_pool}_s(t) = \text{cap}_s(t) - \text{auction}_s(t)$$

If `cap_trajectory` is absent or invalid, the builder falls back to summing `initial_emissions` across all participants whose `sector_group` equals the sector name — a participant-count-weighted fallback.

### Step 2 — Sum to get scenario-level cap and auction

$$\text{total\_cap}(t) = \sum_s \text{cap}_s(t)$$

$$\text{auction\_offered}(t) = \sum_s \text{auction}_s(t)$$

These values **override** the per-year `total_cap` and `auction_offered` scalars in the JSON. The per-year scalars are ignored when sectors are active.

### Step 3 — Derive per-participant free_allocation_ratio

For each participant $i$ with `sector_group = s` and `sector_allocation_share = α_i`:

$$\text{free\_allocation\_ratio}_i(t) = \min\!\left(1,\; \frac{\alpha_i \times \text{free\_pool}_s(t)}{E_{0,i}}\right)$$

where $E_{0,i}$ = `initial_emissions` for participant $i$.

The `min(1, ...)` guard prevents the ratio from exceeding 100%, which would happen if a participant's allocated free allowances exceed their entire initial emissions.

This derived ratio is written into the participant dict before the `MarketParticipant` dataclass is constructed, so all downstream logic (OBA override, compliance optimisation) sees the final value.

### Override priority (full hierarchy)

The builder applies overrides in reverse priority order, so higher-priority rules overwrite lower-priority ones:

```
Priority 1 (lowest):  per-year free_allocation_ratio in JSON
Priority 2:           sector-derived allocation (sectors[] active)
Priority 3:           free_allocation_trajectories[] (per-participant ratio trajectory)
Priority 4 (highest): OBA override (production_output × benchmark_emission_intensity)
```

OBA always wins when its conditions are met. See [OBA Allocation](../../oba/doc/reference.md) for details.

---

## Participant fields for sector allocation

| Field | Type | Default | Validation | Description |
|---|---|---|---|---|
| `sector_group` | string | `""` | Must match a sector `name` in `sectors[]` if sectors are defined | Which sector this participant belongs to |
| `sector_allocation_share` | float | `0.0` | 0 ≤ value ≤ 1 | Share of the sector free pool allocated to this participant |

**Constraint:** The sum of `sector_allocation_share` across all participants in a sector should equal 1.0 to fully exhaust the sector free pool. If the sum is less than 1.0, some free allowances go unallocated. If greater than 1.0, the `min(1, ...)` clamp prevents individual ratios from exceeding 100%, but total implied allocations may exceed the pool — this should be avoided.

A participant with `sector_group` set but `sector_allocation_share = 0` does not receive sector-derived allocation; it retains its per-year `free_allocation_ratio`.

---

## Worked example: two-participant Steel sector

### Setup

The scenario has one sector (`Steel`) and two participants. The Steel sector cap falls from 148 Mt in 2026 to 110 Mt in 2030 with an increasing auction share.

```json
{
  "scenarios": [
    {
      "name": "Steel Sector Example",
      "model_approach": "competitive",
      "sectors": [
        {
          "name": "Steel",
          "cap_trajectory": {
            "start_year": "2026", "end_year": "2030",
            "start_value": 148.0, "end_value": 110.0
          },
          "auction_share_trajectory": {
            "start_year": "2026", "end_year": "2030",
            "start_value": 0.03, "end_value": 0.10
          }
        }
      ],
      "years": [
        {
          "year": "2026",
          "total_cap": 0,
          "auction_offered": 0,
          "auction_mode": "explicit",
          "price_lower_bound": 18.0,
          "price_upper_bound": 150.0,
          "banking_allowed": true,
          "borrowing_allowed": false,
          "borrowing_limit": 0.0,
          "expectation_rule": "next_year_baseline",
          "participants": [
            {
              "name": "POSCO_Pohang",
              "sector_group": "Steel",
              "sector_allocation_share": 0.64,
              "initial_emissions": 82.0,
              "free_allocation_ratio": 0.0,
              "penalty_price": 120.0,
              "abatement_type": "linear",
              "cost_slope": 6.5,
              "max_abatement": 22.0
            },
            {
              "name": "Hyundai_Steel",
              "sector_group": "Steel",
              "sector_allocation_share": 0.36,
              "initial_emissions": 24.0,
              "free_allocation_ratio": 0.0,
              "penalty_price": 120.0,
              "abatement_type": "linear",
              "cost_slope": 7.0,
              "max_abatement": 7.0
            }
          ]
        },
        {
          "year": "2028",
          "total_cap": 0,
          "auction_offered": 0,
          "auction_mode": "explicit",
          "price_lower_bound": 24.0,
          "price_upper_bound": 150.0,
          "banking_allowed": true,
          "borrowing_allowed": false,
          "borrowing_limit": 0.0,
          "expectation_rule": "next_year_baseline",
          "participants": [
            {
              "name": "POSCO_Pohang",
              "sector_group": "Steel",
              "sector_allocation_share": 0.64,
              "initial_emissions": 78.0,
              "free_allocation_ratio": 0.0,
              "penalty_price": 125.0,
              "abatement_type": "linear",
              "cost_slope": 6.5,
              "max_abatement": 22.0
            },
            {
              "name": "Hyundai_Steel",
              "sector_group": "Steel",
              "sector_allocation_share": 0.36,
              "initial_emissions": 23.0,
              "free_allocation_ratio": 0.0,
              "penalty_price": 125.0,
              "abatement_type": "linear",
              "cost_slope": 7.0,
              "max_abatement": 7.0
            }
          ]
        }
      ]
    }
  ]
}
```

### Derivation for year 2026

**Step 1 — Interpolate sector values:**

- `cap(2026) = 148.0 Mt` (at `start_year`, returns `start_value`)
- `auction_share(2026) = 0.03`
- `auction(2026) = 148.0 × 0.03 = 4.44 Mt`
- `free_pool(2026) = 148.0 − 4.44 = 143.56 Mt`

**Step 2 — Scenario totals:**

- `total_cap(2026) = 148.0 Mt` (overrides the `"total_cap": 0` in the year JSON)
- `auction_offered(2026) = 4.44 Mt`

**Step 3 — Per-participant free_allocation_ratio:**

| Participant | `sector_allocation_share` | `initial_emissions` | Allocated Mt | `free_allocation_ratio` |
|---|---|---|---|---|
| POSCO Pohang | 0.64 | 82.0 Mt | 0.64 × 143.56 = 91.88 Mt | min(1, 91.88/82.0) = **1.0** |
| Hyundai Steel | 0.36 | 24.0 Mt | 0.36 × 143.56 = 51.68 Mt | min(1, 51.68/24.0) = **1.0** |

Both participants receive a capped ratio of 1.0 — their full initial emissions are covered by free allowances. With 97% free allocation in 2026 (only 3% auctioned), the sector is in early-phase over-allocation, typical of Phase 4 ramp-up.

### Derivation for year 2028

Linear interpolation at year 2028 (midpoint of 2026–2030 range, fraction = 0.5):

- `cap(2028) = 148.0 + 0.5 × (110.0 − 148.0) = 129.0 Mt`
- `auction_share(2028) = 0.03 + 0.5 × (0.10 − 0.03) = 0.065`
- `auction(2028) = 129.0 × 0.065 = 8.385 Mt`
- `free_pool(2028) = 129.0 − 8.385 = 120.615 Mt`

| Participant | Allocated Mt | `free_allocation_ratio` |
|---|---|---|
| POSCO Pohang | 0.64 × 120.615 = 77.19 Mt | min(1, 77.19/78.0) = **0.990** |
| Hyundai Steel | 0.36 × 120.615 = 43.42 Mt | min(1, 43.42/23.0) = **1.0** |

By 2028 the tightening cap has reduced POSCO's ratio to 0.990 — just below full coverage — while the smaller Hyundai Steel remains over-covered.

---

## Interaction with `cap_trajectory` (scenario-level)

When `sectors[]` is active, the scenario-level `cap_trajectory` is **ignored** for `total_cap` derivation. The sector-derived sum replaces it. However, `price_floor_trajectory` and `price_ceiling_trajectory` at the scenario level still apply normally.

To combine sector-level caps with a scenario-level cap override: remove the `sectors[]` array and use only the scenario-level `cap_trajectory`.

---

## Interaction with OBA

When a participant has both `sector_allocation_share > 0` and OBA fields (`production_output > 0` and `benchmark_emission_intensity > 0`), the OBA allocation takes effect **after** sector derivation. The sector-derived ratio is computed and stored; the OBA override then replaces it before the participant object is finalised:

```
sector_derived_ratio = 0.990    ← from sector pool / initial_emissions
oba_ratio = (1.80 × 20.0) / 82.0 = 0.439   ← benchmark × output / ie
final free_allocation_ratio = 0.439          ← OBA wins
```

The sector derivation is always performed first, but its result is overwritten by OBA. This design allows sectors to set economy-wide caps while OBA governs the per-facility allocation methodology within those caps.

---

## Sub-sector decomposition

Sector names can contain any string, including colon-delimited sub-sector labels such as `"Steel:Integrated"` and `"Steel:EAF"`. This allows modelling sub-technologies or sub-processes within a broader sector while maintaining distinct cap trajectories for each.

```json
"sectors": [
  { "name": "Steel:Integrated",
    "cap_trajectory": { "start_year": "2026", "end_year": "2035",
                        "start_value": 95.0, "end_value": 65.0 },
    "auction_share_trajectory": { "start_year": "2026", "end_year": "2035",
                                   "start_value": 0.03, "end_value": 0.15 } },
  { "name": "Steel:EAF",
    "cap_trajectory": { "start_year": "2026", "end_year": "2035",
                        "start_value": 28.0, "end_value": 20.0 },
    "auction_share_trajectory": { "start_year": "2026", "end_year": "2035",
                                   "start_value": 0.05, "end_value": 0.20 } }
]
```

Participants then set `"sector_group": "Steel:Integrated"` or `"sector_group": "Steel:EAF"` accordingly. The total cap seen by the market is the sum of all sub-sector caps. See `examples/k_ets_subsector_decomposition.json` for a full four-sector example.

---

## Backward compatibility

The `sectors[]` feature is entirely optional. Scenarios without a `sectors` key behave exactly as before — `total_cap` and `auction_offered` are read from the per-year values, and `free_allocation_ratio` is read from each participant's per-year entry (or derived from `free_allocation_trajectories[]`).

Mixing sector-enabled and sector-disabled scenarios in the same config is supported; each scenario is processed independently.

---

## Validation rules

| Rule | Checked at | Error type |
|---|---|---|
| `name` must be non-empty string | Config normalisation | `ValueError` |
| `sector_group` on participant must match a sector `name` (when sectors defined) | Config normalisation | `ValueError` |
| `cap_trajectory` must have all four keys if non-empty | Config normalisation | silently discarded if incomplete |
| `auction_share_trajectory` must have all four keys if non-empty | Config normalisation | silently discarded |
| `auction_offered` must be ≥ 0 after sector derivation | Build time | `ValueError` |
| Supply identity: `free_allocations + auction_offered + reserved + cancelled = total_cap` | Build time | `ValueError` |

---

## See also

- [Data Model & Config Schema](../../../core/doc/data-model.md) — full field reference for `sectors[]`, `sector_group`, `sector_allocation_share`
- [OBA Allocation](../../oba/doc/reference.md) — OBA override that follows sector derivation
- [Multi-Year Simulation](../../../core/doc/multi-year-simulation.md) — how sector caps are re-interpolated each year
- [Algorithm Overview](../../../docs/algorithm-overview.md) — sector derivation within the Layer 3 build pipeline
- `examples/k_ets_subsector_decomposition.json` — four-sector sub-sector decomposition example
