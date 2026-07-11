# K-ETS Manual

Full reference manual for the K-ETS partial-equilibrium simulator. For the
one-page pitch, install command, and smallest usage example, see
[README.md](README.md). For the feature-module architecture and its
execution history, see [docs/feature-modules-plan.md](docs/feature-modules-plan.md).
For the block-graph compiler and its API contract, see
[docs/blocks-graph-plan.md](docs/blocks-graph-plan.md).

---

## Launchers

Three entry points, each a `.command` script at the repo root. All three
sync the `uv`-pinned environment (falling back to a `.venv` + `requirements.txt`
install if `uv` is not on `PATH`) and then launch the same WSGI application
on a different port with a different `?mode=` query parameter — the mode is
read once, client-side, in `frontend/src/main.jsx`, and picks which React
root to mount.

| Launcher | Purpose | Port (env override) | URL it opens |
|---|---|---|---|
| `run.command` | Everything-tool — the full app, every feature module enabled, every tab (Model / Validation / Analysis / Scenario / Guide) | `8765` | `http://127.0.0.1:8765/` |
| `configure.command` | Model Composer — admin GUI for drawing block graphs and saving them as models | `8801` (`ETS_COMPOSER_PORT`) | `http://127.0.0.1:8801/?mode=composer` |
| `pe.command` | PE shell — model list first; selecting a model scopes the UI to only the feature modules that model uses | `8802` (`ETS_PE_PORT`) | `http://127.0.0.1:8802/?mode=pe` |

```bash
./run.command          # everything-tool, port 8765
./configure.command     # composer admin, port 8801
./pe.command            # model-scoped shell, port 8802
```

Run any two (or all three) at once — they bind different ports and share
the same `user-scenarios/` registry on disk, so a model saved from
`configure.command` shows up immediately in both `run.command`'s template
picker and `pe.command`'s model list.

`run.command` has no `?mode=` argument — it always mounts the default shell
(`enabledFeatures=null`, i.e. every registry feature active). It also
accepts the same CLI subcommands as `python -m ets.cli` (`sample <name>`,
`samples` to list bundled sample modes, or arbitrary `ets.cli` flags passed
through).

`run.command`, `configure.command`, and `pe.command` all invoke the same
deprecated `ets_framework.py` shim under the hood (kept for the existing
launcher scripts and CI; it emits a `DeprecationWarning` and delegates to
`ets.cli.main`). Calling `ets.cli` directly (`uv run python -m ets.cli --gui`)
works identically and is warning-clean.

---

## Composing models

`configure.command` opens the Model Composer — a node-graph editor
(`frontend/src/composer/Composer.jsx`, built on React Flow) for assembling a
scenario from blocks instead of hand-writing JSON. Walkthrough:

1. **Palette → canvas.** The left-hand palette lists every block in
   `GET /api/blocks` (participants, `carbon_market`, one price-formation
   block per approach, policy blocks — MSR, CCR, price floor/ceiling,
   cancellation, OBA, CBAM, hoarding — plus expectations and analysis
   blocks). Drag a block onto the canvas to create a node.
2. **Connect.** Draw edges between node ports — e.g. a `participant` node's
   `compliance` output to a `carbon_market` node's `participants` input, or
   a `rubin_schennach_banking` node's `price_formation` output to the
   market's `price_formation` input (cardinality exactly one per market).
   `isValidConnection` rejects port-type mismatches at draw time.
3. **Params.** Selecting a node opens the param panel
   (`ParamPanel.jsx`) on the right, rendering one field per `ParamSpec` the
   catalogue declares for that block (type, unit, min/max/enum) — no block
   knowledge is hardcoded in the frontend.
4. **Validate.** The **Validate** button calls `POST /api/graph/validate`,
   which runs the structural rules (R1–R32, `docs/blocks-composition-rules.md`)
   against the drawn graph — dangling edges, cardinality violations, and
   block constraints (e.g. `kmsr_decree` `requires` `rubin_schennach_banking`;
   `msr_bank_threshold` `excludes` `kmsr_decree`). Errors and warnings list
   under the canvas; clicking one highlights the offending node or edge.
5. **Run.** **Run** calls `POST /api/graph/run`: validate, compile the graph
   to a scenario-config dict (`blocks/compile.py:compile_graph`), and solve
   it — the same dashboard payload `/api/run` returns, rendered inline below
   the canvas so you can inspect results without leaving the composer.
6. **Save model.** **Save model** calls `POST /api/graph/save-model` with a
   display name. This persists two files under `user-scenarios/`: the
   compiled scenario config (`<slug>.json`, runnable by any endpoint that
   takes a config) and the source graph (`<slug>.graph.json`, read back so
   the model reopens exactly as drawn). The saved model appears as
   `user_<slug>` in `GET /api/templates` — immediately selectable from
   `run.command`'s template picker and from `pe.command`'s "Your models"
   list.

Other toolbar actions: **Load example** decompiles an `examples/*.json`
onto the canvas (`GET /api/graph/from-template`); **Export config** compiles
without running (`POST /api/graph/compile`) and downloads the resulting
JSON.

---

## Model manifest

`GET /api/model-manifest?id=<template_id>` and `POST /api/model-manifest`
(body: a scenario-config dict) both return the **manifest** of a model — the
set of feature modules, blocks, and price-formation approaches it actually
exercises (`ets.blocks.manifest.derive_manifest`). `pe.command`'s shell calls
this once per model selection to decide which feature-module panels to
render, so a model that never touches MSR never shows an MSR panel.

The manifest is derived two ways, combined:

- **From the compiled block graph** (`ets.blocks.decompile.graph_from_config`):
  every synthesised node maps to exactly one `BlockSpec`, and every
  `BlockSpec` declares exactly one `feature` — so `{node.block for node in
  graph.nodes}` mapped through the catalogue covers most of the signal.
- **From direct detectors** (`ets.blocks.manifest._direct_detectors`) for
  config shapes the decompiler never turns into a drawn node: `oba`
  (participant has positive `production_output`, `benchmark_emission_intensity`,
  and `initial_emissions`), `sectors` (a non-empty `sectors[]` table, or any
  participant tagged with `sector_group`), and `policy_events` (a non-empty
  policy-event timeline — splicing is engine composition, not a drawable
  block).

`"features"` always includes `"core"`. Example — `derive_manifest` on
`examples/k_ets_oba_benchmark.json`:

```json
{
  "features": ["cbam", "competitive", "core", "oba", "price_controls", "sectors"],
  "blocks": ["cap_path", "carbon_market", "cbam", "competitive_clearing", "participant", "price_ceiling", "price_floor"],
  "approach": ["competitive"]
}
```

