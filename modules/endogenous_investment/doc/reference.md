# Endogenous Investment — Reference

*(Moved from `docs/technology-transition.md` — WO-17 doc fold. Companion:
[`spec.md`](spec.md) — the binding investment↔price feedback specification.)*

## Technology Transition & Endogenous Technology Choice

**File:** `src/ets/participant.py` — `optimize_compliance()`, `_optimize_mixed_technology_portfolio()`

Technology transition is the mechanism by which a participant can switch from their current "base technology" to one or more alternatives (e.g. a coal plant adopting renewables, a steel plant switching to hydrogen DRI). The simulator models this endogenously: participants choose the technology mix that minimises their total compliance cost at the prevailing carbon price.

---

## Concept

Each participant has a **base technology** (their current operations) and optionally one or more **technology options** (alternatives they could adopt). Every technology has its own:

- `initial_emissions` — baseline emissions if 100% of activity uses this technology
- `free_allocation_ratio` — share of emissions covered for free
- `penalty_price` — fine for non-compliance
- `marginal_abatement_cost` — MAC model (linear, piecewise, or threshold)
- `fixed_cost` — one-time investment cost to adopt this technology
- `max_activity_share` — maximum fraction of total activity that can use this technology in a given year

The key constraint is `max_activity_share`: if a technology can only cover 50% of a participant's activity, the remaining 50% must use another technology. This naturally models **partial adoption** — realistic for large industrial facilities that cannot fully switch overnight.

---

## Decision modes

The `optimize_compliance()` method selects between three modes based on the configuration:

```python
def optimize_compliance(self, carbon_price, ...):
    technologies = self._available_technologies()
    mixed_enabled = any(option.max_activity_share < 1.0 for option in technologies)

    if len(technologies) == 1:
        # Only one option — use it unconditionally
        return self._optimize_for_technology(technologies[0], ...)

    elif not mixed_enabled:
        # Multiple options but each can cover 100% — pick the cheapest
        return min(
            [self._optimize_for_technology(opt, ...) for opt in technologies],
            key=lambda outcome: outcome.total_cost,
        )

    else:
        # At least one option has max_activity_share < 1 — solve portfolio mix
        return self._optimize_mixed_technology_portfolio(technologies, ...)
```

---

## Mode 1: Single technology (no options)

If no `technology_options` are defined, the participant uses a `_default_technology()` built from their own fields (`initial_emissions`, `free_allocation_ratio`, `penalty_price`, `marginal_abatement_cost`). The optimisation reduces to finding the cost-minimising abatement level for that single technology.

---

## Mode 2: Discrete technology selection (all options can cover 100%)

When all technology options have `max_activity_share = 1.0`, the participant can fully switch to any one of them. The solver evaluates each option independently and selects the cheapest:

```python
outcomes = [_optimize_for_technology(opt, P) for opt in technologies]
best = min(outcomes, key=lambda o: o.total_cost)
```

**Example — Coal plant with three options:**

| Technology | Fixed cost | Abatement potential | Likely winner at... |
|---|---|---|---|
| Base (coal) | $0 | Linear, slope=3 | Low carbon prices |
| Gas + CCS | $50M | Piecewise, lower MAC | Medium carbon prices |
| Renewables | $200M | Very low residual emissions | High carbon prices |

At a low carbon price ($20/t), the fixed cost of switching outweighs the compliance savings → coal wins. At $80/t, renewables' low emissions cost less than buying allowances → renewables win.

---

## Mode 3: Mixed portfolio (partial adoption)

When one or more technologies have `max_activity_share < 1.0`, the participant cannot fully deploy any single alternative. The solver optimises the **share of activity** allocated to each technology.

### Problem formulation

Let `s_k` = activity share for technology `k`. The optimisation is:

```
min_{s}  Σ_k [ fixed_cost_k × s_k  +  abatement_cost_k(a_k(s_k))  ]
        +  P × allowances_purchased  −  P × allowances_sold

subject to:
    Σ_k s_k = 1            (all activity is covered)
    0 ≤ s_k ≤ cap_k        (cap_k = max_activity_share for technology k)
```

**Solver:** `scipy.optimize.minimize` with `method='SLSQP'` (Sequential Least Squares Programming).

### Step-by-step execution

**Step 1: Unit profiles**

For each technology, compute what outcomes look like if it were fully adopted alone (share = 1, banking/borrowing disabled). These "unit profiles" are computed once and reused:

