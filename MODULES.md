# Modules index

The manifest tying the vertical slices together (`docs/vertical-slice-plan.md`
§7). One row per module: its feature id (the work-order tag it was peeled
under), backend import path, frontend fragment (where one exists), doc path,
and the papers its `doc/reference.md` cites.

As of this index, the repository is mid-move (`docs/vertical-slice-plan.md`
WO-0..WO-15 landed for the backend; WO-16, the frontend relocation into
`core/frontend/` + `modules/<name>/frontend/`, has **not** landed — frontend
fragments below are still at their pre-move path,
`frontend/src/features/<name>/index.jsx`). `market_links` (D1, recursive
partial equilibrium / gross substitutes) does not exist yet — omitted below
until it lands.

| Module | Feature id | Backend | Frontend | Doc | Papers implemented |
|---|---|---|---|---|---|
| banking | v1 O9 / v2 O13 | `modules/banking/backend` (`pe.features.banking`) | `frontend/src/features/banking/index.jsx` | `modules/banking/doc/reference.md` | Rubin (1996); Schennach (2000) |
| cbam | O7 (two-door) | `modules/cbam/backend` (`pe.features.cbam`) | `frontend/src/features/cbam/index.jsx` | `modules/cbam/doc/reference.md` | Regulation (EU) 2023/956 |
| ccr | v1 O8 / v2 O12 | `modules/ccr/backend` (`pe.features.ccr`) | `frontend/src/features/ccr/index.jsx` | `modules/ccr/doc/reference.md` | Benmir, Roman & Taschini (2025) |
| competitive | v1 O10 / v2 O14 | `modules/competitive/backend` (`pe.features.competitive`) | — (backend-only; no frontend fragment) | `modules/competitive/doc/reference.md` | Montgomery (1972) |
| elastic_baseline | O8 (Feedback Option A) | `modules/elastic_baseline/backend` (`pe.features.elastic_baseline`) | `frontend/src/features/elastic_baseline/index.jsx` | `modules/elastic_baseline/doc/reference.md` | Reduced-form own-price channel (see `docs/feedback-coupling.md` for Option B) |
| endogenous_investment | EI-5 / EI-6 (Phase 1 investment-price feedback) | `modules/endogenous_investment/backend` (`pe.features.endogenous_investment`) | `frontend/src/features/endogenous_investment/index.jsx` | `modules/endogenous_investment/doc/reference.md` (mechanism) + `modules/endogenous_investment/doc/spec.md` (binding spec) | Dixit–Pindyck real-options trigger (`core/doc/... ` investment_trigger analysis); K-MSR paper §6–7 |
| hoarding | O10 (two-door) | `modules/hoarding/backend` (`pe.features.hoarding`) | — (backend-only; no frontend fragment) | `modules/hoarding/doc/reference.md` | Reduced-form device; Salant (1976) as nearest analogue (not a reproduction) |
| hotelling | v1 O11 / v2 O15 | `modules/hotelling/backend` (`pe.features.hotelling`) | `frontend/src/features/hotelling/index.jsx` | `modules/hotelling/doc/reference.md` | Hotelling (1931) |
| msr | v1 O8 / v2 O12 | `modules/msr/backend` (`pe.features.msr`) | `frontend/src/features/msr/index.jsx` | `modules/msr/doc/reference.md` | Kollenberg & Taschini (2016); Perino & Willner (2016); Perino, Ritz & van Benthem (2025); K-MSR decree (Korea parameterization, not academic) |
| nash_cournot | v1 O11 / v2 O15 | `modules/nash_cournot/backend` (`pe.features.nash_cournot`) | `frontend/src/features/nash_cournot/index.jsx` | `modules/nash_cournot/doc/reference.md` | Cournot (1838); Hahn (1984) |
| oba | O9 | `modules/oba/backend` (`pe.features.oba`) | `frontend/src/features/oba/index.jsx` | `modules/oba/doc/reference.md` | Korean ETS 4th National Allocation Plan (regulatory, no academic paper) |
| price_controls | O10 (two-door) | `modules/price_controls/backend` (`pe.features.price_controls`) | `frontend/src/features/price_controls/index.jsx` | `modules/price_controls/doc/reference.md` | Weitzman (1974); Roberts & Spence (1976); Fell, Burtraw et al. (title/venue unverified) |
| sectors | O7 / O9 | `modules/sectors/backend` (`pe.features.sectors`) | `frontend/src/features/sectors/index.jsx` | `modules/sectors/doc/reference.md` | Korean ETS National Allocation Plan (regulatory, no academic paper) |
| transmission | v1 O12 / v2 O16 | `modules/transmission/backend` (`pe.features.transmission`) | `frontend/src/features/transmission/index.jsx` | `modules/transmission/doc/reference.md` | K-MSR working paper (forward-transmission λ); Dixit–Pindyck investment trigger |

## Core (kernel, not a module)

| Slice | Backend | Frontend | Doc |
|---|---|---|---|
| core | `core/backend` (`pe`, `pe.core`, `pe.config_io`, `pe.engine`, `pe.blocks`, `pe.analysis`, `pe.coupling`, `pe.web`, `pe.mcp`) | `frontend/` (pre-WO-16; moves to `core/frontend/` in WO-16) | `core/doc/reference.md` (kernel foundations) + `core/doc/{mac-abatement,market-equilibrium,multi-year-simulation,data-model,analysis-tools}.md` (cross-cutting mechanism docs) |

Core papers: Montgomery (1972); Rubin (1996); Schennach (2000); standard MAC
theory (see `core/doc/reference.md` for how each ties to a specific kernel
module).

## Notes

- **`calibration`** has a frontend fragment (`frontend/src/features/calibration/index.jsx`)
  but is a T4 analysis workflow (`pe.analysis.calibration`), not a `pe.features.*`
  module — it is not listed above and has no `modules/calibration/` slice.
- **`market_links`** (D1) will land as `modules/market_links/backend` =
  `pe.features.market_links` per `docs/vertical-slice-plan.md` §8. Add a row
  here (and a `modules/market_links/doc/reference.md`) when it lands.
- Feature ids marked "v1 Ox / v2 Oy" carry both work-order numbers found in
  the module's own backend docstrings (the plan was renumbered once,
  `docs/feature-modules-plan.md`); ids without a "v1/v2" pair (O7–O10, EI-5/6)
  are from the later "two-door feature" and endogenous-investment work orders
  and were only ever numbered once.
- This index is sourced from `git mv` provenance, module `__init__.py` /
  `plugin.py` docstrings, and `frontend/src/features/registry.js` — not from
  a generated build step. If a module is added, renamed, or gains/loses a
  frontend fragment, update this table by hand (there is no test enforcing
  it, unlike the backend import-isolation ratchet in
  `tests/test_module_isolation.py`).

## See also

- `docs/vertical-slice-plan.md` — the design plan this fold (WO-17) executes.
- `docs/feature-modules-plan.md` — the backend feature-module architecture
  and the O-number work orders cited in the table above.
- `docs/blocks-composition-rules.md` — the F1–F6 / R1–R32 composition rules
  governing how CCR, MSR, price-controls, and hoarding compose inside the
  kernel's fixed points.
