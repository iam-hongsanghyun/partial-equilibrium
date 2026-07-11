# OBA — Reference

*(Moved from `docs/oba-allocation.md` — WO-17 doc fold.)*

## Output-Based Allocation (OBA)

**Files:** `src/ets/config_io/builder.py` (OBA override block), `src/ets/participant/models.py` (participant fields)

Output-Based Allocation is a method of distributing free emission allowances proportional to actual production output rather than as a fixed ratio of historical emissions. It is the dominant allocation methodology in the Korean ETS 4th National Allocation Plan (2026–2030) for trade-exposed, emission-intensive sectors.

---

## Concept: Why OBA?

In a standard ETS, a participant receives free allowances equal to `initial_emissions × free_allocation_ratio`. This is straightforward but creates a **carbon leakage incentive**: firms can reduce their domestic production (and thus their compliance obligation) without any actual abatement. They may offshore production to uncapped regions, exporting both the activity and the emissions.

OBA ties free allowances to **current production output**, not historical emissions. Under OBA:

- If a firm produces more, it receives more free allowances (but must also cover more emissions)
- If a firm reduces production, its free allowances fall proportionally — there is no windfall from downsizing
- If a firm becomes more efficient (emissions per unit fall below the benchmark), it retains a surplus profit

This structure preserves the carbon price signal for abatement decisions while eliminating the incentive to offshore production for compliance reasons — which is why OBA is the preferred allocation mechanism for trade-exposed sectors like steel, cement, and petrochemicals.

---

## Formula

$$\text{free\_allocation}_i = \beta_i \times Y_i$$

where:

| Symbol | Name | Config field | Units |
|---|---|---|---|
| $\beta_i$ | Benchmark emission intensity | `benchmark_emission_intensity` | tCO₂ per unit of product |
| $Y_i$ | Annual production output | `production_output` | Physical units per year |
| $\text{free\_allocation}_i$ | OBA free allowances | Derived | Mt CO₂e |

The benchmark $\beta_i$ represents the emission intensity of the best-performing facilities in the sector — not the average. This incentivises all facilities to approach best-practice performance.

### Conversion to free_allocation_ratio

The model internally stores allocation as a fraction of initial emissions. The OBA-derived ratio is:

$$\text{free\_allocation\_ratio}_i = \min\!\left(1,\; \frac{\beta_i \times Y_i}{E_{0,i}}\right)$$

where $E_{0,i}$ = `initial_emissions`. The `min(1, ...)` prevents the ratio from exceeding 100%, which could happen if a firm's emissions fall below its benchmark entitlement (it would then be a net seller).

---

## Override hierarchy

OBA takes the **highest priority** for determining free allocation. The builder applies overrides in reverse priority order so that OBA always wins when active:

```
Priority 1 (lowest):  per-year free_allocation_ratio in JSON
Priority 2:           sector-derived allocation (when sectors[] defined)
Priority 3 (highest): OBA override (production_output × benchmark_emission_intensity)
```

In code (`src/ets/config_io/builder.py`):

```python
# Step 1: sector derivation (priority 2)
if sectors:
    for participant in participants:
        if sector_group in sector_pools and sector_allocation_share > 0:
            allocated_mt = sector_pool * sector_allocation_share
            participant["free_allocation_ratio"] = min(1.0, allocated_mt / initial_emissions)

# Step 2: OBA override (priority 3 — overwrites whatever is in free_allocation_ratio)
for participant in participants:
    po  = production_output
    bei = benchmark_emission_intensity
    ie  = initial_emissions
    if po > 0 and bei > 0 and ie > 0:
        free_alloc_mt = bei * po
        participant["free_allocation_ratio"] = min(1.0, free_alloc_mt / ie)
```

### When OBA fires

All three conditions must be true for the OBA override to activate:

| Condition | Reason |
|---|---|
| `production_output > 0` | Non-zero output required — zero output would mean zero allocation, which could be intentional |
| `benchmark_emission_intensity > 0` | A benchmark must be set — zero benchmark means no OBA scheme |
| `initial_emissions > 0` | Needed to compute the ratio — zero emissions participant has nothing to cover |

If any condition is false, the OBA override does not fire and `free_allocation_ratio` is used as-is.

---

## Config fields

| Field | Type | Default | Validation | Example | Description |
|---|---|---|---|---|---|
| `production_output` | float | `0.0` | ≥ 0 | `20.0` | Annual physical output (Mt steel/year, Mcm gas/year, etc.) |
| `benchmark_emission_intensity` | float | `0.0` | ≥ 0 | `1.80` | Sector benchmark intensity (tCO₂/unit product) |

**OBA is not active when both are 0.** This allows participants to have both fields in their config without activating OBA — useful when comparing OBA vs ratio allocation in the same config.

---

