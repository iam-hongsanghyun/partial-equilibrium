# Core — Market Equilibrium Solver Reference

*(Moved from `docs/market-equilibrium.md` — WO-17 doc fold.)*

## Market Equilibrium Solver

**File:** `src/ets/market.py`

The market equilibrium solver finds the carbon price at which total demand for allowances equals total supply. It is the numerical heart of the simulation — called once per year per scenario (or many times during the perfect foresight iteration).

---

## The equilibrium condition

Let:
- `Q` = effective auction supply (allowances offered at auction)
- `D(P)` = total net demand at price `P` = sum of all participants' net allowance purchases

The equilibrium price `P*` satisfies:

```
D(P*) = Q
```

Equivalently, we solve for the root of:

```
f(P) = D(P) - Q = 0
```

---

## Demand function

```python
def total_net_demand(self, carbon_price, bank_balances, expected_future_price):
    return max(0.0, sum(
        participant_outcome(participant, carbon_price, ...).net_allowances_traded
        for participant in self.participants
    ))
```

`net_allowances_traded` per participant:

```
= allowance_buys - allowance_sells
= (residual_emissions + ending_bank - free_allocation - starting_bank)  if positive
= 0                                                                      if negative
```

Negative net demand (a participant has surplus) is capped at zero from the demand function's perspective — sellers simply offer their surplus into the market, which is implicitly absorbed. The function sums only the buying side.

**Why D(P) is monotonically non-increasing:**
- As `P` rises, each participant abates more (MAC curve logic)
- More abatement → lower residual emissions → fewer allowances needed to buy
- Therefore `D(P)` never increases as `P` increases

This monotonicity is the critical property that guarantees Brent's method finds a unique root.

---

## Root-finding: Brent's method

The solver uses `scipy.optimize.root_scalar` with `method='brentq'`.

### Why Brent's method?

