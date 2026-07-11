# Vertical-Slice Restructure — Design Plan (D0-VS)

Second rename-scale, import-name-preserving physical move. Owner's chosen
target: co-locate each module's backend + frontend + doc as a vertical slice;
peel `core/` out as the shared kernel slice. **No math changes. No golden
number moves.** The golden gate stays bit-identical (39/39) and the `ets.*`
compat mirror keeps working because every import name is invariant.

Status when this plan was written (verified, not assumed):
- branch `feat/platform-d0`; `src/pe` is the real package, `src/ets` a full
  compat mirror that re-exports `pe.*` **by name**.
- 28 `pe` packages (see enumeration below) + top-level modules `pe.cli`,
  `pe.model_store`; 14 feature packages under `pe.features.*`.
- Vercel imports `pe` via `api/index.py` `sys.path.insert(src)` +
  `vercel.json includeFiles: src/pe/**` — **it does NOT install the project**
  (`requirements.txt` lists only numpy/pandas/scipy/matplotlib/tabulate).
- `frontend/dist` is **committed** (4 tracked files); no build step in Vercel
  or CI — the committed dist is served directly.
- Editable-install of a `package_dir`-split `pe` was **empirically proven**
  (throwaway probe): `import pe.features.msr` resolves from a neutral cwd with
  no `src/` on path, feature importing back into `pe` across the split.

---

## 0. The load-bearing constraint (why this is a design task)

A **split package is not `sys.path`-reconstructable.** `pe` root + `pe.core` +
`pe.engine` in `core/backend/`, and `pe.features.<name>` in
`modules/<name>/backend/`, cannot be reunited by putting those directories on
`PYTHONPATH` — Python maps one regular package to one location, and
`modules/msr/backend/` is not physically named `pe/features/msr/`. Only the
**installed package** (wheel on Vercel, editable locally) carries the
`package_dir` finder that redirects import names to physical dirs.

Consequence that drives the whole sequence: **every place that today imports
`pe` via `sys.path`+`src/` must first switch to importing the installed
package.** That switch is validatable with zero physical moves, so it goes
first (WO-0) and de-risks the scariest thing (Vercel) before a single file
relocates.

The `src/` touchpoints (the "six-touchpoint" surface, enumerated):
1. `pyproject.toml` `[tool.setuptools.packages.find] where=["src"]`
2. `pyproject.toml` `[tool.pytest.ini_options] pythonpath=["src"]`
3. `api/index.py` `SRC_DIR = PROJECT_DIR/"src"; sys.path.insert(...)`
4. `app.py`, `ets_framework.py` (launcher shims) `sys.path.insert(src)`
5. `run.command`, `pe.command`, `configure.command` `export PYTHONPATH=$SRC`
   and the pip-fallback that installs `-r requirements.txt` (NOT `-e .`)
6. `vercel.json` `includeFiles: src/pe/**, src/ets/**`
Plus two physical-path assumptions to audit: `src/pe/core/paths.py`
`parents[3]` and `tests/test_module_isolation.py` `_PKG_ROOT = src/pe`.

---

## 1. PYTHON — physical-path -> import-name mapping (DECISION)

**Chosen: (a) explicit `[tool.setuptools.package-dir]` per-package remap +
explicit `[tool.setuptools.packages]` list.** Evaluated against the four
options:

- (a) explicit `package-dir` — **chosen.** Only option that (i) keeps import
  names byte-identical, (ii) works with `uv sync` editable AND a Vercel wheel
  (proven by probe), (iii) adds exactly **one `packages` line + one
  `package-dir` line per feature module** — the per-module ceremony the owner
  already accepts. `find()` cannot span `core/backend` + `modules/*/backend`
  under one `pe` namespace, so packages are enumerated. Verbose but explicit,
  debuggable, and on-brand with the six-touchpoint doctrine.
- (b) src-layout with a thin `src/pe/` of namespace re-export packages —
  **rejected**: reintroduces the split it was meant to remove, and namespace
  packages can't span into arbitrarily-named `modules/*/backend` dirs.
- (c) custom build/editable finder — **rejected**: bespoke code to maintain,
  no upside over setuptools' own `package_dir` finder which already does this.
- (d) `src/pe` real + `modules/*` symlinks (or reverse) — **rejected**:
  symlinks-in-git are fragile on the Vercel builder and break the "physical
  layout IS the vision" goal; a symlink farm is a worse split than (b).

