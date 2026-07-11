# Hotelling — Reference

## What this module implements

`pe.features.hotelling` (`modules/hotelling/backend/solver.py`,
`solve_hotelling_path`) treats the cumulative emissions budget as an
exhaustible resource and prices allowances off the intertemporal
no-arbitrage condition rather than year-by-year market clearing: the price
path is pinned to `P*(t) = lambda * (1 + r + rho)^(t - t0)`, a shadow price
`lambda` at the base year growing at the effective discount rate
(risk-free rate `r` plus a policy/market risk premium `rho`). `lambda` is
found by bisection so that cumulative residual emissions under the
Hotelling price path exactly exhaust the cumulative carbon budget
(`carbon_budget`, falling back to summed `total_cap` with a warning) — an
arbitrage argument, not a market-clearing one: each year's price is set
directly (`market.participant_results(P_hotelling)`) rather than solved for
via Brent root-finding. If lambda cannot be bracketed, the solver falls
back to the competitive per-year clearing path (`competitive` module) with
the engine's default cap rules. This module is one reading of `lambda = 1`
in the forward-transmission blend documented in
`modules/transmission/doc/reference.md` — the pure inter-temporal price,
as opposed to the pure static (`lambda = 0`) competitive price.

## Reference papers

- Hotelling, H. (1931). "The Economics of Exhaustible Resources." *Journal
  of Political Economy*, 39(2), 137–175.

  The founding no-arbitrage result this module computes directly: the
  owner of an exhaustible stock (here, the cumulative emissions budget) is
  indifferent between extracting/using a unit today or holding it for
  tomorrow only if its price rises at the rate of return available
  elsewhere — Hotelling's `r`. This module's `P*(t) = lambda * (1 + r +
  rho)^(t - t0)` is the discrete-time form of Hotelling's continuous rule
  `dP/dt = r * P`, with the risk premium `rho` added as a calibration
  device for policy uncertainty (cap-tightening ambiguity, MSR rule
  changes, CBAM schedule revisions) that Hotelling's original frictionless
  model does not itself model.

## The banking/budget shadow-price reading

The banking equilibrium solver (`modules/banking/doc/reference.md`) reports
a `Banking Regime` column of `static` or `hotelling` precisely because the
Rubin/Schennach banking window (Rubin 1996; Schennach 2000 — see
`core/doc/reference.md`) *is* a bounded-window instance of this same
no-arbitrage carry: inside the window, `P_t = P_a * (1 + g)^(t - a)` with
`g = discount_rate + risk_premium` is the identical Hotelling growth
condition, applied to the sub-horizon where banking is profitable, rather
than to the full simulation horizon this module bisects over. Reading this
module and the banking window together: the banking solver asks "over what
sub-window does the Hotelling no-arbitrage condition hold, given a finite
starting bank," while this module asks "what shadow price makes the
Hotelling condition hold over the *entire* horizon against the full
cumulative budget."