| Property | Brent's method |
|---|---|
| Convergence guarantee | Yes, given a valid bracket |
| Convergence speed | Superlinear (faster than bisection) |
| Requires derivative | No |
| Handles discontinuities | Yes (unlike Newton's method) |
| Iterations to converge | Typically 10–20 for ε=1e-8 |

Brent's method combines three techniques, switching between them adaptively:
1. **Bisection** — slow but always makes progress, guarantees bracket shrinks
2. **Secant method** — fast near the root (superlinear convergence)
3. **Inverse quadratic interpolation** — even faster when three good points are known

The method falls back to bisection whenever the other methods would step outside the bracket.

### Bracketing procedure

Before calling Brent's method, the solver must find `[P_low, P_high]` such that `f(P_low) > 0` and `f(P_high) < 0`:

```python
# Step 1: Initial bracket
P_low  = max(price_lower_bound, auction_reserve_price)  # typically 0
P_high = price_upper_bound  if set, else  max_penalty_price × 1.25

f_low  = D(P_low)  - Q     # should be positive (excess demand at low price)
f_high = D(P_high) - Q     # should be negative (demand collapses at high price)

# Step 2: Expand upper bound if bracket not found
expansion_count = 0
while f_low * f_high > 0 and expansion_count < 10:
    P_high *= 2.0
    f_high  = D(P_high) - Q
    expansion_count += 1

if f_low * f_high > 0:
    raise RuntimeError("Could not bracket equilibrium price")
```

**Why the initial bracket usually works:**
- At `P_low = 0`: no abatement, full emissions, very high demand → `f(0) > 0` almost always
- At `P_high = max_penalty × 1.25`: paying the fine is cheaper than buying, demand → 0 → `f(P_high) < 0`

The doubling loop handles unusual configurations where the penalty price is underspecified.

### Root-finding call

```python
solution = root_scalar(
    lambda P: total_net_demand(P, bank_balances, expected_future_price) - Q,
    bracket=[P_low, P_high],
    method="brentq",
)
P_star = solution.root
```

---

## Auction mechanics

Before the root-finding step, the solver handles three special auction conditions:

### Condition 1: Zero supply

```python
if offered <= 0.0:
    # No auction — price is set by free allocation scarcity alone
    P* = _solve_for_supply(target_supply=0.0, ...)
    sold = 0, unsold = 0
```

This occurs when all allowances are given as free allocation and nothing is auctioned. The price is still non-zero if participants need to buy from each other.

### Condition 2: Insufficient demand (auction failure)

The auction may fail to clear if demand at the floor price is less than offered supply:

```python
demand_floor = D(floor_price)   # floor = max(price_lower_bound, reserve_price)

if demand_floor + ε < offered:
    coverage = demand_floor / offered

    if coverage < minimum_bid_coverage:
        # Total auction failure — not enough bids
        sold    = 0
        unsold  = offered
        P*      = _solve_for_supply(target_supply=0.0, ...)  # secondary market only
    else:
        # Partial clearance at floor price
        sold    = demand_floor
        unsold  = offered - demand_floor
        P*      = floor_price
```

`minimum_bid_coverage` (e.g. 0.8 = 80%) is a real auction design parameter used in the EU ETS. If fewer than 80% of offered allowances receive bids, the entire auction is cancelled.

### Condition 3: Normal clearance

```python
# demand at floor ≥ offered → market clears normally
P* = _solve_for_supply(target_supply=offered, P_low=floor_price, P_high=...)
sold   = offered
unsold = 0
```

---

## Unsold allowance treatment

When allowances go unsold (Condition 2 above), they are handled according to the `unsold_treatment` setting:

| Value | Behaviour | Effect on next year |
|---|---|---|
| `"reserve"` | Held in government reserve | Does not re-enter market |
| `"cancel"` | Permanently retired | Reduces effective cap permanently (modelled implicitly) |
| `"carry_forward"` | Added to next year's auction supply | `carry_forward_in` passed to next year's `solve_equilibrium()` |

In `simulation.py`:
```python
carry_forward_allowances = (
    float(equilibrium["unsold_allowances"])
    if market.unsold_treatment == "carry_forward"
    else 0.0
)
```

---

## Price bounds

After finding the raw equilibrium price, bounds are applied:

```
P_effective = max(price_lower_bound, min(price_upper_bound, P*_raw))
```

**Price floor (`price_lower_bound`):**
Models a minimum price guarantee (e.g. the UK ETS minimum carbon price, the California price floor). Even if the market would clear below this level, participants pay at least the floor. Mechanically, the lower bound of the root-finding bracket is set to the floor.

**Price ceiling (`price_upper_bound`):**
Models a safety valve. If costs exceed this level, the government releases additional allowances at the ceiling price (the simplification here: demand above the ceiling is unmet, price is capped). Mechanically, the upper bracket is set to the ceiling.

**Reserve price (`auction_reserve_price`):**
The minimum price at which the government sells at auction. Different from the price floor: the reserve price only applies to the auction itself, not the secondary market. The effective floor used in the solver is `max(price_lower_bound, auction_reserve_price)`.

---

## Supply identity

The `CarbonMarket` constructor validates the supply budget:

```
total_cap = free_allocation + auction_offered + reserved + cancelled + unallocated

where:
  free_allocation = Σ participant.initial_emissions × participant.free_allocation_ratio
  unallocated     = max(0, total_cap - everything_else)   # administrative buffer
```

Violation raises `ValueError` immediately:
```python
if allowance_supply - total_cap > 1e-9:
    raise ValueError("Inconsistent cap setup: supply buckets exceed total_cap")
```

---

## Outputs

The `solve_equilibrium()` method returns:

```python
{
    "price":              P*,           # equilibrium carbon price ($/t)
    "auction_offered":    Q_offered,    # allowances offered at auction
    "auction_sold":       Q_sold,       # allowances actually sold
    "unsold_allowances":  Q_unsold,     # allowances that did not clear
    "coverage_ratio":     Q_bid / Q_offered,  # fraction of offered volume bid on
}
```

`participant_results()` then re-evaluates all participants at `P*` to produce the full per-participant table (abatement, net trade, compliance cost, bank balance, etc.).

---

## See also

- [Algorithm Overview](../../docs/algorithm-overview.md) — where this layer fits in the full simulation
- [MAC & Abatement Models](mac-abatement.md) — how participant demand is computed
- [Multi-Year Simulation](multi-year-simulation.md) — how equilibrium feeds into the next year
