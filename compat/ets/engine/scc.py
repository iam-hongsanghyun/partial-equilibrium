"""Deprecated mirror of ``pe.engine.scc`` — import ``pe.engine.scc`` instead.

Kept for the ets->pe rename window (D0-R1); removed at 0.4.0.
"""

import warnings

from pe.engine.scc import *  # noqa

warnings.warn(
    "ets.engine.scc is deprecated; import pe.engine.scc instead. "
    "Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)
