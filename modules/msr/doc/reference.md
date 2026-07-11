# MSR — Reference

## What this module implements

`pe.features.msr` (`modules/msr/backend/`) implements the Market Stability
Reserve as a non-linear supply-adjustment mechanism composed into two
distinct pipelines: `MSRCapRule` (`rules.py`) is a `CapRule` on the
competitive per-year pipeline; `ThresholdMSRSupplyRule` (`rules.py`) is a
`SupplyRule` evaluated inside the banking fixed point. Both read the mutable
`MSRState` (`state.py`) — a reserve pool that withholds allowances from
auction when the aggregate bank exceeds an upper threshold (deflationary
surplus) and releases previously withheld allowances when the bank falls
below a lower threshold (inflationary shortage), with an optional
excess-cancellation rule once the pool exceeds a cancellation threshold.
`decree.py` implements a second, independently-selectable rule family
(`decree_msr_action`, `DecreeSupplyRule`) — a **K-MSR draft-decree**
parameterization, ported from Korea's kets-outlook dashboard (Phase-4
reserve 85.277 Mt, price-band 15,000–25,000 KRW, surplus-ratio band
5%–18%, capped intake/release of 20 Mt/yr) that reads a *price band* and/or
a *bank-surplus ratio* signal from the previous year's realized outcomes
(`hybrid` mode takes the majority of the two signals) rather than the
EU-style bank-threshold rule alone. Both families are gated by
`msr_enabled` / `msr_mode`; the bank-threshold rule's pool always starts
empty on construction, while the decree rule's pool can be pre-funded via
`msr_initial_reserve_mt` — the two reserves are never shared (see
`modules/banking/doc/reference.md` for the K-MSR decree's fit against
observed paper anchors).

## Reference papers

- Kollenberg, S. and Taschini, L. (2016). "The European Union Emissions
  Trading System and the Market Stability Reserve." *(Venue not verified in
  this pass — cite as author/year/title only until confirmed against the
  published source.)*

  The formal analysis of how a reserve mechanism that withholds/releases
  allowances in response to observed banking behaviour reshapes the
  intertemporal price path relative to a fixed cap — the theoretical basis
  for treating the MSR as a rule that acts on *lagged* aggregate bank state
  rather than a market-clearing instrument in its own right (this module's
  `Observables.begin_bank` read, never same-iteration outcomes — the F4
  timing discipline in `core/protocols.py`).

- Perino, G. and Willner, M. (2016). "Procrastinating reform: The impact of
  the market stability reserve on the EU ETS." *Journal of Environmental
  Economics and Management*, 80, 37–52. *(Journal/pages recalled, not
  re-verified against the publisher record — confirm before citing in a
  paper.)*

  Analyzes the MSR's effect on the *timing* of abatement under
  intertemporal trading — directly relevant to why this module's threshold
  rule interacts with the banking window's no-arbitrage search
  (`modules/banking/doc/reference.md`) rather than being evaluable
  independently of it.

- Perino, G., Ritz, R.A. and van Benthem, A.R. (2025). Work on overlapping
  climate policies and the "waterbed effect" in emissions trading. *(Title
  and venue as communicated by the team's reference toolkit; not
  independently verified in this pass — the team should confirm the exact
  title/venue before this citation is used in a paper.)*

  The waterbed-neutrality property this module is regression-tested
  against: under a fixed cap with the bank-threshold rule and no
  cancellation, MSR intake/release is a pure reprofiling of *when*
  allowances circulate, not *how many* — cumulative residual emissions are
  invariant to the rule being on or off (identity D4.1 in
  `modules/endogenous_investment/doc/spec.md`; see also
  `modules/ccr/doc/reference.md` for the analogous CCR/MSR composition
  discipline). A cancellation-enabled MSR (`msr_cancel_excess`) is the one
  configuration that "punctures" the waterbed — see Perino, Ritz & van
  Benthem for why that requires care when policies overlap.

## Note on the K-MSR decree

`msr_mode` values `"price_band"` / `"surplus_rule"` / `"hybrid"` are **not**
from the academic MSR literature above — they are this repository's
parameterization of Korea's own K-ETS Market Stability Reserve reform
(the "K-MSR decree"), sourced from the PLANiT kets-outlook dashboard
(`src/lib/msr.ts`) rather than from a published paper. Treat the decree
mode as a policy-calibration device layered on top of the academic MSR
mechanism, not as a reproduction of Kollenberg & Taschini's or Perino &
Willner's own proposed rule. The default `msr_mode: "bank_threshold"`
is the EU-style rule the two 2016 papers above analyze.

## Where you couldn't verify from code

The exact venue (journal, volume/pages) for Kollenberg & Taschini (2016)
and the exact title/venue for Perino, Ritz & van Benthem (2025) are not
independently confirmed against the published record in this pass — the
module code has no bibliographic references beyond internal doc
cross-links (`docs/blocks-composition-rules.md`, `docs/banking-equilibrium.md`
pre-move). Flagged per the "name author+year+title without inventing the
journal" instruction rather than guessing a venue.