### 1a. Which physical dir maps to which import name (the refinement)

The vision line `core/backend/ <- src/pe/core/**` is shorthand. Taken
literally (kernel flattened directly into `core/backend/`) it would (i) force
a separate top-level home for every non-core `pe` subpackage
(engine/web/config_io/…), exploding ceremony to one `package_dir` line **per
subpackage**, and (ii) **break `paths.py`** — `PROJECT_DIR =
parents[3]` counts physical depth, and flattening changes the depth.

**Recommended reading (flag for one-word owner confirm):** `core/backend/` is
the `pe` **package root** — the whole non-feature backend moves as one block.

| import name | physical dir |
|---|---|
| `pe` (root `__init__`, `cli.py`, `model_store.py`) | `core/backend/` |
| `pe.core` (kernel: market/ participant/ ledger costs defaults expectations investment baseline paths logger protocols) | `core/backend/core/` |
| `pe.config_io` `pe.engine` `pe.blocks` `pe.analysis` `pe.coupling` `pe.web` `pe.mcp` `pe.mcp.models` | `core/backend/<same>/` |
| `pe.features` (namespace `__init__` only) | `core/backend/features/` |
| `pe.features.<name>` | `modules/<name>/backend/` |
| `ets.*` (compat mirror, removed 0.4.0) | `compat/ets/` |

Decisive property: `core/backend/core/paths.py` sits at depth 3 from repo
root — **identical to `src/pe/core/paths.py`** — so `parents[3]` is unchanged
and `paths.py` needs **zero edits** for `PROJECT_DIR`. (Its one required edit
is `FRONTEND_DIST_DIR`; see §2.) This is why the kernel lives at
`core/backend/core/`, not flattened into `core/backend/`.

`pe.engine` decision (brief point 6): engine stays **`core/backend/engine`**
(part of the core backend block, tier T3). `market_links` and the D2 joint/scc
engine land as **`modules/market_links/backend`** (`pe.features.market_links`)
— a feature slice, not core — because they are policy mechanisms wired through
`pe.engine`, exactly like every other T2 feature. `pe.engine` remains the
pure orchestration kernel; only the coupling/scc *mechanism* is a module.

### 1b. Exact target `pyproject.toml` (delta)

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

# --- vertical-slice remap: find() cannot span core/backend + modules/*/backend
# under one `pe` namespace, so packages are enumerated and each physical root
# is remapped to its import name. One `packages` entry + one `package-dir`
# entry per feature module. ---
[tool.setuptools]
packages = [
    # pe root + non-feature backend  (physically under core/backend/)
    "pe",
    "pe.core", "pe.core.market", "pe.core.participant",
    "pe.config_io", "pe.engine", "pe.blocks",
    "pe.analysis", "pe.coupling", "pe.web",
    "pe.mcp", "pe.mcp.models",
    "pe.features",                              # namespace __init__ only
    # feature modules  (physically under modules/<name>/backend/)
    "pe.features.banking", "pe.features.cbam", "pe.features.ccr",
    "pe.features.competitive", "pe.features.elastic_baseline",
    "pe.features.endogenous_investment", "pe.features.hoarding",
    "pe.features.hotelling", "pe.features.msr", "pe.features.nash_cournot",
    "pe.features.oba", "pe.features.price_controls", "pe.features.sectors",
    "pe.features.transmission",
    # deprecated ets compat mirror (physically under compat/ets/, removed 0.4.0).
    # Full list mechanically generated: `find compat/ets -name __init__.py`.
    "ets", "ets.core", "ets.core.market", "ets.core.participant",
    "ets.config_io", "ets.engine", "ets.blocks", "ets.analysis",
    "ets.coupling", "ets.web", "ets.mcp", "ets.mcp.models", "ets.features",
    "ets.solvers", "ets.market", "ets.participant",
]

[tool.setuptools.package-dir]
"pe"  = "core/backend"
"ets" = "compat/ets"
"pe.features.banking"                = "modules/banking/backend"
"pe.features.cbam"                   = "modules/cbam/backend"
"pe.features.ccr"                    = "modules/ccr/backend"
"pe.features.competitive"            = "modules/competitive/backend"
"pe.features.elastic_baseline"       = "modules/elastic_baseline/backend"
"pe.features.endogenous_investment"  = "modules/endogenous_investment/backend"
"pe.features.hoarding"               = "modules/hoarding/backend"
"pe.features.hotelling"              = "modules/hotelling/backend"
"pe.features.msr"                    = "modules/msr/backend"
"pe.features.nash_cournot"           = "modules/nash_cournot/backend"
"pe.features.oba"                    = "modules/oba/backend"
"pe.features.price_controls"         = "modules/price_controls/backend"
"pe.features.sectors"                = "modules/sectors/backend"
"pe.features.transmission"           = "modules/transmission/backend"

