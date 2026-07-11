# Price Controls — Reference

## What this module implements

`pe.features.price_controls` (`modules/price_controls/backend/`) is a
two-door feature carrying the price-bound machinery that does not belong
to any single price-formation module: `plugin.py` (the config door) holds
`apply_price_bound_trajectories` — linear interpolation of
`price_floor_trajectory` / `price_ceiling_trajectory` onto each year's
`price_lower_bound` / `price_upper_bound` — and `DeliveredFloor`, a
`core.protocols.PriceOverlay` that clips the *solved* price up to each
year's `auction_reserve_price` **after** the price-formation fixed point has
converged, never inside it (clip-last; the same operation-order discipline
as the forward-transmission blend-then-clip rule, see
`modules/transmission/doc/reference.md`). `rules.py` (the runtime door)
holds `FloorCancellationRule` — the K-MSR paper's "Rule A": where the
reserve-price floor exceeds the year's solved price, the auction sells
only the demand at the floor and the unsold volume is permanently removed
from circulating supply (`unsold_treatment: "cancel"`), evaluated inside
the banking fixed point on the MSR-adjusted supply. The plain in-clearing
floor branch (price bounded below at zero, the oversupply boundary
condition of static clearing) deliberately stays in the kernel
(`core.market.clearing`) — it is a market-clearing primitive, not a policy
instrument, and is not part of this module.

## Reference papers

- Weitzman, M.L. (1974). "Prices vs. Quantities." *Review of Economic
  Studies*, 41(4), 477–491.

  The foundational result on regulating externalities under uncertainty
  when the regulator cannot perfectly observe firms' abatement costs:
  whether a price instrument (a fixed tax/price) or a quantity instrument
  (a fixed cap) is preferred depends on the relative slopes of the
  marginal-benefit and marginal-cost curves. `price_lower_bound` /
  `price_upper_bound` are this module's quantity-instrument-with-a-price-
  safety-valve hybrid — a cap-and-trade system (the quantity instrument)
  with price bounds bolted on precisely because a pure quantity instrument
  can produce price volatility Weitzman's analysis says is costly when
  marginal abatement costs are steep.

- Roberts, M.J. and Spence, M. (1976). "Effluent charges and licenses
  under uncertainty." *Journal of Public Economics*, 5(3–4), 193–208.

  The direct antecedent of this module's hybrid instrument design: Roberts
  and Spence show that combining a tradeable-license quantity instrument
  with a price floor and a price ceiling ("safety valve") can dominate
  either a pure price or a pure quantity instrument under cost uncertainty
  — exactly the `price_lower_bound` / `price_upper_bound` /
  `auction_reserve_price` combination this module's config door exposes,
  and the `DeliveredFloor` overlay implements as a hard clip rather than an
  unlimited-supply safety valve.

- Fell, H., Burtraw, D., and co-authors on price collars / auction reserve
  prices in emissions trading (author list and exact title not verified in
  this pass — the team's established citation for the applied,
  ETS-specific treatment of price floors/collars, as opposed to the
  Weitzman/Roberts-Spence theoretical foundation above). See
  `modules/ccr/doc/reference.md` and `modules/msr/doc/reference.md` for
  the two other supply-management instruments this module's floor
  composes with (MSR-then-floor ordering; CCR is applied before MSR).

## Where you couldn't verify from code

The Fell/Burtraw et al. citation is named in the assignment as the team's
reference for price collars/reserve prices but its exact title and venue
are not present anywhere in `modules/price_controls/backend/` or in the
moved docs — the module code documents only the mechanism (clip-last,
floor-cancellation) and cross-references the K-MSR working paper's "Rule
A," not this specific paper. Flagged rather than guessed.
