r"""market_links plugin door — link-record field/structural validation (T2).

Two-door feature (``docs/feature-modules-plan.md`` PLAN v2 §"Two-door
features"): this module is the ONLY thing ``config_io`` may import from
``pe.features.market_links`` (the door rule; enforced by
``tests/test_module_isolation.py``'s ``_is_plugin_door``). Imports ONLY
``pe.core.*`` (none needed yet) and stdlib.

D1-1 scope (schema layer only — ``docs/platform-plan-d0-d1.md`` D1-1):
``validate_links`` normalizes and validates every ``links: [...]`` record a
multi-market scenario carries, per the binding link spec
(``docs/platform-spec-d0-d1.md`` §2 "D1 link semantics — the PriceLink
object", §6 "Parameters"). Nothing here applies a link to a market or
solves anything — that is ``engine/links.py`` + ``channels.py``, D1-2/D1-3.

References:
    docs/platform-spec-d0-d1.md §2 (PriceLink semantics), §6 (parameters,
    all defaults inert).
    docs/platform-plan-d0-d1.md D1 ("multi-market schema", "GRAPH
    DISENTANGLEMENT").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "ALLOWED_LINK_CHANNELS",
    "normalize_link",
    "validate_links",
]

# spec §2b: v1 shipped exactly ``mac_cost``/``invest_break_even`` (D1). D3-4 adds
# the two steel↔carbon shared-agent coupling channels
# (``carbon_input_price``/``output_ref_price``, docs/multi-commodity-spec.md §7):
# they stamp the sibling PRICE onto the shared producer (not a MAC shift, not a
# quantity). No default (a defaulted channel is an economic constant hiding in a
# fallback). Golden-inert: no existing config uses the two new keys, so
# ``validate_links`` (which only rejects UNKNOWN channels) is byte-identical for
# every committed scenario.
ALLOWED_LINK_CHANNELS: frozenset[str] = frozenset(
    {"mac_cost", "invest_break_even", "carbon_input_price", "output_ref_price"}
)

# spec §6: REQUIRED, no default (from_market/to_market endpoint spelling is
# the architect's choice per spec §7 "Schema names").
_REQUIRED_LINK_KEYS: tuple[str, ...] = (
    "from_market",
    "to_market",
    "channel",
    "phi",
    "phi_unit",
    "target_participants",
)


def normalize_link(
    raw_link: Mapping[str, Any],
    *,
    index: int,
    markets_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate + normalize one ``links[i]`` record (spec §2, §6).

    Structural validation of the config door: every required field present
    (``from_market``, ``to_market``, ``channel``, ``phi``, ``phi_unit``,
    ``target_participants`` — none defaulted, spec §6); ``channel`` in
    :data:`ALLOWED_LINK_CHANNELS`; ``from_market``/``to_market`` reference
    markets that actually exist in ``markets_by_id`` and are distinct;
    ``target_participants`` an EXPLICIT non-empty list (implicit "all" is
    rejected, spec §6); ``target_technologies`` REQUIRED when
    ``channel == "mac_cost"`` (optional otherwise); a ``mac_cost`` link
    naming a linear-abatement technology option is rejected mechanically
    (the ``cost_slope`` dimensional exclusion, spec §2b — see
    :func:`_reject_linear_targets`); ``back_demand_estimate`` optional,
    diagnostic-only (spec §3).

    Args:
        raw_link: One raw ``links[i]`` config dict.
        index: Position in the scenario's ``links`` list, for error
            attribution (``"links[i]"``).
        markets_by_id: Every market body in the scenario, ALREADY
            normalized (``config_io.markets.iter_market_bodies`` builds
            this before validating links), keyed by ``market_id``. Used to
            check endpoint existence, the mac_cost dimensional exclusion,
            and (by the caller, :func:`validate_links`) the price_unit
            declaration.

    Returns:
        The normalized link record: ``from_market``, ``to_market``,
        ``channel``, ``phi`` (float), ``phi_unit`` (str),
        ``target_participants`` (list[str]), ``target_technologies``
        (list[str], possibly empty), ``back_demand_estimate``
        (float | None).

    Raises:
        ValueError: Any of the structural violations above.
    """
    label = f"links[{index}]"
    if not isinstance(raw_link, Mapping):
        raise ValueError(f"{label}: must be a mapping, got {type(raw_link).__name__}.")

    missing = [key for key in _REQUIRED_LINK_KEYS if key not in raw_link]
    if missing:
        raise ValueError(
            f"{label}: missing required field(s) {missing} — channel/phi/phi_unit/"
            "target_participants have no default (spec §6)."
        )

    from_market = str(raw_link["from_market"]).strip()
    to_market = str(raw_link["to_market"]).strip()
    if not from_market or not to_market:
        raise ValueError(f"{label}: from_market/to_market must be non-empty.")
    if from_market == to_market:
        raise ValueError(
            f"{label}: from_market and to_market are both '{from_market}' — "
            "self-links are forbidden."
        )
    for market_id in (from_market, to_market):
        if market_id not in markets_by_id:
            raise ValueError(
                f"{label}: references unknown market '{market_id}' — known "
                f"markets are {sorted(markets_by_id)}."
            )

    channel = str(raw_link["channel"]).strip()
    if channel not in ALLOWED_LINK_CHANNELS:
        raise ValueError(
            f"{label}: channel must be one of {sorted(ALLOWED_LINK_CHANNELS)}, "
            f"got '{channel}' (spec §2b/§6 — no default)."
        )

    try:
        phi = float(raw_link["phi"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: phi must be a number, got {raw_link['phi']!r}.") from exc

    phi_unit = str(raw_link["phi_unit"]).strip()
    if not phi_unit:
        raise ValueError(
            f"{label}: phi_unit is REQUIRED — a silent dimensionless fallback "
            "is an economic constant hiding in a default (spec §2e/§6)."
        )

    raw_target_participants = raw_link["target_participants"]
    if not isinstance(raw_target_participants, list) or not raw_target_participants:
        raise ValueError(
            f"{label}: target_participants must be an EXPLICIT non-empty list "
            "— implicit 'all' is not accepted (spec §6)."
        )
    target_participants = [str(name) for name in raw_target_participants]

    raw_target_technologies = raw_link.get("target_technologies")
    if channel == "mac_cost" and not raw_target_technologies:
        raise ValueError(
            f"{label}: target_technologies is REQUIRED for channel 'mac_cost' (spec §6)."
        )
    target_technologies: list[str] = []
    if raw_target_technologies:
        if not isinstance(raw_target_technologies, list):
            raise ValueError(f"{label}: target_technologies must be a list.")
        target_technologies = [str(name) for name in raw_target_technologies]

    if channel == "mac_cost" and target_technologies:
        _reject_linear_targets(
            label, to_market, markets_by_id[to_market], target_participants, target_technologies
        )

    raw_back_demand_estimate = raw_link.get("back_demand_estimate")
    back_demand_estimate = (
        None if raw_back_demand_estimate is None else float(raw_back_demand_estimate)
    )

    return {
        "from_market": from_market,
        "to_market": to_market,
        "channel": channel,
        "phi": phi,
        "phi_unit": phi_unit,
        "target_participants": target_participants,
        "target_technologies": target_technologies,
        "back_demand_estimate": back_demand_estimate,
    }


def _reject_linear_targets(
    label: str,
    to_market: str,
    to_market_body: Mapping[str, Any],
    target_participants: Sequence[str],
    target_technologies: Sequence[str],
) -> None:
    """Reject a ``mac_cost`` link naming a linear-abatement technology option.

    Spec §2b: ``mac_cost`` is additive on ``mac_blocks[*].marginal_cost``
    (piecewise) or the threshold MAC level (threshold) — both COST LEVELS,
    units [currency/t], dimensionally compatible with an additive ``phi``
    shift. The ``linear`` abatement type has no such level: its
    ``cost_slope`` field is a SLOPE, units [currency/t per Mt] —
    DIMENSIONALLY EXCLUDED, and "the unit check must reject it
    mechanically" (spec §2b). This is that mechanical check: a full
    pint-dimensional pass is D1-5's job, but a ``mac_cost`` link can never
    legally target a ``linear`` technology option regardless of declared
    units, so it is rejected here, at config time, structurally.

    Args:
        label: Error-message prefix (``"links[i]"``).
        to_market: The link's target market id (error attribution only).
        to_market_body: The target market's normalized body — read-only;
            only its first year's participants/technology_options are
            consulted (``abatement_type`` is a structural technology
            attribute, not a per-year-varying value).
        target_participants: The link's ``target_participants``.
        target_technologies: The link's ``target_technologies``.

    Raises:
        ValueError: At least one (participant, technology) pair named by
            the link resolves to a ``linear`` abatement type on
            ``to_market``.
    """
    years = to_market_body.get("years") or []
    if not years:
        return
    participants = years[0].get("participants") or []
    target_participant_set = set(target_participants)
    target_technology_set = set(target_technologies)
    offenders: list[str] = []
    for participant in participants:
        if participant.get("name") not in target_participant_set:
            continue
        for option in participant.get("technology_options") or []:
            if (
                option.get("name") in target_technology_set
                and option.get("abatement_type") == "linear"
            ):
                offenders.append(f"{participant.get('name')}/{option.get('name')}")
    if offenders:
        raise ValueError(
            f"{label}: mac_cost cannot target linear-abatement technology "
            f"option(s) {sorted(offenders)} on market '{to_market}' — cost_slope "
            "[currency/t per Mt] is a slope, dimensionally excluded from an "
            "additive price-LEVEL shift (spec §2b)."
        )


def validate_links(
    raw_links: Sequence[Mapping[str, Any]],
    markets_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate + normalize every link in a multi-market scenario.

    Calls :func:`normalize_link` per record (field/structural validation),
    then the one graph-level check field validation alone cannot make:
    every market that appears as either endpoint of at least one link
    (i.e. is "touching a link") must declare ``price_unit`` (spec §2e/§6 —
    "every linked market declares price_unit... Missing declarations on a
    linked market = ERROR"; "Unlinked markets need no declarations").

    Args:
        raw_links: The scenario's raw ``links`` list (``[]`` is valid — the
            inertness default, spec §6).
        markets_by_id: Every market body in the scenario, ALREADY
            normalized, keyed by ``market_id``.

    Returns:
        The normalized links, in declaration order (spec §3 "REPORT in
        declaration order"; this function does not reorder them — that is
        the engine's topological pass, D1-3).

    Raises:
        ValueError: Any :func:`normalize_link` violation, or a market
            touching a link with no ``price_unit`` declared.
    """
    if not isinstance(raw_links, list):
        raise ValueError("Scenario 'links' must be a list.")

    normalized: list[dict[str, Any]] = []
    touched_markets: set[str] = set()
    for index, raw_link in enumerate(raw_links):
        link = normalize_link(raw_link, index=index, markets_by_id=markets_by_id)
        normalized.append(link)
        touched_markets.add(link["from_market"])
        touched_markets.add(link["to_market"])

    missing_price_unit = sorted(
        market_id
        for market_id in touched_markets
        if not markets_by_id.get(market_id, {}).get("price_unit")
    )
    if missing_price_unit:
        raise ValueError(
            f"Market(s) {missing_price_unit} participate in a link but declare "
            "no price_unit — every linked market must declare price_unit "
            "(spec §2e/§6)."
        )
    return normalized
