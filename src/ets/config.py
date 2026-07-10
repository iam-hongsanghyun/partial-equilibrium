# Backward-compatibility shim — re-exports from core.paths.
# New location: src/ets/core/paths.py.
# Importing this module runs core.paths, which performs the MPLCONFIGDIR
# os.environ.setdefault side effect exactly as before the move.
# Armed in the app-tier tidy order (v1 O13 / v2 O17): the internal importers
# (cli.py, web/*) now read ets.core.paths directly.
import warnings

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

warnings.warn(
    "ets.config is deprecated; import from ets.core.paths instead. "
    "Removal milestone: 0.3.0.",
    DeprecationWarning,
    stacklevel=2,
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
