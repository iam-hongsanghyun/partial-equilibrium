# CBAM — Reference

## What this module implements

`pe.features.cbam` (`modules/cbam/backend/plugin.py`) has no runtime
solver — it is a **post-clearing reporting overlay**, the door rule stated
explicitly in the module docstring: "CBAM has no runtime module today — it
is reporting-only ... CBAM liability is a post-clearing diagnostic that
reads the solved KAU price and the external EUA reference price, never a
price channel (F6)." Three reporters compute, from the already-solved
allowance price, per-participant and aggregate columns: `gap = max(0,
P_EUA - P_KAU)` (or, under `cbam_jurisdictions`, a liability-weighted
average gap across named jurisdictions), `CBAM Liability = gap *
residual_emissions * export_share * coverage_ratio`, an analogous Scope-2
(indirect, electricity-based) liability, and revenue-accounting summary
columns (`Domestic Retained Revenue`, `CBAM Foregone Revenue`, `Potential
Revenue if KAU=EUA`). Because CBAM never feeds back into `total_net_demand`
or any price-formation module, enabling it cannot change a single solved
price or golden baseline — it only adds diagnostic columns to an
already-determined outcome. This is a deliberate scope decision (feature
verdicts v2, Arbitration outcomes O7), not an oversight: a price-coupled
CBAM (where the KAU-EUA gap feeds back into domestic abatement incentives)
would be a different, unbuilt feature.

## Reference papers

- Regulation (EU) 2023/956 of the European Parliament and of the Council
  of 10 May 2023 establishing a carbon border adjustment mechanism.
  *Official Journal of the European Union*, L 130, 16.5.2023.

  The regulatory instrument this module reports against: CBAM requires
  importers of covered goods (steel, cement, aluminium, fertilisers,
  hydrogen, electricity) into the EU to purchase certificates equal to the
  embedded carbon in those goods, priced at the weekly average EU ETS
  auction price, net of any carbon price already paid in the country of
  origin. This module's `gap = max(0, P_EUA - P_KAU)` is precisely that
  netting rule — a Korean (KAU) exporter's CBAM exposure is the shortfall
  between the EU allowance price and whatever domestic carbon price it
  already paid, not the full EU price. The regulation's phased
  implementation (transitional reporting-only period from October 2023,
  full financial liability from 2026) is why this module's own framing —
  "reporting-only, no price channel" — mirrors the regulation's own
  reporting-first design, though the module's F6 scope decision is an
  independent modelling choice, not a claim that the *real* CBAM will
  never gain a domestic feedback channel.

## Notes

`cbam_jurisdictions`, the EUA-price ensemble (`eua_price_ensemble`), and
Scope-2 coverage are this repository's extensions for sensitivity analysis
across multiple export destinations and price scenarios — they are not
part of the EU regulation's own single-jurisdiction design, which only
concerns imports *into* the EU. Interaction with OBA
(`modules/oba/doc/reference.md`) is real-world load-bearing: the OBA doc
notes that under output-based allocation, higher production does not
reduce a firm's compliance obligation per unit, so a firm cannot lower its
CBAM exposure by cutting domestic production — the two mechanisms are
designed (in the actual policy, and thus in this repository) to be
mutually reinforcing rather than to interact through this module's code.
