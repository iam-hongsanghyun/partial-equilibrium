# Nash-Cournot — Reference

## What this module implements

`pe.features.nash_cournot` (`modules/nash_cournot/backend/solver.py`,
`solve_nash_path`) replaces the competitive module's price-taking
assumption with strategic behaviour for a configurable subset of
participants: instead of every participant treating the carbon price as
given, `strategic_participants` internalise their own price impact — a
large buyer knows that increasing its allowance demand pushes the market
price up, so it voluntarily under-demands to lower the price it pays. The
equilibrium concept is a Cournot-Nash equilibrium in abatement quantities:
no strategic participant can lower its total compliance cost by
unilaterally changing its own abatement, given the others' choices held
fixed. The solver implements this via best-response (Jacobi-style)
iteration: starting from the competitive equilibrium, each strategic
participant's best response is found by minimizing its own cost against a
finite-difference estimate of `dP/dQ` (the residual demand curve's price
impact), iterating until `max|delta_a_i| <= tolerance`. Non-strategic
participants remain price-takers throughout. MSR interaction is
F2-frozen: an injected duck-typed `MSRState` (never a CCR) is applied
ungated (`msr_start_year` is ignored) — a deliberately preserved asymmetry
relative to the competitive module's MSR gating, documented rather than
"fixed," to keep this module's numbers bit-identical to its pre-refactor
behaviour.

## Reference papers

- Cournot, A. (1838). *Recherches sur les Principes Mathématiques de la
  Théorie des Richesses.* Paris: Hachette.

  The founding oligopoly-quantity-competition model this module's
  best-response iteration computes a numerical fixed point of: each
  strategic agent chooses a quantity (here, abatement, which maps
  one-to-one to net allowance demand) taking rivals' quantities as given,
  and the market price is the residual-demand function of the sum of all
  quantities. Cournot's original good is a homogeneous product; this
  module's "quantity" is abatement, with the allowance market's inverse
  demand curve playing Cournot's price function.

- Hahn, R.W. (1984). "Market Power and Transferable Property Rights."
  *Quarterly Journal of Economics*, 99(4), 753–765.

  The tradeable-permit-specific extension of Cournot competition this
  module operationalizes: Hahn shows that when permits are initially
  over-allocated to a dominant firm, that firm's strategic behaviour
  (restricting its own permit purchases, or over-holding sold permits) can
  move the equilibrium price and abatement pattern away from the
  cost-minimizing competitive outcome that Montgomery (1972) guarantees
  under price-taking — i.e. Montgomery's allocation-neutrality result
  (`modules/competitive/doc/reference.md`) does *not* survive strategic
  behaviour, which is exactly the gap this module exists to model. Hahn's
  result that the *initial allocation* of permits determines the direction
  and magnitude of the price distortion (not just who holds them) is the
  reason `strategic_participants` and `free_allocation_ratio` interact
  meaningfully here, unlike in the competitive module.