## Interaction with sector allocation share

When `sectors[]` is defined and a participant has both `sector_allocation_share > 0` and OBA fields set, the OBA allocation **replaces** the sector-derived allocation entirely. The sector-derived value is computed first, then overwritten by the OBA calculation:

```
sector_pool = 200 Mt × (1 − auction_share)   = 170 Mt
sector_allocation_share = 0.60
sector_derived_mt = 170 × 0.60 = 102 Mt
sector_derived_ratio = 102 / 100 = 1.02 → clamped to 1.0

OBA calculation:
  production_output = 20 Mt steel
  benchmark = 1.80 tCO₂/t steel
  oba_mt = 20 × 1.80 = 36 Mt
  oba_ratio = 36 / 100 = 0.36   ← this is what the model uses
```

The OBA result (0.36) overrides the sector-derived result (1.0). This design ensures the most specific allocation method always wins.

---

## Worked example: Korean steel sector (Phase 4)

### Setup

Two integrated blast-furnace steel producers share the steel sector cap. Both have OBA fields set:

| Participant | `initial_emissions` | `production_output` | `benchmark_emission_intensity` |
|---|---|---|---|
| POSCO Pohang | 82.0 Mt CO₂ | 20.0 Mt steel | 1.80 tCO₂/t |
| Hyundai Steel | 24.0 Mt CO₂ | 7.5 Mt steel | 1.80 tCO₂/t |

### OBA calculation

**POSCO Pohang:**

$$\text{free\_allocation} = 1.80 \times 20.0 = 36.0 \text{ Mt CO}_2$$

$$\text{free\_allocation\_ratio} = \frac{36.0}{82.0} = 0.439$$

**Hyundai Steel:**

$$\text{free\_allocation} = 1.80 \times 7.5 = 13.5 \text{ Mt CO}_2$$

$$\text{free\_allocation\_ratio} = \frac{13.5}{24.0} = 0.5625$$

### Interpretation

Both plants receive fewer free allowances than their total emissions — they must abate and/or buy to comply. The benchmark rewards efficient performance: a plant that achieves 1.5 tCO₂/t steel (below the 1.8 benchmark) would receive more free allowances than its residual emissions and become a net seller.

### Benchmark tightening over time

In the K-ETS Phase 4 design, benchmarks decline over the allocation period. In the config, this is represented by using different `benchmark_emission_intensity` values across year configs:

```json
{ "year": "2026", "benchmark_emission_intensity": 2.05 },
{ "year": "2030", "benchmark_emission_intensity": 1.90 },
{ "year": "2035", "benchmark_emission_intensity": 1.70 }
```

As the benchmark tightens, the same output generates fewer free allowances, increasing the compliance obligation and the incentive to abate. See `examples/k_ets_oba_benchmark.json` for a full multi-year OBA scenario.

---

## OBA vs ratio allocation: comparison

| Dimension | Ratio allocation | Output-Based Allocation |
|---|---|---|
| Free allowances | `initial_emissions × ratio` | `benchmark × output` |
| Incentive to reduce output | Yes — less output → less obligation | No — free allocation also falls |
| Incentive to abate | Yes | Yes — emissions below benchmark generate surplus |
| Carbon leakage risk | High for trade-exposed sectors | Low — no reward for offshoring |
| Data requirement | Simple | Requires production output data per year |
| Korean ETS Phase 4 | Sectors not under OBA scheme | Steel, Petrochemical, Cement, etc. |

---

## Korean ETS Phase 4 context

The 4th National Allocation Plan (2026–2030) introduces performance benchmarks for the most emission-intensive and trade-exposed sectors. Key features:

- **Benchmark basis:** Best-performing 10% of facilities in each sector
- **Industries covered:** Iron & steel, non-ferrous metals, petrochemicals, cement, pulp & paper
- **Benchmark tightening:** Benchmarks decline at approximately 1.5–2% per year over the allocation period to reflect sector-level decarbonisation targets
- **Interaction with CBAM:** The EU CBAM (entering full enforcement in 2026) adds an external price on the embedded carbon in Korean exports. Under OBA, higher production does not reduce the compliance obligation per unit — firms cannot reduce their CBAM exposure by cutting domestic production, which aligns OBA with CBAM design intent

To model the Phase 4 design, use `benchmark_emission_intensity` values derived from the official sector benchmarks published by the Ministry of Environment, and update them per year as the plan tightens.

---

## See also

- [Data Model & Config Schema](../../../core/doc/data-model.md) — full field reference for OBA fields
- [Sector Configuration](../../sectors/doc/reference.md) — how OBA interacts with sector-level caps
- [Multi-Year Simulation](../../../core/doc/multi-year-simulation.md) — how BAU trajectories interact with OBA
- `examples/k_ets_oba_benchmark.json` — full working example
