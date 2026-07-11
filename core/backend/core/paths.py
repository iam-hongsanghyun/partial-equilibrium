from __future__ import annotations

import os
import tempfile
from pathlib import Path

# PE_PROJECT_DIR anchors the data root explicitly when `pe` is installed from a
# wheel away from the repo checkout (Vercel: WO-0 switched to `pip install .`
# from requirements.txt, so this file resolves inside site-packages and
# parents[3] no longer points at the repo). Deployment entry points
# (api/index.py, the .command launchers) set it before importing `pe`; local
# editable installs and the test suite leave it unset, so parents[3] — the
# repo root, since this file sits at <repo>/core/backend/core/paths.py — is
# used unchanged (bit-identical to before this env var existed).
if os.environ.get("PE_PROJECT_DIR"):
    PROJECT_DIR = Path(os.environ["PE_PROJECT_DIR"]).resolve()
else:
    # parents[3]: this file moved one level deeper (ets/config.py -> ets/core/paths.py),
    # so the repo root is one more parent up. Same directory as before the move.
    PROJECT_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_DIR / "src"
FRONTEND_DIR = PROJECT_DIR / "core" / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
EXAMPLES_DIR = PROJECT_DIR / "examples"
DOCS_DIR = PROJECT_DIR / "docs"
SERVERLESS_ROOT = Path(tempfile.gettempdir()) / "ets_runtime"

if os.environ.get("VERCEL"):
    MPLCONFIG_DIR = SERVERLESS_ROOT / ".mplconfig"
    USER_SCENARIOS_DIR = SERVERLESS_ROOT / "user-scenarios"
    DATABASE_DIR = SERVERLESS_ROOT / "database"
else:
    MPLCONFIG_DIR = PROJECT_DIR / ".mplconfig"
    USER_SCENARIOS_DIR = PROJECT_DIR / "user-scenarios"
    DATABASE_DIR = PROJECT_DIR / "database"

os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIG_DIR))
