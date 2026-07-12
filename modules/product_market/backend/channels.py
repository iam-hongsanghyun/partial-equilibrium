r"""product_market runtime door — the two steel↔carbon coupling channels (T2).

The D3-4 price-driven coupling (``docs/multi-commodity-spec.md`` §7 V-D3-3,
``docs/multi-commodity-plan.md`` §0/§4). Two ``core.protocols.LinkChannel``
implementations that STAMP the sibling market's SOLVED delivered PRICE onto the
shared two-margin producer — NOT a MAC shift, NOT a quantity. Threading only the
price is the whole point (V-D3-3): each market re-derives ``q*``/``e*`` from BOTH
prices, so no quantity crosses the SCC and the joint engine's price norm suffices
(``engine/joint.py`` reused byte-for-byte).

  * ``carbon_input_price`` (carbon → steel): stamps the source carbon price
    ``P_carbon`` onto the TARGET steel market so the product solver prices carbon
    into every producer's output FOC (via ``product_supply``/
    ``MultiCommodityProducer.stamp_carbon_price``). The steel market carries the
    producers as ``product_producers`` specs built fresh each solve, so the stamp
    lands on the market's ``product_carbon_price`` attribute the solver reads.
  * ``output_ref_price`` (steel → carbon): stamps the source steel price
    ``P_steel`` onto the TARGET carbon market's producer EMITTER VIEWS
    (``MultiCommodityProducer.stamp_steel_price``) so ``optimize_compliance``
    computes output-driven emissions ``e* = (σ − a*) q*`` at the current price
    pair.

Both are PURE and COPY-ON-WRITE (the ``market_links`` ``MacCostChannel``
precedent, spec §2d F4 purity): they NEVER mutate ``target_markets`` or anything
reachable from it. A changed market is a fresh ``copy.copy``; a changed producer
view is a fresh ``copy.copy`` re-stamped; untouched objects pass through BY
IDENTITY, and a call with nothing to stamp returns the SAME input list object.

Purity/tier: imports ONLY ``pe.core.*`` (the T2→T0 edge the AST ratchet permits)
and stdlib; reachable only through the engine's ``LINK_CHANNELS`` registry
(``engine/wiring.py:link_channels``), never from ``config_io``.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING

from ...core.participant.producer import MultiCommodityProducer

if TYPE_CHECKING:
    from ...core.market.model import CarbonMarket
    from ...core.protocols import LinkSpec

__all__ = ["CarbonInputPriceChannel", "OutputRefPriceChannel"]

_WILDCARD = "*"


def _source_price(
    source_price_path: Mapping[str, float], year: str | None, link: LinkSpec
) -> float:
    """Read the contemporaneous source price ``P_A(t)`` at a target year.

    Args:
        source_price_path: Source market's solved delivered price by year label.
        year: The target market's own year label ``t`` (same year, spec §2c).
        link: The link (error attribution only).

    Returns:
        ``P_A(t)`` in the source market's price unit.

    Raises:
        ValueError: The target year is absent from the source path (spec §7 E8
            strict-subset), or the target market carries no year label.
    """
    if year is None:
        raise ValueError(
            f"Link {link.from_market}->{link.to_market}: a target market has no year "
            "label — a coupled market's years must be declared to read P_A(t)."
        )
    if year not in source_price_path:
        raise ValueError(
            f"Link {link.from_market}->{link.to_market}: source price path has no "
            f"entry for target year {year!r} (spec §7 E8 strict-subset). Known source "
            f"years: {sorted(source_price_path)}."
        )
    return float(source_price_path[year])


def _matches_participant(link: LinkSpec, participant_name: str) -> bool:
    """Return whether a producer is targeted (explicit name or ``"*"`` wildcard)."""
    return _WILDCARD in link.target_participants or participant_name in link.target_participants


class CarbonInputPriceChannel:
    r"""carbon → steel: stamp ``P_carbon`` onto the target steel market (spec §7).

    For each per-year target steel market, overrides the ``product_carbon_price``
    attribute the product solver reads (and, per year, stamps onto every producer
    via ``stamp_carbon_price``) with ``φ·P_carbon(t)``. That is the coupling
    input to the producer's output FOC ``q*(P_s, P_c)`` — a carbon COST on steel
    output, NOT a MAC shift and NOT a quantity.

    Algorithm:
        LaTeX:
        $$ P_c^{\mathrm{steel}}(t) \;\mapsto\; \phi\,P_{\mathrm{carbon}}(t),
           \qquad
           q_i^{*} = \max\!\Big(0,\ \frac{P_s - \gamma_i - B_i(P_c)}{\delta_i}\Big) $$

        ASCII fallback:
            steel_market.product_carbon_price := phi * P_carbon(t)
            (read by the product solver -> stamp_carbon_price on each producer)

        Symbols (units):
            P_carbon(t) : source carbon price at year t   [currency/tCO2]
            phi         : link coefficient (1 = pass-through) [tCO2/tCO2]
            P_c^steel   : the carbon price the steel leg prices in [currency/tCO2]

    Pure copy-on-write: each shifted steel market is a fresh ``copy.copy`` with
    ``product_carbon_price`` reset; everything else shared by identity, and a
    no-target call returns the input list itself.
    """

    def apply(
        self,
        link: LinkSpec,
        source_price_path: Mapping[str, float],
        target_markets: list[CarbonMarket],
    ) -> list[CarbonMarket]:
        """Stamp ``φ·P_carbon(t)`` onto each target steel market (see class docstring)."""
        if not target_markets:
            return target_markets
        result: list[CarbonMarket] = []
        for market in target_markets:
            carbon_price = link.phi * _source_price(source_price_path, market.year, link)
            clone = copy.copy(market)
            # setattr symmetry: the product body is carried on CarbonMarket
            # dynamically (builder stamps it via setattr; the solver reads it via
            # getattr), so the coupling writes it via setattr too.
            setattr(clone, "product_carbon_price", float(carbon_price))  # noqa: B010
            result.append(clone)
        return result


class OutputRefPriceChannel:
    r"""steel → carbon: stamp ``P_steel`` onto the carbon producer emitter views.

    For each per-year target carbon market, stamps ``φ·P_steel(t)`` onto every
    targeted producer emitter view (a
    :class:`~pe.core.participant.producer.MultiCommodityProducer` the builder's
    ``producer_ref`` expansion placed in the carbon participant list) via
    ``stamp_steel_price``. On the next carbon clearing, each view's
    ``optimize_compliance`` re-derives output-driven emissions from the stamped
    steel price and the probed carbon price — the steel→carbon half of the cycle.

    Algorithm:
        LaTeX:
        $$ P_s^{\mathrm{prod}}(t) \;\mapsto\; \phi\,P_{\mathrm{steel}}(t),
           \qquad e_i^{*} = (\sigma_i - a_i^{*})\,q_i^{*}(P_s, P_c) $$

        ASCII fallback:
            for each producer view p targeted by the link:
                p.stamp_steel_price(phi * P_steel(t))
            (read by optimize_compliance -> e* = (sigma - a*) q*)

        Symbols (units):
            P_steel(t) : source steel price at year t     [currency/t-steel]
            phi        : link coefficient (1 = pass-through) [t-steel/t-steel]
            e_i*       : producer i residual emissions      [tCO2/period]

    Pure copy-on-write: a stamped producer view is a fresh ``copy.copy``
    re-stamped, its market a fresh ``copy.copy`` with the replaced participants;
    non-producer participants and every untouched object pass through by
    identity, and a no-target call returns the input list itself.
    """

    def apply(
        self,
        link: LinkSpec,
        source_price_path: Mapping[str, float],
        target_markets: list[CarbonMarket],
    ) -> list[CarbonMarket]:
        """Stamp ``φ·P_steel(t)`` onto each carbon producer view (see class docstring)."""
        if not target_markets:
            return target_markets
        result: list[CarbonMarket] = []
        changed_any = False
        for market in target_markets:
            steel_price = link.phi * _source_price(source_price_path, market.year, link)
            replacements: dict[int, MultiCommodityProducer] = {}
            for index, participant in enumerate(market.participants):
                if not isinstance(participant, MultiCommodityProducer):
                    continue
                if not _matches_participant(link, participant.name):
                    continue
                clone_p = copy.copy(participant)
                clone_p.stamp_steel_price(float(steel_price))
                replacements[index] = clone_p
            if replacements:
                changed_any = True
                clone = copy.copy(market)
                clone.participants = [
                    replacements.get(i, p) for i, p in enumerate(market.participants)
                ]
                result.append(clone)
            else:
                result.append(market)
        if not changed_any:
            return target_markets
        return result