`oba` and `sectors` are present even though the graph draws no `oba` or
`sector` node — both are direct-detector hits (a benchmark-intensity
participant with a `sector_group` tag).

Adding a new mechanism end-to-end — including where its manifest detector
goes — is documented as a six-step checklist in
[docs/feature-modules-plan.md, "Status: EXECUTED"](docs/feature-modules-plan.md).

---

## MCP composer (AI-guided setup)

`src/ets/mcp` exposes the same block-graph composer as an
[MCP](https://modelcontextprotocol.io) server, so an AI assistant (Claude
Code, Claude Desktop, or any other MCP client) can hold a conversation with
you and build a scenario graph turn by turn instead of you drawing it in
`configure.command` or writing JSON by hand. It is a T5 app, same tier as
`ets.web`/`ets.cli`, wired to the exact same `ets.blocks` catalogue/
validator/compiler and the same `user-scenarios/` registry
(`ets.model_store`) the web composer uses — a model saved from either place
shows up immediately in both.

### Registration

Install the `mcp` optional-dependency group:

```bash
uv sync --extra mcp        # or --all-extras
```

The repo-root `.mcp.json` already registers the server for Claude Code (and
any other client that reads that file):

```json
{
  "mcpServers": {
    "ets-composer": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "python", "-m", "ets.mcp"]
    }
  }
}
```

For Claude Desktop, add the same `"ets-composer"` entry (with an absolute
`cwd` pointing at this repo) to its own `claude_desktop_config.json`. Run it
by hand for a manual check — it speaks MCP over stdio, so a plain
`python -m ets.mcp` blocks waiting for a client:

```bash
uv run --extra mcp python -m ets.mcp
```

### Tools

| Tool | What it does |
|---|---|
| `list_models()` | Examples + registry models, with feature/approach chips and a one-line description. |
| `list_blocks(category=None)` / `describe_block(block_id)` | The block catalogue — params (type/default/unit/bounds), ports, `requires`/`excludes`. |
| `new_graph(template_id=None)` | A blank minimum-viable graph, or a model from `list_models()` loaded onto the (conversational) canvas. |
| `add_block(graph, block_id, params=None, target_market=None, replace_existing=False)` | Adds a node and its obvious edge into a market (port-kind matched, e.g. a policy block → `policies`); a second singular-port block (e.g. price formation) is wired anyway by default so `check()` surfaces the conflict, unless `replace_existing=True`. |
| `set_params(graph, node_id, params)` / `remove_node(graph, node_id)` | Edit or delete a node; `set_params` with a `None` value clears that param back to its default. |
| `check(graph)` | `validate_graph`'s issues (rules R1–R32) plus `next_steps` — a plain-language, typically yes/no-phrased suggestion for every ERROR, derived from `docs/blocks-composition-rules.md` §4. |
| `run_model(graph, scenario=None)` | Compiles and runs the graph; returns a compact per-scenario/per-year summary (price, auction sold/offered, abatement, bank/MSR/CCR columns when active) — never a raw DataFrame. |
| `save_model(graph, name)` | Persists the graph to the shared registry; the returned id shows up in both `run.command`'s template picker and `pe.command`'s model list. |

Every mutating tool is stateless: it takes the current graph JSON and
returns the updated graph plus fresh `issues` — the AI assistant holds the
graph across turns, not the server.

### Example conversation flow

```
You:  Model a cap-and-trade market for three sectors with a price floor
      and an MSR that starts kicking in from year 3.

AI:   [list_models(), list_blocks()] I'll start from a blank model —
      new_graph() — and add three participants, a price_floor block, and
      an msr_bank_threshold block. Sound good?

You:  Yes.

AI:   [add_block(...) x5, check(graph) after each] The MSR needs a bank
      signal to do anything under competitive clearing: at least one year
      with banking_allowed=true and a non-myopic expectations rule. Want
      me to set both?

You:  Yes.

AI:   [set_params(...), add_block("expectations", ...), check(graph)]
      check() is clean now. [run_model(graph)] Here's what it solves to:
      price starts at ~12/tCO2 in year 1 and rises to ~34/tCO2 by year 5 as
      the MSR withholds allowances... Want me to save this model?

You:  Yes, call it "Three Sector MSR Pilot".

AI:   [save_model(graph, "Three Sector MSR Pilot")] Saved as
      user_three_sector_msr_pilot — it's now in run.command's template
      picker and pe.command's model list.
```

---

## Architecture

`src/ets` is organised as five import tiers (T0 kernel → T5 apps), each
feature module isolated in its own directory under `features/`, enforced by
`tests/test_module_isolation.py` (an AST walk over every import in
`src/ets`, not a convention). The full tier table, target tree, and
work-order history live in
[docs/feature-modules-plan.md](docs/feature-modules-plan.md) — this manual
does not duplicate it. In one line: `core/` (market primitives, no I/O) →
`config_io/` (the only JSON parser) → `features/<name>/` (one directory per
mechanism, mutually isolated) → `engine/` (the only importer of features;
solve dispatch and rule wiring) → `analysis/`, `coupling/`, `blocks/`
(workflows) → `web/`, `cli.py`, `mcp/` (apps).

The frontend mirrors this on the config/result-editing side:
`frontend/src/features/<name>/index.jsx` per feature, composed through
`frontend/src/features/registry.js` — a static literal (no dynamic
registration), the JSX-side counterpart of the backend's reviewed wiring
literals. See the registry.js module docstring and
[docs/feature-modules-plan.md](docs/feature-modules-plan.md) for the
composition-point doctrine.

---

## Modelling Approaches

The `model_approach` field on a scenario selects the price-formation
mechanism. All approaches share the same participant compliance
optimisation and market-clearing primitives (`core/participant/compliance.py`,
`core/market/clearing.py`) — they differ in how the price path across years
is determined.

### Competitive (default)

```
model_approach: "competitive"
```

All participants are price-takers. Each year, Brent's method finds `P*` such that:

```
Σᵢ net_demand_i(P*) = auction_offered
```

With `perfect_foresight` expectations, a fixed-point iteration ensures `E[P_{t+1}] = P*_{t+1}`. This is the standard partial-equilibrium ETS model and the appropriate default for most policy analysis.

**When to use:** Standard policy simulation, CBAM analysis, banking/borrowing dynamics, MSR impact assessment.

### Hotelling Rule

```
model_approach: "hotelling"
```

Allowances are treated as an exhaustible resource. The no-arbitrage condition requires the net price (royalty) to grow at the effective discount rate:

```
P*(t) = λ · (1 + r + ρ)^(t − t₀)
```

where `λ` is the shadow price (royalty) at the base year `t₀`, `r` is the risk-free discount rate, and `ρ` is an optional policy risk premium. `λ` is found by bisection so that cumulative residual emissions equal the cumulative `carbon_budget`.

