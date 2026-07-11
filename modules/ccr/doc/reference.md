# CCR — Reference

*(Moved from `docs/carbon-cap-rule.md` — WO-17 doc fold.)*

## Carbon Cap Rule (CCR)

**Files:** `src/ets/solvers/ccr.py` (logic), `src/ets/ccr.py` (shim), `src/ets/solvers/simulation.py` (integration)
**Enabled by:** `ccr_enabled: true`
**Example:** [`examples/benmir_ccr_carbon_cap_rule.json`](../../../examples/benmir_ccr_carbon_cap_rule.json)

The CCR is a rule-based **adaptive cap** — the cap-and-trade analogue of a Taylor
rule in monetary policy. Instead of a fixed per-period cap, the regulator adjusts
the quantity of permits issued each period in response to how far two observable
drivers have drifted from their steady-state (reference) levels: **aggregate
emissions** and **aggregate abatement cost**.

## Reference

Benmir, G., Roman, J. and Taschini, L. (2025). *Weitzman meets Taylor: EU
allowance price drivers and carbon cap rules.* Grantham Research Institute on
Climate Change and the Environment, Working Paper No. 421, LSE.

The paper introduces the CCR as a practical alternative to setting the cap at the
social cost of carbon. It reports that an optimally-tuned CCR cuts EU-ETS
allowance-price volatility by ≈55% and welfare losses by ≈40% relative to the
fixed Phase-3 cap.

## The rule

$$
Q_t \;=\; \overline{Q}
        \;+\; \phi_e \,\frac{e_t - \bar e}{\bar e}
        \;+\; \phi_z \,\frac{z_t - \bar z}{\bar z}
$$

ASCII fallback:

```
Q_t = Qbar + phi_e * (e_t - ebar) / ebar + phi_z * (z_t - zbar) / zbar
```

| symbol | meaning | units | config field |
|--------|---------|-------|--------------|
| `Q_t`  | permits issued in period *t* | Mt CO₂e | (output) |
| `Qbar` | baseline (steady-state) cap | Mt CO₂e | `total_cap` / `cap_trajectory` |
| `e_t`  | observed aggregate emissions | Mt CO₂e | (realised) |
| `ebar` | reference (steady-state) emissions | Mt CO₂e | `ccr_reference_emissions` |
| `z_t`  | observed aggregate abatement cost | currency | (realised) |
| `zbar` | reference (steady-state) abatement cost | currency | `ccr_reference_abatement_cost` |
| `phi_e`| cap sensitivity to the emissions gap | Mt CO₂e | `ccr_phi_emissions` |
| `phi_z`| cap sensitivity to the abatement-cost gap | Mt CO₂e | `ccr_phi_abatement_cost` |

Because the two gap terms are dimensionless fractions, `phi_e` and `phi_z` carry
the **units of the cap** (Mt CO₂e per unit fractional deviation).

### Sign convention (the paper's optimum)

- **`phi_z > 0`** — when abatement costs run **above** reference, **issue more
  permits** to relieve cost pressure and damp the price spike.
- **`phi_e < 0`** — when emissions run **above** reference, **issue fewer
  permits** to keep emissions on track.

The paper finds the rule responds much more strongly to abatement-cost deviations
than to emissions deviations (`|phi_z| ≫ |phi_e|`).

## How it is implemented here

`e_t` and `z_t` are **outcomes** of market clearing, so they are not known when
the period-*t* cap must be set. Mirroring how the MSR reads the
beginning-of-period bank, the CCR conditions period *t*'s cap on the **previously
realised** (period *t−1*) emissions and abatement cost:

- aggregate emissions ← `sum(participant_df["Residual Emissions"])`
- aggregate abatement cost ← `sum(participant_df["Abatement Cost"])`

The computed adjustment `ΔQ_t = Q_t − Qbar` is injected as additional permit
supply before competitive clearing (exactly the mechanism used for the MSR's
withhold/release), so the market clears against the rule-adjusted cap.

Consequences of the one-period information lag:

- The **first period carries no adjustment** (no history yet): `Q_0 = Qbar`.
- A reference value of `0` **disables that term** (the fractional gap is
  undefined), so a scenario can drive the cap off emissions alone, abatement cost
  alone, or both.
- The rule dampens the **sustained** phase of a (persistent / AR(1)) shock rather
  than the impulse year itself.

The CCR runs in the **competitive** model approach — the path where the cap maps
to auction supply and on to the clearing price. It is **not** applied during the
inner perfect-foresight price-convergence loop, only on the final realised path
(same treatment as the MSR).

## Configuration

All fields are scenario-level and fully user-overridable. Defaults leave the CCR
disabled and neutral — **no values are hardcoded** in the solver.

| field | type | default | meaning |
|-------|------|---------|---------|
| `ccr_enabled` | bool | `false` | Enable the Carbon Cap Rule |
| `ccr_phi_emissions` | float | `0.0` | φ_e — Mt cap change per unit emissions gap (use a **negative** value to tighten on overshoot) |
| `ccr_phi_abatement_cost` | float | `0.0` | φ_z — Mt cap change per unit abatement-cost gap (use a **positive** value to loosen when costs run hot) |
| `ccr_reference_emissions` | float | `0.0` | ē — reference emissions (Mt); `0` disables the emissions term |
| `ccr_reference_abatement_cost` | float | `0.0` | z̄ — reference abatement cost; `0` disables the cost term |

> **Calibrating `phi`.** The paper's optimal coefficients (`phi_z ≈ +0.1853`,
> `phi_e ≈ -0.0027`) are expressed in the paper's *normalised* model units. Do not
> copy them verbatim — rescale to the per-period cap of your scenario. The example
> scenario uses `phi_e = -30`, `phi_z = 15` against a ~430–500 Mt cap.

## Output columns

When the CCR is enabled, each year's summary row reports:

| column | meaning |
|--------|---------|
| `CCR Cap Adjustment` | ΔQ_t added to permit supply this year (Mt) |
| `CCR Emissions Deviation` | (e_{t-1} − ē) / ē |
| `CCR Cost Deviation` | (z_{t-1} − z̄) / z̄ |

## Worked example

[`examples/benmir_ccr_carbon_cap_rule.json`](../../../examples/benmir_ccr_carbon_cap_rule.json)
compares a fixed cap and a CCR under an identical market hit by a **persistent**
emissions + abatement-cost shock from 2028 onward. The CCR loosens the cap by
~+29/+24 Mt while abatement costs run hot, holding the post-shock price peak to
≈110 (vs ≈128 under the fixed cap) and cutting the carbon-price standard deviation
by ~27%.

## Relationship to the MSR

| | MSR (Kollenberg & Taschini 2019) | CCR (Benmir et al. 2025) |
|--|----------------------------------|--------------------------|
| Signal | aggregate **bank** size | **emissions** + **abatement-cost** gaps |
| Action | withhold / release auction volume into a reserve pool | shift the per-period cap quantity |
| Trigger | discrete thresholds | continuous Taylor-rule response |
| Cap | preserved (reserve, optional cancellation) | actively re-set each period |

Both are supply-management mechanisms; they can be reasoned about together but are
configured independently (`msr_enabled` vs `ccr_enabled`).
