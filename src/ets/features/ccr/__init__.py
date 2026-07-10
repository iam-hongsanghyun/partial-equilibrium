"""CCR feature (T2) — plugin-only for now; see ``plugin.py`` for the config door.

The CCR runtime (``CCRCapRule``, the Benmir-Roman-Taschini carbon cap rule)
stays in ``ets/solvers/ccr.py`` until O11+ (``docs/feature-modules-plan.md``
O11 "engine/ + features/msr + features/ccr"). The two-door design allows a
plugin-only feature directory in the meantime (O7): this door attaches only
the summary-placeholder reporter.
"""
