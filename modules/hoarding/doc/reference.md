# Hoarding — Reference

## What this module implements

`pe.features.hoarding` (`modules/hoarding/backend/plugin.py`) is a
minimal, one-class feature: `HoardingInflow` implements
`core.protocols.Friction`, reading a single per-year config field
(`hoarding_inflow`, default 0) and returning it as `h_t` — the volume
withdrawn from that year's circulating supply by structural hoarding. That
is the entire feature; the **host set** — where `h_t` actually acts — lives
in the banking solver (`modules/banking/doc/reference.md`), by deliberate
design (Arbitration outcomes, O10, binding): the static-year supply
reduction `S_t - h_t`, the forced-static window-start constraint (the
banking window never starts at or before a hoarding year), the pre-window
no-arbitrage-prune exemption for hoarding-year transitions, and the
accumulation of hoarded volume into the window budget
(`incoming_bank = B_0 + sum(h_t)`) are all banking-equilibrium math, not
feature behaviour that could be isolated into this module without
splitting one economic mechanism across two places. Unconfigured markets
(`hoarding_inflow` absent, `None`, or `0`) yield `h_t = 0.0` exactly —
attaching this Friction to every banking solve is neutral by construction.

## Reference papers

Hoarding here is a **reduced-form modelling choice**, not a reproduction
of a specific published storage model — be honest about that rather than
retrofitting a citation the code does not actually implement. The
motivating empirical fact (K-MSR paper §3–4) is that Korea's ETS is a
`lambda ≈ 0` market: compliance entities bank against future tightening
without pricing the carry (the observed registry banked-to-certified ratio
rising from 0.03 to 0.17), which is a **documented no-arbitrage violation**
relative to the textbook Rubin/Schennach banking window
(`core/doc/reference.md`), not an optimizing storage decision this module
solves for. `hoarding_inflow` is therefore an *exogenous* schedule, not an
equilibrium object — the participant does not choose `h_t` by comparing
storage returns to alternatives, it is read directly from config.

- Salant, S.W. (1976). "Exhaustible Resources and Industrial Structure: A
  Nash-Cournot Approach to the World Oil Market." *Journal of Political
  Economy*, 84(5), 1079–1093.

  Cited here as the closest published analogue to a "speculative storage"
  reading of hoarding — an agent withholding a resource from the market in
  anticipation of future scarcity or price appreciation — **not** because
  this module implements Salant's Nash-Cournot storage-competition model.
  Salant's agents optimize a storage/extraction decision against strategic
  rivals; this module's `h_t` is an exogenous per-year input with no
  optimizing agent behind it. The honest reading: `hoarding_inflow` is a
  calibration device for representing the *outcome* of a hoarding-like
  friction (whatever its underlying cause — regulatory distrust, thin
  secondary-market liquidity, participant risk aversion) without modelling
  the friction's microfoundations. Treat any future work that endogenizes
  `h_t` from an optimizing storage problem as the point where a Salant-style
  citation would become load-bearing rather than illustrative.

## Where you couldn't verify from code

No academic paper is cited anywhere in `modules/hoarding/backend/` or in
the pre-move docs for a specific hoarding/storage model — the module
docstring is explicit that the mechanism is a reduced-form device
motivated by an empirical observation in the K-MSR working paper, not a
literature reproduction. The Salant citation above is supplied per the
assignment's instruction ("Salant (1976)-style speculative storage if
apt") as the nearest analogue, with the caveat stated plainly rather than
implied.