**When to use:** Optimal exhaustible-resource benchmarking, theory comparison, calibration of observed price paths that rise faster than the risk-free rate.

### Nash-Cournot

```
model_approach: "nash_cournot"
```

Strategic participants named in `nash_strategic_participants` internalise their own price impact. The equilibrium satisfies: no strategic participant `i` can reduce total compliance cost by unilaterally changing abatement `aᵢ`. Non-listed participants remain price-takers. Uses Jacobi best-response iteration starting from the competitive equilibrium.

**When to use:** Markets with a small number of dominant emitters or buyers; assessment of market-power distortion on price formation.

### Run All

```
model_approach: "all"
```

Runs competitive, Hotelling, and Nash-Cournot in parallel on the same config and returns all three in a single response, allowing direct model comparison without re-submitting the scenario three times.

---

## Key Features

| Feature | Config field(s) | Description |
|---|---|---|
| Multi-year simulation | `scenarios[].years[]` | Sequential year execution with bank balance propagation |
| Banking | `banking_allowed: true` | Carry surplus allowances to future years |
| Borrowing | `borrowing_allowed: true`, `borrowing_limit` | Advance future allocations to current year |
| Rational expectations | `expectation_rule: "perfect_foresight"` | Fixed-point iteration until realised = expected prices |
| Hotelling path | `model_approach: "hotelling"` | Prices rise at `r+ρ` per year; `λ` bisected to budget |
| Nash-Cournot | `model_approach: "nash_cournot"` | Strategic participants internalise price impact |
| CBAM liability | `eua_price`, `cbam_export_share` | Post-equilibrium border adjustment cost |
| Multi-jurisdiction CBAM | `cbam_jurisdictions[]` | Per-jurisdiction price gap liability |
| EUA ensemble | `eua_price_ensemble` | Fan-chart CBAM across multiple EUA forecasts |
| Scope 2 / indirect | `electricity_consumption`, `grid_emission_factor` | Indirect emissions and Scope 2 CBAM |
| Output-Based Allocation | `production_output`, `benchmark_emission_intensity` | OBA free allocation overrides ratio |
| BAU trajectory | `initial_emissions_trajectory` | Linearly interpolate BAU emissions per participant |
| Grid factor trajectory | `grid_emission_factor_trajectory` | Linearly interpolate grid intensity per participant |
| Sector-level caps | `sectors[]` with `cap_trajectory`, `auction_share_trajectory` | Derive total cap and free pool from per-sector definitions |
| Policy cap trajectory | `cap_trajectory` | Smoothly declining total cap without per-year repetition |
| Price floor/ceiling | `price_floor_trajectory`, `price_ceiling_trajectory` | Rising price bounds without per-year repetition |
| Free allocation phase-out | `free_allocation_trajectories[]` | Per-participant ratio phase-out trajectory |
| Market Stability Reserve | `msr_enabled: true` | Withhold/release allowances based on aggregate bank |
| Carbon Cap Rule (CCR) | `ccr_enabled: true` | Taylor-rule adaptive cap responding to emissions & abatement-cost gaps |
| Price-elastic baseline (feedback A) | `reference_carbon_price`, `output_price_elasticity` | Carbon-intensive activity contracts as the price rises — demand destruction inside clearing |
| Soft-link coupling (feedback B) | `ets.coupling.run_coupled_simulation` | Iterate the ETS to a joint equilibrium with an external energy/CGE/DSGE model |
| Endogenous investment feedback | `investment_feedback_enabled`, technology option `investment_trigger` | Outer loop irreversibly adopts technology options whose Dixit–Pindyck trigger crosses the DELIVERED price path — competitive or banking approach only |
| Piecewise MAC | `abatement_type: "piecewise"`, `mac_blocks[]` | Step-function marginal abatement cost curve |
| Technology switching | `technology_options[]` | Endogenous technology choice via SLSQP portfolio optimisation |
| Auction design | `auction_reserve_price`, `minimum_bid_coverage` | Reserve price and minimum coverage rules |
| Calibration | `POST /api/calibrate` | Nelder-Mead fit of MAC slopes to observed prices |
| Batch sweep | `POST /api/batch-run` | Cartesian-product parameter sensitivity |
| CSV import | `POST /api/import-csv` | CSV table to ETS config JSON |
| Narrative summary | `POST /api/narrative` | Rule-based plain-language interpretation |
| Auction revenue tracker | auto-computed | Domestic retained, CBAM foregone, potential if KAU=EUA |
| Block-graph composer | `POST /api/graph/*`, `GET /api/blocks` | Draw a scenario as a block graph instead of hand-written JSON |
| Model manifest | `GET`/`POST /api/model-manifest` | Which feature modules a config/model uses |

---

## Partial equilibrium & economic closure

The engine is a **dynamic partial-equilibrium model of the allowance market**: it
clears one market (permits) where net demand = supply, taking activity, energy
prices, and macro conditions as exogenous inputs. Two feedback options progressively
relax that closure boundary:

- **Option A — price-elastic baseline** (in-engine): carbon-intensive activity
  responds to the carbon price *within* clearing, so price and activity are solved
  jointly. Reduced-form, own-price; stays partial equilibrium.
  See [`modules/elastic_baseline/doc/reference.md`](modules/elastic_baseline/doc/reference.md).
- **Option B — soft-link coupling** (outer loop): iterate the ETS to a joint
  equilibrium with a purpose-built external model (energy-system / CGE / DSGE) via
  a pluggable adapter — general-equilibrium feedback without embedding a GE model.
  See [`docs/feedback-coupling.md`](docs/feedback-coupling.md).

