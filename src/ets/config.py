# Backward-compatibility shim — re-exports from core.paths.
# New location: src/ets/core/paths.py.
# Importing this module runs core.paths, which performs the MPLCONFIGDIR
# os.environ.setdefault side effect exactly as before the move.
# DeprecationWarning arms in O13 (milestone 0.3.0), once the remaining
# internal importers (cli.py, web/*) are rewritten — see
# docs/feature-modules-plan.md §4.

from .core.paths import (
    PROJECT_DIR,
    SRC_DIR,
    FRONTEND_DIR,
    FRONTEND_DIST_DIR,
    EXAMPLES_DIR,
    DOCS_DIR,
    SERVERLESS_ROOT,
    MPLCONFIG_DIR,
    USER_SCENARIOS_DIR,
)

__all__ = [
    "PROJECT_DIR",
    "SRC_DIR",
    "FRONTEND_DIR",
    "FRONTEND_DIST_DIR",
    "EXAMPLES_DIR",
    "DOCS_DIR",
    "SERVERLESS_ROOT",
    "MPLCONFIG_DIR",
    "USER_SCENARIOS_DIR",
]