[tool.pytest.ini_options]
# pythonpath=["src"] DROPPED — a split package is not sys.path-reconstructable;
# tests import the editable-installed `pe` (uv sync / pip install -e .).
testpaths = ["tests"]
```

Editable-mode note: setuptools ≥64 emits a MetaPathFinder for the remap
(proven by probe). If the default finder ever misbehaves on the split, the
documented fallback is `pip install -e . --config-settings
editable_mode=compat`; the import-sweep smoke (§6) is the acceptance test.

---

## 2. FRONTEND — Vite finds `modules/<name>/frontend` + `core/frontend` (DECISION)

**Chosen: the Vite project root moves into `core/frontend/`** (honors the
vision — no orphan top-level `frontend/`), and `registry.js` lands at
`core/frontend/src/registry.js`. Module fragments live at
`modules/<name>/frontend/index.jsx`. Two path aliases keep per-module import
churn mechanical and deep-`../../../` free.

Target frontend layout:
```
core/frontend/
  package.json  vite.config.js  index.html  public/  dist/  node_modules/(gitignored)
  src/
    main.jsx  app.jsx  registry.js      <- moved from frontend/src/features/registry.js
    components/*  composer/*  pe/*
modules/<name>/frontend/index.jsx        <- moved from frontend/src/features/<name>/index.jsx
```

`vite.config.js` delta (at `core/frontend/vite.config.js`):
```js
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

const repoRoot = resolve(__dirname, "..", "..");   // core/frontend -> core -> repo

export default defineConfig({
  root: __dirname,                                 // core/frontend
  plugins: [react()],
  publicDir: resolve(__dirname, "public"),
  resolve: {
    alias: {
      "@core": resolve(__dirname, "src"),          // shell primitives
      "@features": resolve(repoRoot, "modules"),   // module fragments
    },
  },
  server: { fs: { allow: [repoRoot] } },           // dev server may read modules/* outside root
  build: { outDir: resolve(__dirname, "dist"), emptyOutDir: true },
});
```

Import rewrites (mechanical, alias-based):
- `core/frontend/src/registry.js`: `import msr from "./msr/index.jsx"` ->
  `import msr from "@features/msr/frontend/index.jsx"` (×13, static literal —
  one reviewed file, unchanged shape: still a frozen literal, no dynamic reg).
- each `modules/<name>/frontend/index.jsx`: `../../components/EditorPrimitives.jsx`
  -> `@core/components/EditorPrimitives.jsx` (and `AppShared`, `ResultPrimitives`,
  `MarketChart`). The five shell-consumers of `registry.js`
  (`AppShared`/`Editor`/`AppViews`/`ParticipantPanel`/`GuideView`) change
  `../features/registry.js` -> `./registry.js` (now a sibling in `src/`).
- `index.html` keeps `<script src="/src/main.jsx">` (relative to the new root).

Dist / serve contract (must keep working):
- `frontend/dist` (committed) -> git-mv to `core/frontend/dist`.
- `pe.core.paths.FRONTEND_DIST_DIR`: change `FRONTEND_DIR = PROJECT_DIR /
  "frontend"` -> `PROJECT_DIR / "core" / "frontend"`. (`FRONTEND_DIST_DIR`
  derives from it; `pe.web.handlers`/`server` are unchanged — they import the
  constant.)
- `vercel.json` includeFiles: `frontend/dist/**` -> `core/frontend/dist/**`.
- `.gitignore`: `frontend/node_modules/` -> `core/frontend/node_modules/`.
- `package.json` scripts unchanged (`dev`/`build`/`preview`); developers now
  run them from `core/frontend/`. `package-lock.json` moves with `package.json`.

Rejected alternative (Choice K, keep dist at repo-root `frontend/`): lower
path-churn (zero backend/Vercel edits) but leaves an orphan `frontend/`
toolchain dir the vision doesn't name and splits the shell from its build root.
Choice V (above) is preferred; the dist-path edit is a single gated step with a
serve smoke, so the extra risk is contained.

---

## 3. TESTS — central tree (DECISION)

**Keep `tests/` central; do NOT co-locate under `modules/*/backend/tests/`.**
Reasons: (i) the golden gate, Appendix-B anchors, and the isolation ratchet
are **cross-cutting** — they cannot live inside any one module; (ii)
`testpaths=["tests"]` + one discovery root is simplest and is what the gate
runs; (iii) the O18 precedent ("tests mirror src") means the *internal* tests
tree mirrors the logical package tree — which the central `tests/{core,
features,engine,config_io,coupling,blocks,analysis,apps,workflows,baselines}`
already does — not that tests move into `src`. Tests import `pe.*`/`ets.*` **by
name** via the editable install, so they are location-invariant under the move.
Reorganizing the internal `tests/` layout is explicitly **out of scope** for
this paths-only move (a later optional order can mirror `modules/` inside
`tests/features/` if desired).

---

## 4. ISOLATION RATCHET — confirmed, and the required edit

Read and confirmed: `tests/test_module_isolation.py` **classifies by import
name** (`classify()` on `pe.core.*`/`pe.features.*` dotted strings), so all
tier logic (clauses a–h, the flipped empty allowlist) **survives** a move that
preserves import names — *provided the walker still produces correct dotted
names.* It does not today: two functions assume the `src/pe` physical layout
and **must be updated** (this is the one non-golden code edit the ratchet
needs):

- `_PKG_ROOT = _SRC_ROOT / "pe"` and `_iter_py_files()` (`_PKG_ROOT.rglob`) —
  walk `src/pe` by path.
- `_module_name_for(path)` — maps physical path -> dotted name via
  `relative_to(_SRC_ROOT)`, which would yield `core.backend.core.market...`
  instead of `pe.core.market...`.

Required rewrite (mirrors `[tool.setuptools.package-dir]` — a small
root->prefix table, no tier logic touched):
```python
# physical root -> import-name prefix (mirrors package-dir)
_ROOTS: dict[Path, str] = {_REPO_ROOT / "core" / "backend": "pe"}
for _b in sorted((_REPO_ROOT / "modules").glob("*/backend")):
    _ROOTS[_b] = f"pe.features.{_b.parent.name}"

