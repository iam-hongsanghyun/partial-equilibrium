"""Deprecated mirror of ``pe.engine.joint`` — import ``pe.engine.joint`` instead.

Kept for the ets->pe rename window (D0-R1); removed at 0.4.0.
"""

import warnings

from pe.engine.joint import *  # noqa

warnings.warn(
    "ets.engine.joint is deprecated; import pe.engine.joint instead. "
    "Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)
