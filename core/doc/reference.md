# Core — Reference

## What the kernel implements

`pe.core` (`core/backend/core/`: `market/`, `participant/`, `ledger.py`,
`costs.py`, `expectations.py`, `defaults.py`, `baseline.py`,
`investment.py`, `protocols.py`, `paths.py`, `logger.py`) is the T0 tier
every feature module and the T3 engine builds on: market primitives
(`CarbonMarket`, allowance-supply identities), the participant
compliance-optimization model, the abatement-cost functions (MAC), the
per-year clearing condition and its root-finder, the multi-year path
ledger, and the `CapRule` / `SupplyRule` / `PriceOverlay` / `Friction`
protocols that let feature modules inject behaviour into the kernel's
fixed points without the kernel importing any feature (T0 imports stdlib,
third-party, and `pe.core` only — never a feature). Every module document
in `modules/*/doc/reference.md` describes a *mechanism layered on* this
kernel; this document is about the kernel's own foundations — the permit-
market theory that makes "a price where net demand equals supply" and "an
intertemporal no-arbitrage condition on a bank" the two organizing
equilibrium concepts the whole engine rests on.

## Reference papers

- Montgomery, W.D. (1972). "Markets in Licenses and Efficient Pollution
  Control Programs." *Journal of Economic Theory*, 5(3), 395–418.

  The foundational efficiency result for the single-year clearing
  condition in `core.market.clearing` (`total_net_demand`, the Brent
  root-find for `P*` such that `D(P*) = Q`): a competitive market in
  transferable emission licenses, with price-taking participants, reaches
  the cost-minimizing allocation of abatement regardless of the initial
  distribution of licenses. This is the theorem that licenses `Coase
  clearing` as a Walrasian price-taking equilibrium — the kernel's per-year
  solver is a direct numerical implementation of Montgomery's equilibrium
  concept, and `modules/competitive/doc/reference.md` documents the
  module that wires it into a multi-year path.

- Rubin, J.D. (1996). "A Model of Intertemporal Emission Trading, Banking,
  and Borrowing." *Journal of Environmental Economics and Management*,
  31(3), 269–286.

  The intertemporal extension of Montgomery's static result: with banking
  and borrowing allowed, Rubin characterizes the equilibrium price path as
  one that grows at the discount rate within a "banking window" and
  satisfies a cumulative budget identity across it — exactly the
  `P_t = P_a * (1+g)^(t-a)` no-arbitrage carry and window-search structure
  documented in `modules/banking/doc/reference.md`. The kernel's
  `core.expectations` module (perfect-foresight iteration, expected-price
  derivation) and `core.ledger.simulate_path_details` are the numerical
  machinery this equilibrium concept requires — a fixed point over
  expectations, not a single root-find.

- Schennach, S.M. (2000). "The Economics of Pollution Permit Banking in the
  Context of Title IV of the 1990 Clean Air Act Amendments." *Journal of
  Environmental Economics and Management*, 40(3), 189–210.

  Extends the Rubin banking framework with the boundary conditions this
  kernel's banking window enforces at both ends (it must not be profitable
  to start the window earlier, nor to extend it later) — the "Rubin/
  Schennach banking equilibrium" the kernel's window search
  (`core/backend/core` primitives feeding `modules/banking/backend/`)
  implements together, cited jointly wherever the banking mechanism is
  documented (`modules/banking/doc/reference.md`,
  `core/doc/multi-year-simulation.md`).

## MAC theory (marginal abatement cost)

The kernel's `core.costs` module (linear, piecewise, and threshold MAC
models; documented in `core/doc/mac-abatement.md`) implements the standard
marginal-abatement-cost-curve framework that underlies every equilibrium
concept above: a rational, price-taking participant abates up to the point
where `MAC(a*) = P` — the same first-order condition Montgomery's
efficiency result and Rubin/Schennach's intertemporal extension both
presuppose about participant behaviour. No single MAC-theory paper is
cited in the kernel code beyond this standard textbook condition; the MAC
curve itself is a calibration input (`cost_slope`, `mac_blocks`,
`threshold_cost`), not a result derived from a specific paper, so no
further citation is claimed here beyond the equilibrium concepts above
that the MAC condition serves.

## How the feature modules relate to the kernel

Every `CapRule` (MSR, CCR), `SupplyRule` (MSR, price-controls
floor-cancellation), `PriceOverlay` (price-controls delivered floor), and
`Friction` (hoarding) implementation lives in a feature module and is
*injected* into the kernel's fixed points by the T3 engine
(`pe.engine`) — the kernel itself never imports a feature, and the
permit-market theory above (Montgomery's static efficiency, Rubin/
Schennach's intertemporal banking) describes the kernel's own equilibrium
concepts, not any one feature's departure from them. See
`docs/vertical-slice-plan.md` §1a for the exact import-name-to-physical-
directory mapping, and each `modules/<name>/doc/reference.md` for how that
module's specific mechanism composes with (or, for MSR/CCR, deliberately
perturbs) the kernel equilibrium documented here.