def _iter_py_files() -> Iterator[Path]:
    for root in _ROOTS:
        yield from sorted(root.rglob("*.py"))

def _module_name_for(path: Path) -> str:
    for root, prefix in _ROOTS.items():
        if root in path.parents or root == path.parent:
            rel = list(path.relative_to(root).with_suffix("").parts)
            if rel and rel[-1] == "__init__":
                rel = rel[:-1]
            return ".".join([prefix, *rel]) if rel else prefix
    raise AssertionError(path)
```
`_package_name_for` gets the analogous change (drop the last part). The ratchet
does **not** walk `compat/ets` (it never walked `ets`). Acceptance: the whole
tier suite stays green after the move — proof that import names are preserved.

---

## 5. SEQUENCING — hybrid: atomic toolchain + atomic core relocation, then
   independently-gated peels

The rename argued "one order is safer (no half-moved tree)." That holds for
the **core relocation** (a half-moved `pe` package is unimportable — WO-1 must
be atomic). But two things the rename didn't have change the calculus:
1. the **toolchain switch** (sys.path-import -> installed-import) is
   validatable with **zero moves**, so it goes first and de-risks Vercel; and
2. each `pe.features.<name>` remaps **independently** via its own
   `package-dir` line, so the feature peels can be **one-per-step, each green
   on the full gate** — my "one extraction per step" discipline, recovered.

Ordered work orders (each ends green on the FULL gate, §6):

- **WO-0 — Toolchain switch (NO physical moves).** Make the project the
  installed source of `pe` everywhere: `run.command`/`pe.command`/
  `configure.command` pip-fallback runs `pip install -e ".[dev]"` (not just
  `-r requirements.txt`) and drops `export PYTHONPATH=$SRC`; `requirements.txt`
  gains `.` (Vercel builds+installs the wheel); `vercel.json` drops the
  `sys.path` reliance by keeping `src/pe/**` includes **for now** (still valid,
  pe unmoved) but adding pyproject to the build inputs; `api/index.py`/`app.py`/
  `ets_framework.py` keep their `sys.path` inserts (harmless, still valid).
  `pyproject`: drop `pythonpath=["src"]`, rely on editable install for pytest.
  *This proves the install-based import path + a Vercel preview deploy while
  `pe` is still at `src/pe` — the scariest change, isolated.* Gate + Vercel
  preview smoke. Size: 6 files, ~20 lines.

- **WO-1 — Relocate the core backend block (ATOMIC).** `git mv src/pe ->
  core/backend` (whole tree incl. features-in-transit at
  `core/backend/features/<name>`); `git mv src/ets -> compat/ets`. Rewrite
  `pyproject` `[tool.setuptools]` to the explicit `packages` + `package-dir`
  of §1b **minus the 14 feature remaps** (features still at
  `core/backend/features/*` this step, so they resolve as `pe.features.*`
  without a remap line yet — one clean cutover). Update `vercel.json`
  includeFiles `src/pe/**`->`core/backend/**`, `src/ets/**`->`compat/ets/**`.
  Update `test_module_isolation.py` walker (§4) — at this step `_ROOTS` is just
  `{core/backend: "pe"}`. `paths.py` `parents[3]` **verified unchanged** (no
  edit). `rm -rf src/`. Gate. Size: ~95 files moved, ~30 config lines.

- **WO-2 … WO-15 — Peel each feature module (one per step).** For each of
  banking, cbam, ccr, competitive, elastic_baseline, endogenous_investment,
  hoarding, hotelling, msr, nash_cournot, oba, price_controls, sectors,
  transmission: add its `packages` + `package-dir` line, `git mv
  core/backend/features/<name> -> modules/<name>/backend`, extend the ratchet
  `_ROOTS` (already auto-globs `modules/*/backend`, so no edit — it discovers
  the new dir). Gate after each — import name `pe.features.<name>` is invariant,
  so goldens stay bit-identical every step. Size: 1 dir + 2 config lines each.

- **WO-16 — Frontend relocation (Choice V, §2).** `git mv` shell -> 
  `core/frontend/src`, `registry.js` -> `core/frontend/src/registry.js`, each
  `frontend/src/features/<name>/index.jsx` -> `modules/<name>/frontend/index.jsx`,
  toolchain files (`package.json`, `package-lock.json`, `vite.config.js`,
  `index.html`, `public/`) + committed `dist/` -> `core/frontend/`. Apply the
  `vite.config.js` alias/fs delta, the alias-based import rewrites, `paths.py`
  `FRONTEND_DIR` edit, `vercel.json` dist-path edit, `.gitignore` edit. Gate +
  frontend build smoke (`npm ci && npm run build`, diff regenerated vs
  committed dist) + web serve smoke. Size: ~30 JS files + 4 dist + 5 config.

- **WO-17 — Doc fold (§7).** Move mechanism reference papers into
  `modules/<name>/doc/reference.md` and cross-cutting into `core/doc/`; create
  empty `doc/` slots for feature-only modules. Gate (link-check + full suite —
  docs change no math). Size: ~12 doc moves.

Reserved, untouched by this plan (owned by the registry-DB agent): top-level
`database/` and `registry/` slots, and the `.worktrees/registry-db/` worktree.

---

## 6. THE FULL GATE + SMOKES (run after every WO)

Exactly as the rename order defined it, extended for the split package:
1. `uv sync --all-extras` — rebuilds the editable install with the current
   `package_dir`; must succeed (this is where a bad remap fails fast).
2. **Import sweep**: `uv run python -c "import pe, ets, pe.cli, pe.web.server,
   pe.mcp, pe.mcp.models, pe.model_store; import pe.features.msr, ...(all 14)"`
   — from repo root AND a neutral cwd, every `pe.*`/`ets.*` name resolves with
   no `src/` on path.