A third, distinct mechanism — [endogenous investment feedback](#investment-feedback)
— does not relax the closure boundary above (it stays a single-market, single-engine
model); it makes *technology adoption itself* an outer-loop equilibrium object instead
of a static config choice or a post-processed reading of an already-solved path.

New to the tool? Open [`docs/tutorials/`](docs/tutorials/index.html) — a follow-along
[walkthrough](docs/tutorials/build-your-first-scenario.html) that climbs the closure ladder, plus a
[scenario cookbook](docs/tutorials/scenario-cookbook.html) of ~20 ready-to-run recipes (one per feature).

---

## Investment Feedback

Endogenous technology adoption (Phase 1): an outer loop (`engine/feedback.py`)
around the FULL path solve prices each flagged technology's Dixit–Pindyck
investment trigger against the DELIVERED price path of the previous iterate,
irreversibly adopts at most one crossing pair per iteration, and re-runs the
whole path solve — converging in at most `N_flagged + 1` iterations
(monotone adoption, no price relaxation, no tolerance). See
[`docs/algorithm-overview.md`, "Endogenous Investment Feedback (Phase 1)"](docs/algorithm-overview.md#endogenous-investment-feedback-phase-1)
for the trigger math, the outer-loop pseudocode, and the termination theorem,
and [`modules/endogenous_investment/doc/spec.md`](modules/endogenous_investment/doc/spec.md) for the
binding economic spec.

Enable it with `investment_feedback_enabled: true` on the scenario and an
`investment_trigger` sub-dict on one or more `technology_options[]` entries
(the sub-dict's presence IS the flag). Supported under
`model_approach: "competitive"` or `"banking"` only — `"hotelling"`,
`"nash_cournot"`, and `"all"` raise a config error if flagged.

### Scenario-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `investment_feedback_enabled` | bool | `false` | Master gate. A flagged `investment_trigger` block with the gate off, or the gate on with nothing flagged, raises a `ValueError` — never a silent no-op. |
| `investment_max_iterations` | int ≥ 1 | `N_flagged + 1` | Safety rail on outer iterations; exhaustion logs a `WARNING` and returns the last iterate with `Investment Converged = 0`. There is no relaxation or tolerance parameter — termination is combinatorial. |
| `investment_initial_adoptions` | array | `[]` | Pre-committed adoptions `[{participant, technology, adoption_year}]`; also the landing field the policy-event splice carrier stamps into the next segment. Carried adoptions are FLOORS — a later segment can never un-adopt them. |
| `invest_credibility` | float [0,1] | unset | Scenario-wide override of every flagged option's own `investment_trigger.credibility`; the field an announced policy event raises via `changes: {"invest_credibility": ...}`. |

### Technology option: `investment_trigger` sub-dict

Add this sub-dict to any entry in a participant's `technology_options[]` to flag it for adoption. Unknown keys raise loudly.

| Field | Type | Units | Required / Default | Description |
|---|---|---|---|---|
| `break_even_price` | float | currency/tCO₂ | REQUIRED — exactly one of this or `break_even_prices` | Constant Marshallian break-even θ. |
| `break_even_prices` | object `{year: value}` | currency/tCO₂ | REQUIRED — exactly one of this or `break_even_price` | Declining/rising break-even schedule (e.g. θ falling with hydrogen input costs). |
| `payout_yield` | float | 1/yr | REQUIRED, no default | y — sets the certainty-limit hurdle r/y; deliberately has no default. |
| `sigma` | float ≥ 0 | 1/√yr | `0.0` | Unfloored price volatility σ. |
| `credibility` | float [0,1] | dimensionless | `0.0` | q — probability the announced floor/decree holds; overridden scenario-wide by `invest_credibility`. |
| `discount_rate` | float | 1/yr | scenario `discount_rate` | Per-pair override of r. |
| `trigger_mode` | `"dixit_pindyck"` \| `"break_even"` | — | `"dixit_pindyck"` | `"break_even"` pins the multiple M ≡ 1 (NPV activation dating instead of the D-P trigger). |
| `trigger_multiple_override` | float ≥ 1 | dimensionless | unset | Bypasses M resolution entirely when set. |
| `build_lag_years` | int ≥ 0 | yr | `0` | L — years between the decision year τ (state flips) and capacity effective at τ+L. |

### Output columns

Four diagnostic columns appear in the scenario-summary output only when the
feature is configured (key-presence guarded — every pre-existing golden stays
column-identical when nothing is flagged): `Investment Adoptions` (sorted JSON
of `{participant, technology, adoption_year}`, effective through that row's
year), `Investment Newly Effective` (count of pairs whose capacity arrives
that year, τ+L == year), `Investment Feedback Iterations`, `Investment
Converged` (`1.0`/`0.0`).

### Examples

- **`examples/investment_competitive_transition.json`** — competitive path,
  one participant, one flagged H2-DRI option, `build_lag_years: 1`. Masked
  (pre-adoption) prices climb 60 → 76 → 90 → 104 → 116 across 2026–2030; the
  trigger (θ=48, y=0.03, σ=0, so M = r/y = 11/6, P\*=88) first crosses in
  2028 (masked price 90 ≥ 88). The DECISION year 2028 still clears at 90
  (capacity isn't in yet); capacity arrives 2029 and the entrant's cheaper
  demand curve collapses the price to 44 — below the trigger, the spec's
  ex-post-regret asymmetry (D1.1). Delivered prices: `[60, 76, 90, 44, 56]`.
  Two outer iterations, converged.
- **`examples/k_msr_decree_induces_investment.json`** — the K-MSR paper's
  central transition claim, solved as an endogenous equilibrium rather than
  post-processing. Two twin banking scenarios (6 years, 2026–2031) flag the
  same Steel H2-DRI option (θ=5,000 KRW, σ=0.48, y=0.03):
  - **P1 decree (credible floor)** — hybrid-mode MSR plus a rising auction
    reserve 9,000 → 12,800 KRW, `invest_credibility: 0.8` (σ_eff=0.096,
    M≈2.124, P\*≈10,618 KRW). Delivered prices track the reserve floor
    exactly: `[9000, 9700, 10400, 11200, 12000, 12800]`. **Steel/H2-DRI
    adopts in 2029** — the first year the floor-delivered price (11,200)
    clears the trigger.
  - **P0 no reserve (twin)** — identical fundamentals, no MSR, no floor,
    `invest_credibility: 0.0` (M≈6.386, P\*≈31,931 KRW). Delivered prices:
    `[7055.70, 7443.76, 7853.17, 8285.09, 8740.77, 9221.51]`. **Never
    adopts** — the pure banking ramp tops out around 9,222 KRW, roughly a
    third of the uncredible trigger.

  Same technology, same fundamentals: the decree package changes whether and
  when adoption happens through two channels at once — the floor delivers
  the trigger price, and its credibility shrinks the option-value wedge. The
  adopted capacity then feeds back into the very banking window it was
  priced on (lower emissions → bigger bank → MSR intake responds), with zero
  MSR-module changes.

```bash
PYTHONPATH=src uv run python -m ets.cli --config examples/k_msr_decree_induces_investment.json
PYTHONPATH=src uv run python -m ets.cli --config examples/investment_competitive_transition.json
```

---

## Config Schema Quick Reference

### Scenario-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Scenario identifier |
| `model_approach` | `"competitive"` \| `"hotelling"` \| `"nash_cournot"` \| `"all"` | `"competitive"` | Price-formation mechanism |
| `discount_rate` | float | `0.04` | Annual discount rate `r` for Hotelling formula |
| `risk_premium` | float | `0.0` | Policy risk premium `ρ` added to `r` in Hotelling formula |
| `reference_carbon_price` | float ≥ 0 | `0.0` | Feedback A: price anchor P_ref for the price-elastic baseline; `0` disables the channel |
| `nash_strategic_participants` | string[] | `[]` | Participant names treated as strategic in Nash-Cournot |
| `msr_enabled` | bool | `false` | Enable Market Stability Reserve |
| `msr_upper_threshold` | float | `200.0` | Bank (Mt) above which withholding fires |
| `msr_lower_threshold` | float | `50.0` | Bank (Mt) below which release fires |
| `msr_withhold_rate` | float | `0.12` | Fraction of auction_offered withheld per year |
| `msr_release_rate` | float | `50.0` | Mt released per year from reserve |
| `msr_cancel_excess` | bool | `false` | Permanently cancel pool above `msr_cancel_threshold` |
| `msr_cancel_threshold` | float | `400.0` | Pool level (Mt) above which excess is cancelled |
| `ccr_enabled` | bool | `false` | Enable Carbon Cap Rule (adaptive cap) |
| `ccr_phi_emissions` | float | `0.0` | φ_e — Mt cap change per unit emissions gap (negative tightens on overshoot) |
| `ccr_phi_abatement_cost` | float | `0.0` | φ_z — Mt cap change per unit abatement-cost gap (positive loosens when costs run hot) |
| `ccr_reference_emissions` | float | `0.0` | ē — reference emissions (Mt); `0` disables the emissions term |
| `ccr_reference_abatement_cost` | float | `0.0` | z̄ — reference abatement cost; `0` disables the cost term |
| `cap_trajectory` | object | `{}` | Scenario-wide linearly declining total cap |
| `price_floor_trajectory` | object | `{}` | Linearly rising price floor |
| `price_ceiling_trajectory` | object | `{}` | Linearly rising price ceiling |
| `free_allocation_trajectories` | array | `[]` | Per-participant free ratio phase-out |
| `sectors` | array | `[]` | Sector objects with cap and auction share trajectories |
| `investment_feedback_enabled` | bool | `false` | Master gate for endogenous investment feedback (see [Investment Feedback](#investment-feedback)); flagged `investment_trigger` blocks with the gate off (or vice versa) raise a `ValueError` |
| `investment_max_iterations` | int ≥ 1 | `N_flagged + 1` | Safety rail on outer adoption-loop iterations; not a relaxation/tolerance knob |
| `investment_initial_adoptions` | array | `[]` | Pre-committed adoptions `[{participant, technology, adoption_year}]`; also the splice-carrier landing field |
| `invest_credibility` | float [0,1] | unset | Scenario-wide override of every flagged option's `investment_trigger.credibility` |
| `years` | array | required | Year config objects |

### Year-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `year` | string | required | Year label (e.g. `"2030"`) |
| `total_cap` | float | `0.0` | Annual emissions cap (Mt CO₂e) |
| `auction_mode` | `"explicit"` \| `"derive_from_cap"` | `"explicit"` | How auction volume is determined |
| `auction_offered` | float | `0.0` | Volume offered at auction (Mt) |
| `reserved_allowances` | float | `0.0` | Withheld from market; count toward cap |
| `cancelled_allowances` | float | `0.0` | Permanently retired; count toward cap |
| `auction_reserve_price` | float | `0.0` | Minimum clearing price |
| `minimum_bid_coverage` | float [0,1] | `0.0` | Min fraction of offered volume that must be bid |
| `unsold_treatment` | `"reserve"` \| `"cancel"` \| `"carry_forward"` | `"reserve"` | Disposition of unsold allowances |
| `price_lower_bound` | float | `0.0` | Price floor for equilibrium solver |
| `price_upper_bound` | float | `100.0` | Price ceiling for equilibrium solver |
| `banking_allowed` | bool | `false` | Allow surplus carry-forward |
| `borrowing_allowed` | bool | `false` | Allow deficit carry-back |
| `borrowing_limit` | float | `0.0` | Maximum borrow volume (Mt) |
| `expectation_rule` | string | `"next_year_baseline"` | Future price expectation method |
| `manual_expected_price` | float | `0.0` | Price used when `expectation_rule = "manual"` |
| `carbon_budget` | float | `0.0` | Cumulative budget for Hotelling bisection |
| `eua_price` | float | `0.0` | EU ETS reference price for CBAM |
| `eua_prices` | object | `{}` | Per-jurisdiction prices, e.g. `{"EU": 72, "UK": 58}` |
| `eua_price_ensemble` | object | `{}` | Named EUA forecasts for CBAM fan chart |
| `participants` | array | required | Participant config objects |

### Participant-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Unique participant identifier |
| `sector_group` | string | `""` | Sector label for aggregated reporting |
| `sector_allocation_share` | float [0,1] | `0.0` | This participant's share of its sector's free pool |
| `initial_emissions` | float ≥ 0 | `0.0` | Gross BAU emissions (Mt CO₂e) |
| `initial_emissions_trajectory` | object | `{}` | Linearly interpolated BAU over years |
| `free_allocation_ratio` | float [0,1] | `0.0` | Share of initial emissions covered for free |
| `penalty_price` | float > 0 | `100.0` | Fine per uncovered tonne (₩/t) |
| `abatement_type` | `"linear"` \| `"piecewise"` \| `"threshold"` | `"linear"` | MAC model |
| `max_abatement` | float ≥ 0 | `0.0` | Maximum reducible emissions (Mt) |
| `cost_slope` | float > 0 | `1.0` | Slope `σ` of linear MAC (₩/t per Mt) |
| `threshold_cost` | float ≥ 0 | `0.0` | Switching price for threshold MAC |
| `mac_blocks` | array | `[]` | Piecewise MAC blocks `{amount, marginal_cost}`, sorted by non-decreasing `marginal_cost`. `amount` ≥ 0; `marginal_cost` may be **negative** (no-regret measures) |
| `production_output` | float ≥ 0 | `0.0` | Annual physical output (Mt product/yr) |
| `benchmark_emission_intensity` | float ≥ 0 | `0.0` | OBA benchmark (tCO₂/unit product) |
| `output_price_elasticity` | float ≥ 0 | `0.0` | Feedback A: price elasticity of activity ε; baseline contracts as price exceeds `reference_carbon_price` |
| `cbam_export_share` | float [0,1] | `0.0` | Fraction exported to single CBAM market |
| `cbam_coverage_ratio` | float [0,1] | `1.0` | Fraction of exports within CBAM scope |
| `cbam_jurisdictions` | array | `[]` | Multi-jurisdiction CBAM list |
| `electricity_consumption` | float ≥ 0 | `0.0` | Annual electricity use (MWh) |
| `grid_emission_factor` | float ≥ 0 | `0.0` | Grid carbon intensity (tCO₂/MWh) |
| `grid_emission_factor_trajectory` | object | `{}` | Linearly interpolated grid factor over years |
| `scope2_cbam_coverage` | float [0,1] | `0.0` | Fraction of indirect emissions in CBAM scope |
| `technology_options` | array | `[]` | Alternative production technologies; each entry may carry an `investment_trigger` sub-dict to flag it for endogenous adoption — see [Investment Feedback](#investment-feedback) |

---

## Solver Settings

Nine solver parameters, all set at the scenario level, control numerical precision and iteration limits across the three deterministic solvers.

| Parameter | Default | Controls |
|---|---|---|
| `solver_competitive_max_iters` | `25` | Maximum perfect-foresight fixed-point iterations before declaring convergence |
| `solver_competitive_tolerance` | `0.001` | Convergence threshold: max price change between iterations (₩/t) |
| `solver_hotelling_max_bisection_iters` | `80` | Maximum bisection steps when finding shadow price `λ` |
| `solver_hotelling_max_lambda_expansions` | `20` | Maximum attempts to expand the `[λ_low, λ_high]` bracket |
| `solver_hotelling_convergence_tol` | `0.0001` | Relative tolerance on cumulative emissions: `|Σ_e − budget| / budget` |
| `solver_nash_price_step` | `0.5` | Finite-difference step (₩/t) for estimating `dP/dQ` price impact |
| `solver_nash_max_iters` | `120` | Maximum Jacobi best-response iterations per year |
| `solver_nash_convergence_tol` | `0.001` | Convergence threshold: max abatement change (Mt) between iterations |
| `solver_penalty_price_multiplier` | `1.25` | Upper bracket = `max(penalty_price) × multiplier` for Brent's method |

---

## Analysis Tools

Tools in `src/ets/analysis/` extend the core simulator with higher-level workflows.

### Model Calibration (`/api/calibrate`)

Fits `abatement_cost_slope` parameters for named participants to minimise MSE between modelled equilibrium prices and a set of observed historical prices. Uses Nelder-Mead optimisation (scipy).

**Request:** `POST /api/calibrate` with JSON body:

```json
{
  "config": { "scenarios": [...] },
  "observed_prices": { "2026": 18.5, "2027": 22.0, "2028": 25.5 },
  "participant_names": ["POSCO", "Hyundai Steel"],
  "initial_slopes": [6.5, 7.0],
  "max_iter": 500
}
```

**Response:** `calibrated_slopes`, `final_mse`, `iterations`, `success`, `modelled_prices`, `observed_prices`.

### Batch / Sensitivity Runner (`/api/batch-run`)

Sweeps one or more parameters over cartesian product of values and collects per-run summaries. Uses JSON-path notation with `[*]` wildcard for year arrays.

**Request:** `POST /api/batch-run`:

```json
{
  "config": { "scenarios": [...] },
  "sweeps": [
    { "path": "scenarios[0].years[*].eua_price", "values": [40, 60, 80, 100] },
    { "path": "scenarios[0].discount_rate", "values": [0.03, 0.04, 0.05] }
  ]
}
```

**Response:** `runs` (one per combination), `sweep_axes`, `n_runs`, `n_errors`.

### CSV Import (`/api/import-csv`)

Converts a CSV table (one row per participant per year) into a valid ETS config JSON. Required columns: `year`, `participant_name`. Optional columns match participant field names.

**Request:** `POST /api/import-csv` with `multipart/form-data` containing `file` field (CSV text) and optional `scenario_name`.

### Narrative Summary (`/api/narrative`)

Generates a plain-language interpretation of simulation results: price trend, cumulative abatement, CBAM exposure, and domestic auction revenue.

**Request:** `POST /api/narrative`:

```json
{
  "results": [ { "year": "2026", "summary": { "Equilibrium Carbon Price": 18500 } } ],
  "scenario_name": "K-ETS Baseline"
}
```

**Response:** `{ "narrative": "The equilibrium carbon price rises from ₩18,500/t in 2026 ..." }`

### Block Graph API

The composer and pe shell talk to the same backend through a small set of
graph endpoints (full contract in
[docs/blocks-graph-plan.md §5](docs/blocks-graph-plan.md)):

| Endpoint | Purpose |
|---|---|
| `GET /api/blocks` | Block catalogue — palette entries, param specs, ports, constraints |
| `POST /api/graph/validate` | Structural validation of a drawn graph (R1–R32) |
| `POST /api/graph/compile` | Graph → scenario-config dict, no run |
| `POST /api/graph/run` | Graph → scenario-config → today's `/api/run` payload |
| `GET /api/graph/from-template?id=<id>` | Template or saved model → graph (decompiled, or the saved sidecar) |
| `POST /api/graph/save-model` | Graph → persisted `user_<slug>` model, runnable and re-editable |
| `GET`/`POST /api/model-manifest` | Which feature modules a model/config uses — see [Model manifest](#model-manifest) above |

---

## GUI Walkthrough

### Step 1 — Scenario setup

Set `name`, `model_approach`, `discount_rate` (Hotelling), `risk_premium` (Hotelling), `nash_strategic_participants` (Nash). Enable MSR parameters if needed. All fields are in the collapsible **Scenario Settings** group.

### Step 2 — Year configuration

Each year is a collapsible panel. Set `total_cap`, `auction_mode`, `auction_offered`, price bounds, banking/borrowing flags, and `expectation_rule`. Collapsible groups within each year: **Auction Design**, **Price Bounds**, **Banking & Borrowing**, **Expectation Settings**, **CBAM / EUA Prices**.

### Step 3 — Participant configuration

Add participants via the **Add Participant** button. Collapsible groups per participant: **Emissions & Allocation**, **MAC / Abatement**, **CBAM Exposure**, **Scope 2 / Indirect**, **Output-Based Allocation (OBA)**, **Technology Options**.

The MAC block editor supports visual entry of piecewise step-function cost curves. Each block defines an `amount` (Mt CO₂e abatable at this cost) and `marginal_cost` (₩/t). Blocks must be entered in non-decreasing cost order.

The technology transition wizard guides creation of `technology_options` — alternative production modes with their own emission profiles, MAC curves, fixed adoption costs, and maximum activity shares.

### Step 4 — Run and explore

Click **Run Simulation**. The output panels show:

- **Scenario summary table**: one row per scenario-year with all aggregate statistics
- **Market clearing chart**: demand curve and equilibrium price for each year
- **Annual emissions trajectory**: abatement and residual emissions over time
- **Participant panel**: individual cost breakdown, CBAM liability, bank balances
- **Narrative**: plain-language interpretation (auto-generated)

This is the same Editor/AppViews UI whether reached via `run.command`
(unscoped) or via `pe.command` after selecting a model (scoped to that
model's feature modules — see [Model manifest](#model-manifest)). Building a
model visually instead of by hand is the [Composing models](#composing-models)
walkthrough above, via `configure.command`.

---

## Output Columns Reference

### Participant results (one row per participant per year)

| Column | Description |
|---|---|
| `Scenario` | Scenario name |
| `Year` | Year label |
| `Participant` | Participant name |
| `Sector Group` | Sector label from `sector_group` |
| `Chosen Technology` | Active technology name or "Mixed Portfolio ..." |
| `Technology Mix` | Semicolon-separated `name:share` pairs |
| `Initial Emissions` | BAU gross emissions (Mt CO₂e) |
| `Free Allocation` | Free allowances received (Mt) |
| `Abatement` | Emissions reduced (Mt) |
| `Residual Emissions` | Post-abatement direct emissions (Mt) |
| `Allowance Buys` | Allowances purchased (Mt) |
| `Allowance Sells` | Allowances sold (Mt) |
| `Net Allowances Traded` | Buys minus sells (Mt); positive = net buyer |
| `Penalty Emissions` | Emissions not covered, subject to penalty (Mt) |
| `Starting Bank Balance` | Allowances carried in from prior year (Mt) |
| `Ending Bank Balance` | Allowances carried forward to next year (Mt) |
| `Banked Allowances` | `max(0, ending bank balance)` (Mt) |
| `Borrowed Allowances` | `max(0, -ending bank balance)` (Mt) |
| `Expected Future Price` | Price used for banking/borrowing decision (₩/t) |
| `Fixed Technology Cost` | Fixed adoption cost of chosen technology (₩M) |
| `Abatement Cost` | Variable cost of abatement (₩M) |
| `Allowance Cost` | Cost of purchased allowances at equilibrium price (₩M) |
| `Penalty Cost` | Fine for uncovered emissions (₩M) |
| `Sales Revenue` | Revenue from sold allowances (₩M) |
| `Total Compliance Cost` | Sum of costs minus sales revenue (₩M) |
| `EUA Price` | EU ETS reference price used for CBAM (€/t) |
| `CBAM Gap` | `max(0, EUA_price − P*)` (₩/t) |
| `CBAM Export Share` | Aggregate export share fraction |
| `CBAM Liable Emissions` | Residual emissions subject to CBAM (Mt) |
| `CBAM Liability` | Total CBAM border adjustment (₩M) |
| `Total Cost incl. CBAM` | Total Compliance Cost + CBAM Liability (₩M) |
| `Electricity Consumption` | Annual electricity use (MWh) |
| `Grid Emission Factor` | Grid carbon intensity (tCO₂/MWh) |
| `Indirect Emissions` | `electricity × grid_factor` (Mt CO₂e) |
| `Scope 2 CBAM Coverage` | Fraction of indirect emissions in CBAM scope |
| `Scope 2 CBAM Liability` | CBAM liability on indirect emissions (₩M) |
| `CBAM Liability (X)` | Per-jurisdiction CBAM when `cbam_jurisdictions` used |
| `CBAM Gap (X)` | Per-jurisdiction price gap |
| `CBAM Liability (source)` | EUA ensemble CBAM under named forecast |

### Scenario summary (one row per scenario-year)

| Column | Description |
|---|---|
| `Equilibrium Carbon Price` | Market-clearing price P* (₩/t) |
| `Total Abatement` | Sum across all participants (Mt) |
| `Total Allowance Buys / Sells` | Gross market volume (Mt) |
| `Total Penalty Emissions` | Uncovered emissions in penalty channel (Mt) |
| `Auction Offered / Sold` | Supply and actual clearing volume (Mt) |
| `Unsold Allowances` | Allowances below reserve price (Mt) |
| `Auction Coverage Ratio` | Sold / Offered |
| `Total Auction Revenue` | `P* × auction_sold` (₩M) |
| `Total Banked / Borrowed Allowances` | System-wide bank dynamics (Mt) |
| `MSR Withheld / Released / Reserve Pool` | MSR state when enabled (Mt) |
| `CCR Cap Adjustment / Emissions Deviation / Cost Deviation` | Carbon Cap Rule state when enabled (Mt / fraction) |
| `Total CBAM Liability` | System-wide border adjustment (₩M) |
| `Domestic Retained Revenue` | Auction revenue remaining in Korea (₩M) |
| `CBAM Foregone Revenue` | CBAM that flows to EU rather than Korea (₩M) |
| `Potential Revenue if KAU=EUA` | Domestic revenue if price equalled EUA (₩M) |
| `{Sector} Total Abatement` | Sector-group aggregate (Mt) |
| `{Sector} P10/P50/P90 Compliance Cost` | Distribution across participants in sector (₩M) |

---

## Documentation Index

| File | What it covers |
|---|---|
| `docs/feature-modules-plan.md` | Backend feature-module architecture — import tiers, target tree, isolation enforcement, work-order history, execution status |
| `docs/blocks-graph-plan.md` | Block catalogue, graph schema, compiler, API contract for the composer and manifest endpoints |
| `docs/blocks-composition-rules.md` | Graph-validation rules R1–R32 and engine findings F1–F6 |
| `docs/algorithm-overview.md` | Solver math (competitive, Hotelling, Nash), MSR, CBAM, validation rules, execution flow |
| `core/doc/data-model.md` | Every config field — type, default, validation, example |
| `core/doc/multi-year-simulation.md` | Banking, borrowing, expectation rules, BAU trajectory, grid factor trajectory, sector dynamics, auction revenue decomposition |
| `modules/oba/doc/reference.md` | Output-Based Allocation concept, formula, override hierarchy, worked steel example |
| `modules/ccr/doc/reference.md` | Carbon Cap Rule (Benmir, Roman & Taschini 2025) — adaptive Taylor-rule cap, formula, config, worked example |
| `modules/elastic_baseline/doc/reference.md` | Feedback Option A — price-elastic baseline (within-clearing demand destruction), formula, config, worked example |
| `docs/feedback-coupling.md` | Feedback Option B — soft-link coupling loop, adapter contract, writing your own external model |
| `docs/tutorials/index.html` | Tutorials landing page — links the walkthrough and the cookbook |
| `docs/tutorials/build-your-first-scenario.html` | Follow-along HTML walkthrough — base PE → MSR → CCR → feedback A → feedback B |
| `docs/tutorials/scenario-cookbook.html` | ~20 ready-to-run recipes grouped by theme, each mapped to an `examples/` file |
| `docs/tutorials/practitioner-training.html` | Role-based training course — six use-case modules (compliance, policy, trading, strategy, feedback, calibration) + feature × use-case matrix |
| `modules/sectors/doc/reference.md` | Sector-level caps, auction share derivation, per-participant allocation from sector pool, worked two-participant example |
| `core/doc/analysis-tools.md` | Calibration, batch runner, CSV import, narrative — APIs, request/response schemas, algorithms |
| `core/doc/mac-abatement.md` | Linear, piecewise, and threshold MAC models with cost derivations |
| `core/doc/market-equilibrium.md` | Brent's method details, auction rules, bracketing procedure |
| `modules/endogenous_investment/doc/reference.md` | Technology options, SLSQP portfolio optimisation, fixed-cost switching |
| `docs/k-msr-condensed.md`, `docs/k-msr-vs-repo-comparison.md` | K-MSR (decree-mode) paper reproduction — condensed source translation and repo-vs-paper comparison |
| `modules/endogenous_investment/doc/spec.md`, `docs/invest-feedback-plan.md` | Endogenous investment feedback (Phase 1) — binding economic spec (trigger, equilibrium concept, termination theorem) and architecture/work-order history; see also [Investment Feedback](#investment-feedback) and `docs/algorithm-overview.md` |

---

## Project Structure

```
src/ets/
  core/               T0 — market primitives, no I/O
    market/           model.py (CarbonMarket), clearing.py (Brent's method), reporting.py
    participant/       models.py, compliance.py, technology.py
    costs.py, defaults.py, expectations.py, ledger.py, protocols.py, paths.py, logger.py
  config_io/          T1 — the only JSON parser
    normalize.py, builder.py, templates.py
  features/           T2 — one directory per mechanism, mutually isolated
    banking/, cbam/, ccr/, competitive/, elastic_baseline/, hoarding/,
    hotelling/, msr/, nash_cournot/, oba/, price_controls/, sectors/, transmission/
    each: plugin.py (config-facing door) + runtime modules (solver/rules/state)
  engine/             T3 — the only importer of features
    dispatch.py       run_simulation(), run_simulation_from_config/file
    wiring.py         default_cap_rules / default_supply_rules per approach
    events.py         policy-event splicing
  analysis/           T4 — workflows (isolated leaves)
    calibration.py, batch.py, csv_import.py, narrative.py, investment_trigger.py
  coupling/           T4 — Option B soft-link fixed-point loop
    loop.py, adapters.py
  blocks/             T4 — graph compiler, config_io-only (engine-blind)
    registry.py, catalogue.py, graph.py, validate.py, compile.py, decompile.py,
    manifest.py, serialize.py (wire-shape helpers, shared by web + mcp)
  model_store.py       shared registry I/O (save/list/resolve models on disk);
                       used by both web/ and mcp/, imports neither
  web/                T5 — apps
    api.py, routes.py, handlers.py, server.py
  cli.py              T5 — command-line entry point
  mcp/                T5 — AI-guided composer, exposed as an MCP server
    tools.py           stateless tool implementations (list_models, list_blocks,
                       describe_block, new_graph, add_block, set_params,
                       remove_node, check, run_model, save_model)
    suggestions.py     rule -> plain-language-suggestion table for check()
    compact.py         compact per-scenario/per-year summary for run_model()
    server.py          FastMCP wiring + server instructions; __main__.py entry
  <flat shims>        expectations.py, msr.py, ccr.py, costs.py, config.py, market.py,
                       participant.py, solvers/, market/, participant/ — DeprecationWarning,
                       re-export the moved names; see docs/feature-modules-plan.md §4 O13

api/
  index.py             Vercel serverless shim — wraps WSGI app

frontend/
  src/
    main.jsx           Mode switch: ?mode=composer / ?mode=pe / default
    app.jsx             Root component — tab routing (the default/run.command shell)
    composer/           ComposerAdmin.jsx, Composer.jsx — the configure.command shell
    pe/                 PeApp.jsx — the pe.command shell
    features/           registry.js + one <name>/index.jsx per feature module
    components/
      Editor.jsx           Scenario builder — collapsible config panels
      AppViews.jsx          Output views coordinator
      AppShared.jsx         Shared layout, toolbar
      MarketChart.jsx       Demand curve and equilibrium price chart
      AnnualMarketChart.jsx Multi-year price trajectory chart
      AnnualEmissionsChart.jsx Emissions trajectory chart
      TrajectoryChart.jsx   Policy trajectory visualisation
      ParticipantPanel.jsx  Participant-level cost breakdown
      ParticipantMacChart.jsx MAC curve visualisation
      MarketYearGallery.jsx Year-gallery navigation
      GuideView.jsx         In-app user guide

examples/             Pre-built JSON scenario files
user-scenarios/       User-saved scenarios and composer models (runtime, gitignored)
docs/                 Extended documentation
```

---

## Limitations

- **Single commodity:** Only CO₂-equivalent emissions are modelled. Multi-pollutant general-equilibrium feedback is captured only via the optional [soft-link coupling](docs/feedback-coupling.md) (feedback B) to an external model.
- **Static abatement curves:** MAC parameters do not evolve endogenously. Technological learning curves must be specified explicitly via trajectories. (MAC blocks may include negative-cost "no-regret" measures — see [core/doc/mac-abatement.md](core/doc/mac-abatement.md).)
- **No financial intermediaries:** Banks, brokers, and speculative traders are not modelled. Banking is purely a compliance firm decision.
- **Partial equilibrium by design:** The core engine clears the allowance market with activity, energy, and macro conditions exogenous. Two opt-in channels relax this: [price-elastic baseline](modules/elastic_baseline/doc/reference.md) (feedback A — own-price activity response, still partial equilibrium) and [soft-link coupling](docs/feedback-coupling.md) (feedback B — joint equilibrium with an external energy/CGE/DSGE model). Both default off.
- **Endogenous investment feedback covers competitive and banking only (v1):** [Investment feedback](#investment-feedback) wraps the competitive and Rubin/Schennach banking path solves; scenarios under `model_approach: "hotelling"`, `"nash_cournot"`, or `"all"` cannot flag `technology_options[]` for adoption yet (a flagged option under those approaches raises a config error rather than silently ignoring the flag). The partial-credibility interior mapping σ_eff(q) = (1−q)·σ is a documented modelling choice, not a paper result (see [`modules/endogenous_investment/doc/spec.md`](modules/endogenous_investment/doc/spec.md) D2.1).
- **Calibration is single-scenario:** The `/api/calibrate` endpoint calibrates `abatement_cost_slope` for linear MAC only; piecewise blocks are not calibrated automatically.
- **Nash-Cournot convergence:** The Jacobi iteration may not converge for all market configurations; the solver logs a warning and uses its best approximation if the iteration limit is reached.
- **Integer compliance:** The model operates in continuous tonnes; compliance is not restricted to integer lots.
