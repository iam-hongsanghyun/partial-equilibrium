"""Deprecated mirror of ``pe.core.participant.producer`` — import ``pe.core.participant.producer`` instead.

Kept for the ets->pe rename window (D0-R1); removed at 0.4.0.
"""

import warnings

from pe.core.participant.producer import *  # noqa

warnings.warn(
    "ets.core.participant.producer is deprecated; import pe.core.participant.producer instead. "
    "Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)