3. `uv run pytest` — full suite (currently 782 passed), including:
   - `tests/test_golden_baselines.py` — **39/39 bit-identical** (the number-
     preservation proof; any drift ⇒ a file was altered, not moved ⇒ STOP).
   - `tests/test_paper_appendix_b.py` — Appendix-B anchors.
   - `tests/test_module_isolation.py` — tier ratchet on the new walker roots.
   - `tests/test_shim_deprecations.py` — `ets.*` DeprecationWarnings intact.
4. Launcher smokes: `./run.command samples`, `uv run python -m pe.cli
   --list-modes`, and `app.py`/`ets_framework.py` still import (with warning).
5. MCP smokes: `uv run python -m pe.mcp` and `-m pe.mcp.models` import + one
   `list_models()` tool call.
6. Frontend smokes (WO-16+): `cd core/frontend && npm ci && npm run build`;
   regenerated `dist` matches committed; start `pe.web`, curl `/` (index.html),
   `/assets/*`, `/api/templates`.
7. **Vercel smoke**: `vercel build` locally (or a preview deploy) — `from
   pe.web.server import app` resolves from the installed wheel and dist serves.

Golden-invariance argument: every WO is `git mv` (byte-identical file content)
+ import-name-preserving remap. The solver bytes never change, so
`test_golden_baselines` **cannot** move a decimal. If it does, the move
corrupted content — revert (never edit a golden to "fix" a move).

