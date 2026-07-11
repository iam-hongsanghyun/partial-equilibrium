"""hoarding feature (T2) — the structural-hoarding Friction provider; see ``plugin.py``.

Only the inflow schedule reader lives here. The EXTENDED HOST SET stays in
the banking solver (Arbitration outcomes, O10, binding): the static-year
supply reduction S_t − h_t, the no-arbitrage-prune exemption for hoarding
years (the documented λ ≈ 0 violation), the window-start constraint
a > max{t : h_t > 0}, and the bank accumulation of the hoarded volume are
window-equilibrium math, not feature behaviour.
"""