```python
unit_profiles = [
    _optimize_for_technology(opt, P,
        starting_bank_balance=0.0,
        expected_future_price=0.0,
        banking_allowed=False,
        borrowing_allowed=False,
    )
    for opt in technologies
]
```

**Step 2: Aggregate from shares**

The aggregate outcome for a given share vector is:

```python
def aggregate_from_shares(shares):
    residual_emissions = Σ unit.residual_emissions × s_k
    free_allocation    = Σ unit.free_allocation    × s_k
    abatement_cost     = Σ unit.abatement_cost     × s_k
    fixed_cost         = Σ option.fixed_cost       × s_k
    # ... etc

    # Inventory (banking/borrowing) computed on the aggregate
    inventory = _finalize_inventory(residual_emissions, free_allocation, ...)
```

Note: banking/borrowing is handled at the aggregate level, not per-technology. This means the participant makes a single banking decision based on their blended position.

**Step 3: SLSQP optimisation**

```python
result = minimize(
    objective,                       # total compliance cost
    x0 = initial_shares,            # starting guess: proportional to caps
    method = "SLSQP",
    bounds = [(0.0, cap_k) for cap_k in share_caps],
    constraints = [{"type": "eq", "fun": lambda s: sum(s) - 1.0}],
    options = {"maxiter": 400, "ftol": 1e-9},
)
```

**Step 4: Fallback**

If SLSQP fails to converge, the solver tries several candidate portfolios and picks the best:

```python
candidates = [
    initial_shares,            # original proportional guess
    capped_shares / sum,       # max all caps proportionally
    pure_tech_k for each k     # 100% in each single technology
]
best = min(candidates, key=objective)
```

### Example: Steel plant with partial CCS adoption

```
Base technology (blast furnace):
  initial_emissions: 100 Mt,  free_ratio: 0.9,  max_activity_share: 1.0

Technology option (CCS retrofit):
  initial_emissions: 30 Mt,   free_ratio: 0.6,  fixed_cost: $80M,
  max_activity_share: 0.4     ← max 40% of plant activity

At P = $60/t, SLSQP might find:
  s_base = 0.6,  s_CCS = 0.4
  → 60% of activity stays on blast furnace
  → 40% retrofitted with CCS
  → blended residual emissions = 0.6 × (100 - abatement_base) + 0.4 × 30
```

---

## Technology transition pathway (multi-year)

Technology choices are made **independently in each year** — the simulator does not carry a "committed technology" state between years. This means:

- A participant can use 40% CCS in 2030 and 80% CCS in 2035 (no constraint linking the two)
- Fixed costs are paid in full every year the technology is active (it represents per-period adoption overhead, not a one-time capex)

If you want to model **irreversible adoption** (once switched, always switched), set `fixed_cost = 0` from the switch year onward in the multi-year template, or model it as a progressive `max_activity_share` increase in later years.

---

## Outcome labelling

The `technology_name` in results is set as follows:

```python
if len(technology_mix) == 1 and technology_mix[0][1] >= 0.999:
    technology_name = technology_mix[0][0]      # "Renewables"
else:
    mix_label = ", ".join(f"{name} {share*100:.0f}%" for name, share in technology_mix)
    technology_name = f"Mixed Portfolio ({mix_label})"  # "Mixed Portfolio (Coal 60%, CCS 40%)"
```

The frontend's **Technology Pathway** table in the Analysis tab displays this label per participant per year, making it easy to track when transitions happen across the simulation horizon.

---

## Built-in transition archetypes (frontend wizard)

The Editor's **Technology Transition Wizard** (`frontend/src/components/Editor.jsx`) generates technology options using archetype templates:

| Archetype | Technologies offered |
|---|---|
| Steel | Hydrogen DRI, Scrap Electric Arc Furnace, CCS Retrofit |
| Coal power | Renewables + Storage, Gas + CCS, CCS Retrofit |
| Cement | CCS Retrofit, Clinker Substitution |
| Generic industry | CCS Retrofit, Electrification |

The wizard applies emission and cost multipliers based on the selected aggressiveness (conservative / moderate / aggressive) to the participant's existing data, producing realistic technology options without manual entry.

---

## See also

- [MAC & Abatement Models](../../../core/doc/mac-abatement.md) — how each technology's cost is computed
- [Multi-Year Simulation](../../../core/doc/multi-year-simulation.md) — how technology choices evolve across years
- [Algorithm Overview](../../../docs/algorithm-overview.md) — where technology choice fits in the overall flow
