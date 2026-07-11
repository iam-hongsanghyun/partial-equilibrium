# Competitive — Reference

## What this module implements

`pe.features.competitive` (`modules/competitive/backend/solver.py`,
`solve_scenario_path`) is the price-taking baseline every other price-formation
module extends or replaces: each year's carbon price is the Walrasian root
`P*` where aggregate net allowance demand equals effective auction supply
(`core.market.clearing.total_net_demand`, `core.ledger.simulate_path_details`),
found by bracketed Brent root-finding (`scipy.optimize.root_scalar`,
`method="brentq"`). Participants are atomistic price-takers: no participant
believes its own abatement or purchase decision moves the price — that
strategic channel is `nash_cournot`'s, not this module's. Multi-year paths
layer a perfect-foresight fixed point on top of the per-year clearing (solve
→ update expectations → re-solve until price deltas fall below tolerance),
with cap rules (CCR, MSR) injected by the engine-bound entry point and
applied only on the final realized path, never inside the inner convergence
loop (`core.protocols.CapRule`; R29 rule-free inner loop). This module is the
`model_approach: "competitive"` default and the fallback every other
approach (Hotelling, Nash-Cournot) reverts to when its own bracket search
fails.

## Reference papers

- Montgomery, W.D. (1972). "Markets in Licenses and Efficient Pollution
  Control Programs." *Journal of Economic Theory*, 5(3), 395–418.

  The foundational result this module operationalizes: under price-taking
  behaviour, a competitive market in transferable emission licenses
  converges to the cost-minimizing allocation of abatement across sources —
  the Coase-theorem argument specialized to a cap-and-trade instrument.
  Montgomery's proof that *any* initial allocation of licenses yields the
  same efficient equilibrium price and abatement pattern (only the
  distribution of rents differs) is the theoretical license for treating
  `free_allocation_ratio` as a pure wealth transfer that leaves `P*`
  unchanged — a property this module's clearing condition inherits directly
  (the equilibrium condition depends on aggregate net demand, not on how
  free allocation is distributed across participants).

## Notes

The Walrasian/Coase reading is standard textbook treatment of this
mechanism; no further module-specific literature is cited in the existing
codebase docs (`core/doc/market-equilibrium.md` describes the numerical
implementation — Brent bracketing, auction-failure handling, price
bounds — but does not itself cite external sources beyond Montgomery's
underlying result).