---

## 7. DOC FOLD — mapping + sizes (approved disposition)

Into `modules/<name>/doc/reference.md`:
| module | source doc(s) | ~lines |
|---|---|---|
| banking | banking-equilibrium.md | 152 |
| ccr | carbon-cap-rule.md | 137 |
| transmission | forward-transmission.md | 144 |
| oba | oba-allocation.md | 197 |
| sectors | sector-config.md | 350 |
| endogenous_investment | technology-transition.md + invest-feedback-spec.md (merge) | 452 |
| elastic_baseline | feedback-price-elastic-baseline.md | 80 |

Into `core/doc/`: mac-abatement.md (322), market-equilibrium.md (253),
multi-year-simulation.md (593), data-model.md (695).

Empty `doc/` slots (no mechanism paper in the approved list yet): cbam,
competitive, hoarding, hotelling, msr, nash_cournot, price_controls. Candidate
follow-up (not in the approved fold, flagged): the `k-msr-*` trio (condensed
126 / ko-translation 230 / vs-repo 359) are msr's reference papers — fold into
`modules/msr/doc/` under a separate owner-approved order.

**Deviation from "delete the spent *-plan.md" (reasoned, requires a call):**
`invest-feedback-plan.md` is referenced by **16** live code/test files,
`blocks-graph-plan.md` by **14**, `feature-modules-plan.md` by **58**. Deleting
them during a paths-only move would strand those references (churn far beyond
"imports/paths only", and none are golden-affecting). Recommendation: in this
move **delete nothing**; move only the mechanism/cross-cutting reference papers
above. Retire the referenced plans in a **separate doc-hygiene order** that also
sweeps the 58/14/16 docstring references. `joint-equilibrium-plan.md` and
`platform-plan-d0-d1.md` (0 refs) are **in-flight D1/D2** — keep until D2 lands.
`docs/` remains for cross-cutting/platform/paper docs; `pe.core.paths.DOCS_DIR
= PROJECT_DIR/"docs"` (web-served) is therefore **unchanged**.

---

## 8. COMPOSITION WITH IN-FLIGHT WORK

- **registry-DB build** (`.worktrees/registry-db/`): this plan only **reserves**
  top-level `database/` (`registry.sqlite`) and `registry/` (store code) slots
  and touches neither. `pe.model_store` (the transport-free registry I/O) stays
  in `core/backend/model_store.py` — it is core backend, not a module.
- **D0-vocab / D1 / D2**: future mechanism work builds **into**
  `modules/<name>/{backend,frontend,doc}`. `market_links` (D1) and the joint/scc
  engine (D2) land as `modules/market_links/backend` = `pe.features.market_links`
  (a feature slice wired through `pe.engine`), **not** in `core/backend/engine`.
  Each new module = one `packages` line + one `package-dir` line + a
  `modules/<name>/` tree; the ratchet auto-discovers it (`_ROOTS` globs
  `modules/*/backend`).
- **`ets.*` compat mirror**: it re-exports `pe.*` **by name**, so relocating
  `pe`'s physical home is **invisible** to it — confirmed by reading the shims
  (`compat/ets/msr.py` does `from pe.features.msr import MSRState`; the name is
  unchanged). It moves as a block to `compat/ets/` in WO-1 and keeps warning
  and re-exporting. Removed at 0.4.0, its enumeration in `packages` shrinks to
  nothing.

---

## 9. RISKS + MITIGATIONS

