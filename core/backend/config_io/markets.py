"""Multi-market scenario accessor (D1-1 schema layer).

``docs/platform-plan-d0-d1.md`` D1's COMPAT RULE, verbatim: "a scenario
WITHOUT markets normalizes down the byte-identical legacy path; the flat
shape REMAINS the canonical normalized form for single-market scenarios
(markets view is derived via ``config_io.iter_market_bodies(scenario)`` ->
``[(None, scenario)]`` degenerate)." This module is that one accessor.

D1-4 update (``docs/platform-plan-d0-d1.md`` D1 "GRAPH DISENTANGLEMENT"):
:func:`normalize_scenario` now normalizes a ``markets``-shaped scenario
itself (the D1-1 interim loud guard is retired — markets are wired), so
this accessor delegates to it rather than duplicating the per-market walk
— "reuse, don't duplicate" applies across modules, not just within one.

Dependency law (``tests/test_module_isolation.py`` clause (e)): this module
is T1 (``pe.config_io``) — it may import ``pe.core.*`` freely and exactly
one feature door, ``pe.features.market_links.plugin`` (the link
field/structural validator), and nothing else outside its own tier.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .builder import normalize_scenario

__all__ = ["iter_market_bodies"]


def iter_market_bodies(scenario: Mapping[str, Any]) -> list[tuple[str | None, dict[str, Any]]]:
    """Iterate a scenario's market bodies, normalized, market_id-keyed.

    The uniform reader the engine uses to build markets regardless of
    scenario shape — see the module docstring's COMPAT RULE quote.

    Degenerate case (no ``markets`` key): today's single-market scenario,
    normalized via :func:`normalize_scenario` exactly as it always has
    been — the flat shape stays the canonical normalized form (D1 COMPAT
    RULE; this is what keeps all 39 goldens bit-identical). Returns
    ``[(None, normalized_scenario)]``.

    Multi-market case (a ``markets`` key present): :func:`normalize_scenario`
    normalizes every ``markets[i]`` entry (via
    :func:`~.builder._normalize_market_body` — the SAME per-market internals
    the flat path calls, so a market body normalizes identically whether it
    arrives flat or inside a ``markets`` list) and validates every ``links``
    entry (default ``[]``, spec §6) through
    ``pe.features.market_links.plugin.validate_links`` (the plugin-door
    contract) — field/structural validation and the price_unit-touching
    check only; nothing here applies a link, solves a market, or checks
    graph structure (DAG-ness is R34, blocks/validate.py). This function
    reshapes that normalized ``{"markets": [{"market_id": ..., **body}]}``
    into ``[(market_id, body), ...]`` — the market body itself never carries
    the accessor's own ``market_id`` bookkeeping key (stripped back out
    here), matching the flat path's ``(None, body)`` shape.

    Args:
        scenario: A raw (not yet normalized) scenario dict — either
            today's flat single-market shape, or the D1 ``markets``/
            ``links`` shape (docs/platform-spec-d0-d1.md §6).

    Returns:
        Market bodies keyed by market id (``None`` for the degenerate
        single-market case), in declaration order.

    Raises:
        ValueError: An empty/malformed ``markets`` list; a missing,
            empty, or duplicate ``market_id``; any per-market body
            validation error (:func:`~.builder._normalize_market_body`);
            or any link validation error
            (``pe.features.market_links.plugin.validate_links``).
    """
    normalized = normalize_scenario(dict(scenario))
    if "markets" not in normalized:
        return [(None, normalized)]

    result: list[tuple[str | None, dict[str, Any]]] = []
    for market in normalized["markets"]:
        market_id = market["market_id"]
        body = {k: v for k, v in market.items() if k != "market_id"}
        result.append((market_id, body))
    return result
