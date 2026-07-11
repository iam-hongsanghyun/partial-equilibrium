"""
Market Stability Reserve (MSR) for ETS.

The MSR is a non-linear supply-adjustment mechanism that:
  - WITHHOLDS allowances from auction when the total banked volume is too high
    (excessive surplus → deflationary price pressure)
  - RELEASES previously withheld allowances when the bank is too low
    (shortage → inflationary price pressure)

Rule (applied before each year's auction):

    if total_bank > upper_threshold:
        withheld = min(msr_withhold_rate × auction_offered, auction_offered)
        reserve_pool += withheld
        effective_auction -= withheld

    elif total_bank < lower_threshold and reserve_pool > 0:
        released = min(msr_release_rate, reserve_pool)
        reserve_pool -= released
        effective_auction += released

The reserve_pool accumulates withheld allowances and persists across years.
Allowances cancelled by the MSR (if msr_cancel_excess=True) are permanently
removed once the pool exceeds msr_cancel_threshold.

Moved from ``solvers/msr.py`` in the engine work order (v1 O8 / v2 O12,
``docs/feature-modules-plan.md``); this module holds the mutable state
object, ``rules.py`` the ``CapRule``/``SupplyRule`` implementations, and
``decree.py`` the K-MSR draft-decree rule. ``ets/solvers/msr.py`` remains as
a re-export shim.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MSRState:
    """
    Mutable state object carried across years for a single scenario.
    """

    def __init__(self, initial_reserve: float = 0.0) -> None:
        self.reserve_pool: float = float(initial_reserve)

    def apply(
        self,
        total_bank: float,
        auction_offered: float,
        upper_threshold: float,
        lower_threshold: float,
        withhold_rate: float,
        release_rate: float,
        cancel_excess: bool = False,
        cancel_threshold: float = 0.0,
        year_label: str = "",
    ) -> tuple[float, float, float]:
        """
        Apply MSR rule and return adjusted auction volume.

        Returns
        -------
        effective_auction : float   – auction supply after MSR adjustment
        withheld          : float   – Mt withheld this year (0 if no withholding)
        released          : float   – Mt released this year (0 if no release)
        """
        withheld = 0.0
        released = 0.0

        if total_bank > upper_threshold:
            withheld = min(withhold_rate * auction_offered, auction_offered)
            self.reserve_pool += withheld
            logger.debug(
                f"MSR [{year_label}]: bank={total_bank:.1f} > upper={upper_threshold:.1f} "
                f"→ withheld {withheld:.1f} Mt, pool now {self.reserve_pool:.1f} Mt"
            )

        elif total_bank < lower_threshold and self.reserve_pool > 0.0:
            released = min(release_rate, self.reserve_pool)
            self.reserve_pool -= released
            logger.debug(
                f"MSR [{year_label}]: bank={total_bank:.1f} < lower={lower_threshold:.1f} "
                f"→ released {released:.1f} Mt, pool now {self.reserve_pool:.1f} Mt"
            )

        # Optional: cancel allowances that have been in the pool too long
        if cancel_excess and self.reserve_pool > cancel_threshold:
            cancelled = self.reserve_pool - cancel_threshold
            self.reserve_pool = cancel_threshold
            logger.debug(
                f"MSR [{year_label}]: pool cancellation {cancelled:.1f} Mt "
                f"(pool > cancel_threshold {cancel_threshold:.1f})"
            )

        effective_auction = max(0.0, auction_offered - withheld + released)
        return effective_auction, withheld, released

