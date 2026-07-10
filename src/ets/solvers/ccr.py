r"""
Carbon Cap Rule (CCR) for ETS.

Reference
---------
Benmir, G., Roman, J. and Taschini, L. (2025). "Weitzman meets Taylor: EU
allowance price drivers and carbon cap rules." Grantham Research Institute on
Climate Change and the Environment, Working Paper No. 421, London School of
Economics and Political Science.

The CCR is a rule-based, *adaptive* cap mechanism — the cap-and-trade analogue
of a Taylor rule in monetary policy. Instead of a fixed per-period cap, the
regulator adjusts the quantity of permits issued in each period in response to
how far two observable drivers have drifted from their de-trended steady-state
(reference) levels:

  - aggregate emissions e_t  (deviation from reference ē)
  - aggregate abatement cost z_t  (deviation from reference z̄)

By aligning permit supply with evolving demand it dampens carbon-price
volatility while keeping emissions near the intended trajectory. Benmir et al.
report it cuts EU-ETS price volatility by ≈55% and welfare losses by ≈40%
relative to a fixed cap.

Algorithm
---------
LaTeX:
$$
Q_t \;=\; \overline{Q}
        \;+\; \phi_e \,\frac{e_t - \bar e}{\bar e}
        \;+\; \phi_z \,\frac{z_t - \bar z}{\bar z}
$$

ASCII fallback:
    Q_t = Qbar + phi_e * (e_t - ebar) / ebar + phi_z * (z_t - zbar) / zbar

Symbols (units):
    Q_t    : permits issued in period t                          [Mt CO2e]
    Qbar   : baseline (steady-state) cap for the period          [Mt CO2e]
             — supplied externally as the year's total_cap.
    e_t    : observed aggregate emissions                        [Mt CO2e]
    ebar   : de-trended steady-state / reference emissions       [Mt CO2e]
    z_t    : observed aggregate abatement cost                   [currency]
    zbar   : steady-state / reference abatement cost             [currency]
    phi_e  : cap sensitivity to the emissions gap                [Mt CO2e]
    phi_z  : cap sensitivity to the abatement-cost gap           [Mt CO2e]

Because the two gap terms are dimensionless fractions, phi_e and phi_z carry the
units of the cap (Mt CO2e per unit fractional deviation) and must be calibrated
to the cap scale of the modelled system. The paper's optimal coefficients
(phi_z ≈ +0.1853, phi_e ≈ -0.0027) are expressed in the paper's normalised model
units; rescale them to the per-period cap of your scenario rather than copying
the raw figures.

Sign convention (per the paper's optimum):
    phi_z > 0 : abatement costs above reference  → ISSUE MORE permits
                (ease cost pressure, reduce price spikes).
    phi_e < 0 : emissions above reference         → ISSUE FEWER permits
                (tighten to keep emissions on track).

Discrete-time / sequential implementation
-----------------------------------------
e_t and z_t are *outcomes* of market clearing, so they are not known when the
period-t cap must be set. Mirroring how the MSR reads the beginning-of-period
bank, the CCR conditions period t's cap on the **previously realised**
(period t-1) emissions and abatement cost. The first period therefore carries no
adjustment (no history yet), so Q_0 = Qbar.

A reference value of 0 disables its term (the fractional gap is undefined), so a
scenario can drive the cap off emissions alone, abatement cost alone, or both.
"""

from __future__ import annotations

import logging

# Moved to core.defaults (O1); re-exported so this module's surface is unchanged.
from ..core.defaults import CCR_DEFAULTS  # noqa: F401

logger = logging.getLogger(__name__)


class CCRState:
    """Mutable CCR state carried across the years of a single scenario path.

    Stores the previously realised emissions and abatement cost so the next
    period's cap adjustment can be computed from their deviation against the
    configured reference levels.
    """

    def __init__(self) -> None:
        self.prev_emissions: float | None = None
        self.prev_abatement_cost: float | None = None
        # Diagnostics from the most recent cap_adjustment() call.
        self.last_adjustment: float = 0.0
        self.last_emissions_deviation: float = 0.0
        self.last_cost_deviation: float = 0.0

    def cap_adjustment(
        self,
        phi_emissions: float,
        phi_abatement_cost: float,
        reference_emissions: float,
        reference_abatement_cost: float,
        year_label: str = "",
    ) -> tuple[float, float, float]:
        """Compute the period's cap adjustment ΔQ_t = Q_t − Qbar.

        Uses the previously recorded (period t-1) emissions and abatement cost.
        Returns ``(0, 0, 0)`` for the first period, before any history exists.

        Parameters
        ----------
        phi_emissions : float
            φ_e — cap sensitivity to the fractional emissions gap [Mt CO2e].
        phi_abatement_cost : float
            φ_z — cap sensitivity to the fractional abatement-cost gap [Mt CO2e].
        reference_emissions : float
            ē — reference (steady-state) emissions [Mt CO2e]. 0 disables the term.
        reference_abatement_cost : float
            z̄ — reference (steady-state) abatement cost. 0 disables the term.
        year_label : str
            Year label for logging only.

        Returns
        -------
        adjustment : float            – ΔQ_t added to permit supply [Mt CO2e]
        emissions_deviation : float   – (e_{t-1} − ē) / ē, or 0 if disabled
        cost_deviation : float        – (z_{t-1} − z̄) / z̄, or 0 if disabled
        """
        if self.prev_emissions is None or self.prev_abatement_cost is None:
            # No realised history yet → Q_0 = Qbar.
            self.last_adjustment = 0.0
            self.last_emissions_deviation = 0.0
            self.last_cost_deviation = 0.0
            return 0.0, 0.0, 0.0

        emissions_deviation = (
            (self.prev_emissions - reference_emissions) / reference_emissions
            if reference_emissions > 0.0
            else 0.0
        )
        cost_deviation = (
            (self.prev_abatement_cost - reference_abatement_cost)
            / reference_abatement_cost
            if reference_abatement_cost > 0.0
            else 0.0
        )

        adjustment = (
            phi_emissions * emissions_deviation
            + phi_abatement_cost * cost_deviation
        )

        self.last_adjustment = adjustment
        self.last_emissions_deviation = emissions_deviation
        self.last_cost_deviation = cost_deviation

        logger.debug(
            f"CCR [{year_label}]: dev_e={emissions_deviation:+.4f}, "
            f"dev_z={cost_deviation:+.4f} → ΔQ={adjustment:+.2f} Mt "
            f"(prev emissions={self.prev_emissions:.1f}, "
            f"prev abatement cost={self.prev_abatement_cost:.1f})"
        )
        return adjustment, emissions_deviation, cost_deviation

    def record(self, emissions: float, abatement_cost: float) -> None:
        """Store realised period-t aggregates for use as period-(t+1) signals."""
        self.prev_emissions = float(emissions)
        self.prev_abatement_cost = float(abatement_cost)
