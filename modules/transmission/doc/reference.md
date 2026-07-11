# Transmission — Reference

*(Moved from `docs/forward-transmission.md` — WO-17 doc fold.)*

## Forward transmission (λ) and the Dixit–Pindyck investment trigger

Two additions from the K-MSR working paper (PLANiT, July 2026): the
forward-transmission coefficient λ as a reduced-form price blend
(`src/ets/solvers/transmission.py`), and the irreversible-investment trigger
as a post-processing analysis module
(`src/ets/analysis/investment_trigger.py`).

Both are deliberately **reduced-form**, matching how the paper frames them:
λ blends *prices* (it does not feed back into abatement or investment — that
would leave partial equilibrium; see `docs/feedback-coupling.md`), and the
trigger is a calculation *on* a solved price path, not part of market
clearing.

---

## 1. Forward-transmission λ

The paper formalizes a market's capacity to price future scarcity as
λ ∈ [0, 1]: the realized price is a convex combination of the static
year-by-year clearing price and the inter-temporal (Hotelling) price. The
KRX-estimated value for Korea is λ ≈ 0 (cross-vintage carry ≈ 0 %/yr against
a 5.5 %/yr Hotelling benchmark).

### Mechanism

```
P_blend(t)     = (1 − λ) · P_competitive(t) + λ · P_hotelling(t)
P_delivered(t) = max(P_blend(t), floor_t)
```

Both components are solved with the reserve floor **removed**; the floor
(each year's `auction_reserve_price`) clips the blend **last**. This order is
load-bearing — it is what reproduces the paper's transmission-immunity
result:

- the floor is λ-independent (enforced at the primary auction, outside the
  forward channel), while
- the price *above* the floor varies with λ.

Clipping before blending would deliver `(1−λ)·floor + λ·P_hot > floor` in
floor-bound years — a different (wrong) object.

### Configuration

One scenario-level field, validated to [0, 1]; only applies under
`model_approach: "competitive"`:

```json
{
  "name": "A hold",
  "model_approach": "competitive",
  "discount_rate": 0.055,
  "forward_transmission_lambda": 0.55,
  "years": [ ... ]
}
```

The Hotelling component uses the scenario's `discount_rate` + `risk_premium`
and each year's `carbon_budget` (falling back to `total_cap` with a warning).
The summary output gains four columns: `Forward Transmission Lambda`,
`Static Component Price`, `Hotelling Component Price`, `Reserve Floor Price`.

### Example — the paper's three regimes on K-ETS numbers

`examples/k_msr_lambda_regimes.json` runs rule A (reserve price
22,750 → 97,500 KRW, unsold cancelled) under the paper's three regimes:
relapse (λ→0), hold (λ≈0.55), consolidate (λ→0.9).

```
PYTHONPATH=src .venv/bin/python -m ets.cli --config examples/k_msr_lambda_regimes.json
```

Result (delivered KRW/tCO₂): the regimes differ only while the market clears
above the floor — 2026: 22,750 / 24,211 / 33,254 — and deliver the
**identical** path from 2028 onward (39,361 → 97,500 by 2035, held to 2040).
Steel-threshold activation is 2035 in every regime. This is the paper's
Figure 4 in repository numbers (the paper's v1.0 calibration coincides from
2030 with 2030 = 55,972; this repo's v0.6 calibration gives the same 55,972
in 2030 and binds the floor two years earlier because its early no-policy
path is lower).

### Tests

`tests/test_transmission.py`: endpoint identities (λ=0 ≡ competitive,
λ=1 ≡ Hotelling), the λ=0.5 arithmetic-mean property, blend-then-clip
operation order, λ-invariance of a binding floor, config validation.

---

## 2. Dixit–Pindyck investment trigger

Under uncertainty and irreversibility the firm invests not at the Marshallian
break-even `P_NPV` but at `P* = [β/(β−1)] · P_NPV`, with β > 1 the positive
root of

```
(σ²/2)·β·(β−1) + (r − y)·β − r = 0
```

`ets.analysis.investment_trigger` provides:

| Function | Purpose |
|---|---|
| `beta_positive_root(sigma, r, y)` | closed-form β (σ = 0 → r/(r−y)) |
| `trigger_multiple(sigma, r, y)` | β/(β−1) |
| `credible_floor_multiple(r, y)` | the σ→0 bound r/y (≈1.83 at r=5.5 %, y=3 %) |
| `effective_volatility(sigma0, q)` | reduced-form σ_eff(q) = (1−q)·σ₀ — endpoints per paper A.10; the interior interpolation is a modeling choice, the paper leaves σ_eff(q) unidentified |
| `activation_year(price_path, break_even, multiple)` | first year P(t) ≥ multiple·P_NPV(t); accepts declining threshold schedules |

Paper-worked values (regression-tested in
`tests/test_investment_trigger.py`): σ=0.20 → ≈2.86×; σ=0.30 → ≈3.86×;
σ=0.48 (pooled KAU estimate) → ≈6.4×; full credibility → r/y ≈ 1.83×.

### Usage on a solved path

```python
from ets.analysis.investment_trigger import (
    activation_year, credible_floor_multiple, trigger_multiple,
)
from ets.engine import run_simulation_from_file

summary, _ = run_simulation_from_file("examples/k_msr_lambda_regimes.json")
a = summary[summary["Scenario"].str.contains("relapse")]
path = dict(zip(a["Year"], a["Equilibrium Carbon Price"]))

activation_year(path, 97_500.0, multiple=1.0)                        # '2035' (break-even dating)
activation_year(path, 97_500.0,
                multiple=credible_floor_multiple(0.055, 0.03))       # None — a schedule capped
                                                                     # AT break-even never triggers
trigger_multiple(0.48, 0.055, 0.03)                                  # ≈ 6.4 (no credible floor)
```

The `None` in the second call is the paper's Section 6 point reproduced: even
a fully credible floor leaves the r/y timing wedge, so a reserve-price
schedule must escalate *above* bare break-even for the investment to trigger
by the intended date.

### What this does not do

The engine stays deterministic: σ is an input to the analysis (e.g. the
paper's KAU estimate 0.48), not a model output; and the partial-credibility
interior of σ_eff(q) is an illustrative interpolation, not the paper's
optimal-stopping treatment (which the paper itself defers to future work).
