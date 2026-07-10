"""Centralized logger factory for the ETS package (T0 kernel).

Logging policy (CLAUDE.md "Logging"): log shape and dtype, never full
arrays; never log secrets, PII, or raw data rows. Levels: DEBUG for branch
decisions, scalar values, and shapes; INFO for milestones (data loaded, fit
complete); WARNING for recoverable degradation; ERROR for a failure that
returns or skips; CRITICAL for abort.

New in work order O1 (docs/feature-modules-plan.md §4). Existing modules
keep their ``logging.getLogger(__name__)`` calls unchanged this order;
rewiring onto this factory is a later work order.
"""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Return the package logger for `name`.

    Args:
        name: Dotted logger name, conventionally the caller's ``__name__``
            (so web warning capture, which is scoped to ``ets.*`` loggers,
            keeps working).

    Returns:
        The standard-library logger for `name`.
    """
    return logging.getLogger(name)
