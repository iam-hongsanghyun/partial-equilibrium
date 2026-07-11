"""Deprecated mirror of ``pe.core.market.product_clearing`` — import ``pe.core.market.product_clearing`` instead.

Kept for the ets->pe rename window (D0-R1); removed at 0.4.0.
"""

import warnings

from pe.core.market.product_clearing import *  # noqa

warnings.warn(
    "ets.core.market.product_clearing is deprecated; import "
    "pe.core.market.product_clearing instead. Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)
