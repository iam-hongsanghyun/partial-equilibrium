"""Policy and solver default parameter sets (T0 kernel, data only).

Scenario-level defaults shared by the solvers and by ``config_io.templates``
(the blank-scenario template spreads them into every new scenario). Moved
verbatim from ``solvers/msr.py``, ``solvers/ccr.py``, and
``solvers/banking.py`` in work order O1; those modules re-export them so
their public surface is unchanged.

Also home to the named fallback constants used at ``getattr`` sites in the
solvers (decree-MSR fallbacks from ``solvers/banking.py``, competitive-path
MSR fallbacks via ``MSR_DEFAULTS``) so each default value is typed exactly
once in the codebase.
"""

from __future__ import annotations

# ── MSR default parameter set (K-ETS calibrated) ─────────────────────────────
# These are scenario-level defaults; users can override via solver settings.

MSR_DEFAULTS = {
    "msr_enabled": False,
    "msr_upper_threshold": 200.0,   # Mt CO₂e — bank above which withholding triggers
    "msr_lower_threshold": 50.0,    # Mt CO₂e — bank below which release triggers
    "msr_withhold_rate": 0.12,      # 12% of auction_offered withheld per year
    "msr_release_rate": 50.0,       # Mt released per year when bank is low
    "msr_cancel_excess": False,     # whether to permanently cancel pool surplus
    "msr_cancel_threshold": 400.0,  # Mt CO₂e — pool above this is cancelled
}


# ── CCR default parameter set ────────────────────────────────────────────────
# Scenario-level defaults. All values are user-overridable via scenario config.
# Defaults leave the CCR disabled and neutral (no adjustment); the paper's
# optimal coefficients are intentionally NOT hardcoded here because they are in
# the paper's normalised units and must be calibrated to each scenario's cap
# scale (see the example scenario and docs/carbon-cap-rule.md).

CCR_DEFAULTS = {
    "ccr_enabled": False,
    "ccr_phi_emissions": 0.0,          # φ_e — Mt cap change per unit emissions gap (paper-optimal sign: negative)
    "ccr_phi_abatement_cost": 0.0,     # φ_z — Mt cap change per unit abatement-cost gap (paper-optimal sign: positive)
    "ccr_reference_emissions": 0.0,    # ē  — reference emissions [Mt CO2e]; 0 disables the emissions term
    "ccr_reference_abatement_cost": 0.0,  # z̄ — reference abatement cost; 0 disables the cost term
}


# Solver defaults (overridable via scenario config fields of the same name).
BANKING_DEFAULTS = {
    "banking_initial_bank": 0.0,       # Mt CO2e carried into the first year
    "banking_strict_no_arbitrage": True,
    "banking_bank_tolerance": 1e-6,    # Mt; interior bank >= -tol
    "banking_supply_rule_max_iters": 25,
    "banking_supply_rule_tolerance": 1e-3,  # Mt; schedule fixed-point tol
}


# ── Decree-MSR getattr fallbacks (K-MSR decree rule, solvers/banking.py) ─────
# Fallback values for the per-market ``msr_*`` decree fields when a scenario
# does not set them. Named here (once) and sourced at the getattr sites in
# ``_decree_msr_action`` so the numbers are never re-typed.

DECREE_MSR_PRICE_BAND_HIGH = 25_000.0   # currency/tCO2 — prev price at/above ⇒ release
DECREE_MSR_PRICE_BAND_LOW = 15_000.0    # currency/tCO2 — prev price at/below ⇒ intake
DECREE_MSR_SURPLUS_UPPER_RATIO = 0.18   # dimensionless — prev surplus ratio at/above ⇒ intake
DECREE_MSR_SURPLUS_LOWER_RATIO = 0.05   # dimensionless — prev surplus ratio at/below ⇒ release
DECREE_MSR_MAX_INTAKE_MT = 20.0         # Mt CO2e per year
DECREE_MSR_MAX_RELEASE_MT = 20.0        # Mt CO2e per year