| risk | mitigation |
|---|---|
| **Split package unimportable outside an install** (the core hazard) | WO-0 switches every entrypoint to the installed package **before** any move; proven by the editable probe. Import-sweep from a neutral cwd is gate step 2. |
| **Vercel imports via `sys.path`, not install** — split would 500 in prod | WO-0 adds `.` to `requirements.txt` so Vercel builds+installs the wheel (package_dir baked in); Vercel preview smoke is gate step 7, run first while `pe` is still at `src/pe`. |
| **`per-module pyproject entries drift`** (a new module forgotten) | The ratchet `_ROOTS` globs `modules/*/backend`, so a physical module with **no** `package-dir` line still gets walked; the import-sweep + `uv sync` fail loudly if a module isn't installable. One-line-per-module is mechanical and reviewed. |
| **`paths.py parents[3]`** breaks on depth change | Kernel placed at `core/backend/core/` = depth 3 (identical to `src/pe/core/`) — `parents[3]` **unchanged**, verified; only `FRONTEND_DIR` edits (WO-16). |
| **Vite can't resolve `modules/*` outside root** | `server.fs.allow=[repoRoot]` + `@features`/`@core` aliases; frontend build smoke diffs regenerated vs committed dist. |
| **Second-rename blast radius** (half-moved tree) | WO-1 (core relocation) is **atomic**; feature peels are independent and each fully gated; `src/` deleted only after WO-1 is green. |
| **Editable finder edge cases on the remap** | Documented fallback `editable_mode=compat`; import-sweep is the acceptance test. |
| **Stranded doc references** (58/14/16) | Delete no referenced plan in this move; defer to a reference-sweeping doc order (§7). |
| **A golden number moves** | Cannot happen from `git mv` + name-preserving remap; if `test_golden_baselines` drifts, content was corrupted — revert, don't rebaseline. |

---

## 10. TARGET DEPENDENCY DIAGRAM + TREE

Import-name dependency arrows (unchanged by the move — physical layout only):

```
                      pe.web / pe.cli / pe.mcp            (T5 apps)
                              |
                        pe.analysis                        (T4 workflows)
                     pe.blocks   pe.coupling
                              |
                          pe.engine                        (T3 orchestration)
                              |
              +---------------+----------------+
              |                                |
        pe.features.<name>              pe.config_io        (T2 / T1)
        (modules/*/backend)                    |
              |            \                    |
              |             \  (plugin door)    |
              v              -----------------> v
           pe.core  <----------------------  pe.core        (T0 kernel)
        (core/backend/core: market, participant, ledger,
         costs, defaults, expectations, investment, baseline,
         protocols, paths, logger)

        Allowed: web -> analysis -> engine -> {features, config_io} -> core.
        Forbidden (ratchet-enforced): feature->feature, feature->config_io,
        core->anything-but-core, config_io->non-plugin feature, engine->apps.

   ets.* (compat/ets)  --re-exports by NAME-->  pe.*   (deprecated, 0.4.0)

   Frontend:  core/frontend/src/registry.js  --@features-->
              modules/<name>/frontend/index.jsx  --@core-->  core/frontend/src/components/*
   Serve:     pe.web (FRONTEND_DIST_DIR) + Vercel  <--  core/frontend/dist (committed)
```

Target repository tree:
```
core/
  backend/            -> pe            (root __init__, cli.py, model_store.py)
    core/             -> pe.core       (market/ participant/ ledger costs ... paths logger)
    config_io/ engine/ blocks/ analysis/ coupling/ web/ mcp/(models/)
    features/__init__ -> pe.features   (namespace init only)
  frontend/           (Vite root: package.json vite.config.js index.html public/ dist/ src/)
    src/ main.jsx app.jsx registry.js components/ composer/ pe/
  doc/                (mac-abatement, market-equilibrium, multi-year-simulation, data-model)
modules/
  <name>/
    backend/          -> pe.features.<name>
    frontend/         index.jsx (+ module-owned components)     [omit for backend-only modules]
    doc/              reference.md                              [omit where no paper yet]
compat/
  ets/                -> ets.*         (re-exports pe.* by name; removed 0.4.0)
database/             (RESERVED — registry-DB agent; registry.sqlite)
registry/             (RESERVED — registry-DB agent; store code)
docs/                 (cross-cutting/platform/paper; DOCS_DIR, web-served — unchanged)
tests/                (central; mirrors the logical package tree)
api/index.py  vercel.json  pyproject.toml  requirements.txt  *.command  app.py  ets_framework.py
```
