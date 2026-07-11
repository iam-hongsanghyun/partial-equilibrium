# K-ETS Partial-Equilibrium Simulator

A research-grade, multi-year partial-equilibrium simulator for the Korean Emissions Trading Scheme (K-ETS) and comparable cap-and-trade systems.

## What it does

Models competitive, Hotelling-optimal, Nash-Cournot, and banking-fixed-point price formation, with Market Stability Reserve, Carbon Cap Rule, CBAM exposure, Output-Based Allocation, sector-level caps, and price-elastic-baseline / soft-link general-equilibrium feedback. Every mechanism is a self-contained **feature module** — backend (`src/ets/features/<name>/`) and frontend (`frontend/src/features/<name>/`) — composed rather than hardcoded, so a model only shows the modules it actually uses.

Three ways in: `run.command` (everything), `configure.command` (a graph-based model composer), `pe.command` (pick a model, get only its modules).

## Live App

**Deployed:** https://ets.vercel.app

The `api/index.py` shim exposes the WSGI application to Vercel's serverless runtime. The React frontend communicates with the Python backend via a JSON REST API.

## Quickstart

```bash
git clone <this-repo> && cd pe-modular
uv sync --all-extras       # or: pip install -e ".[dev]"

./run.command               # everything-tool  -> http://127.0.0.1:8765/
./configure.command          # composer admin   -> http://127.0.0.1:8801/?mode=composer
./pe.command                 # model-scoped shell -> http://127.0.0.1:8802/?mode=pe
```

All three sync the pinned environment and launch the same backend on a
different port; run any combination at once. Full launcher reference (ports,
env-var overrides, CLI passthrough) and a walkthrough of composing a model
in the composer: [MANUAL.md — Launchers](MANUAL.md#launchers),
[MANUAL.md — Composing models](MANUAL.md#composing-models).

## Installation

```bash
uv sync --all-extras           # install (preferred)
# or: pip install -e ".[dev]"
```

Frontend (development):

```bash
cd frontend
npm install
npm run dev                    # Vite dev server at http://localhost:5173
```

Frontend (production build, consumed by the launchers and by Vercel):

```bash
cd frontend
npm run build
cp public/styles.css dist/styles.css
```

## Usage

Run a bundled sample from the command line:

```bash
uv run python -m ets.cli --mode banking
```

Or launch the browser GUI (see [Quickstart](#quickstart) for the three launcher variants):

```bash
uv run python -m ets.cli --gui       # http://127.0.0.1:8765/
```

## Architecture

`src/ets` is a **feature-module engine**: five import tiers (kernel →
config boundary → isolated feature modules → engine composition → workflows
→ apps), enforced by an AST-walking test
(`tests/test_module_isolation.py`), not convention. A **block-composer GUI**
(`configure.command`, React Flow) draws scenarios as graphs and compiles
them to the same scenario-config dict the CLI and API run. A
**module-scoped pe shell** (`pe.command`) lists models first and scopes the
UI to exactly the feature modules a selected model uses, via
`GET /api/model-manifest`.

Full architecture, target tree, and execution history:
[docs/feature-modules-plan.md](docs/feature-modules-plan.md). Block
catalogue, graph schema, and API contract:
[docs/blocks-graph-plan.md](docs/blocks-graph-plan.md).

## Golden-baseline gate

Every change to solver/rule math is gated by `uv run pytest` against
committed golden baselines (`tests/baselines/`, `tests/test_golden_baselines.py`)
in the `uv.lock`-pinned environment — numeric output must match bit-exactly
unless the change is a declared, sign-off math change. CI runs the full
suite; run it locally before opening a PR:

```bash
uv run pytest -q
```

## Deploy

1. Fork the repository.
2. Connect to Vercel. The `vercel.json` routes all requests to `api/index.py`.
3. No environment variables are required for a basic deployment.

## Documentation

| Doc | Covers |
|---|---|
| [MANUAL.md](MANUAL.md) | Launchers, composing models, model manifest, config schema, GUI walkthrough, output columns, full project structure, limitations |
| [docs/feature-modules-plan.md](docs/feature-modules-plan.md) | Feature-module architecture — import tiers, isolation enforcement, work orders, execution status |
| [docs/blocks-graph-plan.md](docs/blocks-graph-plan.md) | Block catalogue, graph compiler, composer/manifest API contract |
| [docs/algorithm-overview.md](docs/algorithm-overview.md) | Solver math — competitive, Hotelling, Nash, MSR, CBAM |
| [core/doc/data-model.md](core/doc/data-model.md) | Every config field — type, default, validation |
| [docs/tutorials/index.html](docs/tutorials/index.html) | Follow-along walkthrough + ~20-recipe scenario cookbook |

See MANUAL.md's [Documentation Index](MANUAL.md#documentation-index) for the complete list, including per-mechanism docs (OBA, CCR, feedback options, sectors, technology transition).

## License / Citation

GPL-3.0-or-later. See [LICENSE](LICENSE).
