r"""Elastic-baseline plugin door — price-elastic BAU baseline overlay (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``ets.features.elastic_baseline`` (the door rule). This feature has no
runtime module today — the overlay is called directly at its pre-refactor
call site inside the kernel (``core/participant/models.py``
``activity_multiplier``, now the overlay dispatcher), the same relationship
CBAM's reporters have to the reporting host. Imports ONLY ``ets.core.*`` and
stdlib.

``ElasticBaselineOverlay`` implements ``core.protocols.DemandOverlay`` with
the Option A formula relocated VERBATIM from the pre-refactor
``core/participant/models.py`` ``activity_multiplier`` (lines 173-197: same
clamps, same float expressions).

``stamp_and_attach`` is the BLOCKING design fix from the binding Arbitration
outcomes (PLAN v2, O8): ``reference_carbon_price`` is a SCENARIO-level field
historically stamped onto participants post-construction
(``config_io/builder.py``, pre-fix lines 474-477); a bare
``participant.reference_carbon_price = ...`` assignment could silently leave
an active elastic channel (``output_price_elasticity > 0``) without its
overlay attached — activity would never actually contract even though the
scenario config says it should, with no error raised anywhere. This plugin
now OWNS that stamping step: it stamps ``reference_carbon_price`` AND
attaches the overlay in one call, per participant, conditional on that
participant's own ``output_price_elasticity > 0`` — mirroring
``activity_multiplier``'s exact pre-refactor activation predicate (``eps > 0
AND P_ref > 0``). ``core.participant.models.MarketParticipant`` enforces a
loud guard (raises ``ValueError``) at every mutation of
``output_price_elasticity``, ``reference_carbon_price``, or
``demand_overlays`` — not only at construction — so any code path that
bypasses this function and stamps ``reference_carbon_price`` directly on an
elastic participant fails loudly instead of silently dropping the channel.

References:
    docs/feature-modules-plan.md — PLAN v2 §"Two-door features", "Feature
    verdicts v2" ("elastic_baseline (models.py:193-197 formula -> overlay;
    kernel guard raises loud if eps>0 without overlay — the one deliberate
    API change)"); Arbitration outcomes, O8 (binding design fix).
    core/protocols.py — ``DemandOverlay``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...core.participant.models import MarketParticipant

__all__ = ["ElasticBaselineOverlay", "stamp_and_attach"]


@dataclass(frozen=True)
class ElasticBaselineOverlay:
    r"""Price-elastic scaling of one participant's BAU baseline (Option A).

    A self-contained, immutable snapshot of one participant's elasticity
    coefficient and reference price at the moment ``stamp_and_attach`` ran —
    deliberately NOT a back-reference to the owning ``MarketParticipant``
    (which would make every attached participant self-referential through
    its own ``demand_overlays`` tuple, recursing in ``repr``/``__eq__``).
    Snapshotting is exact here because both source fields are written
    exactly once, at build time, before any compliance solve reads them
    (``output_price_elasticity`` is a build-time-only field; the historical
    single post-construction write to ``reference_carbon_price`` is this
    class's own construction site).

    Algorithm:
        LaTeX:  $$m(P) = \max\!\left(0,\; 1 - \varepsilon\,
                \frac{P - P_{\mathrm{ref}}}{P_{\mathrm{ref}}}\right)$$
        ASCII:  m(P) = max(0, 1 - eps * (P - P_ref) / P_ref)

        Symbols (units):
            P     : carbon price                            [currency/tCO2]
            P_ref : reference (undistorted) carbon price;
                    ``reference_carbon_price``                [currency/tCO2]
            eps   : ``output_price_elasticity``, dimensionless (>= 0)

    Returns 1.0 (no feedback) when ``eps <= 0`` or ``P_ref <= 0`` — the same
    early-return the pre-refactor ``activity_multiplier`` method used.

    Attributes:
        output_price_elasticity: eps, dimensionless (>= 0).
        reference_carbon_price: P_ref, price units (> 0 to be active).
    """

    output_price_elasticity: float
    reference_carbon_price: float

    def baseline_multiplier(self, price: float) -> float:
        """Return m(P) at ``price``.

        Args:
            price: Carbon price P [currency/tCO2].

        Returns:
            Dimensionless multiplier m(P) >= 0; 1.0 means no feedback.
        """
        eps = self.output_price_elasticity
        p_ref = self.reference_carbon_price
        if eps <= 0.0 or p_ref <= 0.0:
            return 1.0
        return max(0.0, 1.0 - eps * (price - p_ref) / p_ref)


def stamp_and_attach(
    participant: "MarketParticipant", reference_carbon_price: float
) -> "MarketParticipant":
    """Stamp the scenario reference price and attach the overlay atomically.

    Owns the stamping step the binding Arbitration outcomes (O8) assign to
    this plugin. Mirrors ``activity_multiplier``'s pre-refactor activation
    predicate EXACTLY: the overlay is attached only when this participant's
    ``output_price_elasticity > 0 AND reference_carbon_price > 0`` (the
    latter evaluated on the ``reference_carbon_price`` ARGUMENT, i.e. what is
    about to be stamped — not the participant's current, possibly-stale,
    field). Participants that fail the predicate (the common case, ``eps ==
    0``) still get ``reference_carbon_price`` stamped — matching the
    pre-refactor loop, which stamped every participant unconditionally
    whenever the scenario anchor was configured — but get NO overlay: a
    no-op, since an unattached channel with ``eps == 0`` never fed back into
    the baseline anyway (``activity_multiplier``'s old early return).

    The overlay is attached BEFORE the price stamp (field write order:
    ``demand_overlays`` then ``reference_carbon_price``) so
    ``MarketParticipant``'s loud guard never observes the inconsistent
    intermediate state (P_ref active, overlay missing) even transiently:
    while ``demand_overlays`` is being extended, the field being written
    doesn't yet fail the guard (either eps <= 0, or reference_carbon_price
    is still its pre-stamp value); the final write (the price) lands on a
    participant that already carries the overlay.

    Args:
        participant: The participant to stamp (mutated in place; this is
            the only call site allowed to mutate ``reference_carbon_price``
            or ``demand_overlays`` post-construction without tripping the
            guard).
        reference_carbon_price: Scenario-level P_ref [currency/tCO2]. The
            builder only calls this function when the scenario configured a
            positive anchor (see ``config_io/builder.py``); 0 keeps the
            channel globally disabled and is stamped as a no-op (no
            overlay attached, matching every participant's default).

    Returns:
        The same ``participant`` instance, stamped (and overlay-attached
        when active), for convenient use in a list/generator comprehension.
    """
    if participant.output_price_elasticity > 0.0 and reference_carbon_price > 0.0:
        participant.demand_overlays = (
            *participant.demand_overlays,
            ElasticBaselineOverlay(
                output_price_elasticity=participant.output_price_elasticity,
                reference_carbon_price=reference_carbon_price,
            ),
        )
    participant.reference_carbon_price = reference_carbon_price
    return participant
