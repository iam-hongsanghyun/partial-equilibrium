"""Block metadata primitives: :class:`ParamSpec`, :class:`PortSpec`,
:class:`BlockSpec`, and the in-memory :class:`BlockRegistry`.

This module is pure data plumbing — no I/O, no math. It defines the shape of
a "block" (a palette entry the frontend renders and the compiler consumes)
and nothing else. See ``docs/blocks-graph-plan.md`` §1/§3 for the catalogue
these dataclasses describe.

Dependency law: this module imports stdlib only.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

# A ParamSpec's ``scope`` says which normalised config_io document the
# ``config_key`` must appear in: a scenario dict (``normalize_scenario``), a
# year dict (``normalize_year``), a participant dict (``normalize_participant``
# / ``normalize_technology_option``), or ``"edge"`` for block-local metadata
# that never lands in a scenario config at all (e.g. analysis-block request
# payloads, or graph-only bookkeeping such as an "announced" year label that
# feeds a derived key rather than being written verbatim).
Scope = Literal["scenario", "year", "participant", "edge"]

ParamType = Literal["str", "float", "int", "bool", "enum", "list", "dict"]

Direction = Literal["in", "out"]


@dataclass(frozen=True)
class ParamSpec:
    """One block parameter and the config field it ultimately writes.

    Args:
        name: Key used inside ``Node.params`` for this parameter (the
            graph-JSON-facing name).
        config_key: The field name this parameter writes in the compiled
            scenario-config dict (``config_io`` schema). Several ParamSpecs
            may share one ``config_key`` (e.g. every ``sector`` field folds
            into the scenario-level ``sectors`` list).
        scope: Which normalised config_io document ``config_key`` belongs to.
        type: Declared value type for palette/form rendering.
        default: Value used when the param is absent from ``Node.params``.
        unit: Physical/economic unit label (``None`` if dimensionless/N-A).
        bounds: Optional ``(min, max)`` numeric bounds.
        enum: Optional allowed-value tuple for ``type == "enum"``.
        label: Human-readable label (defaults to ``name`` if omitted).
    """

    name: str
    config_key: str
    scope: Scope
    type: ParamType
    default: Any = None
    unit: str | None = None
    bounds: tuple[float, float] | None = None
    enum: tuple[str, ...] | None = None
    label: str | None = None

    def display_label(self) -> str:
        return self.label or self.name


@dataclass(frozen=True)
class PortSpec:
    """One connection point on a block.

    Args:
        name: Port name, unique within its direction on the owning block.
        direction: ``"in"`` (target of an edge) or ``"out"`` (source).
        kind: Semantic edge type. Two ports may only be connected if their
            ``kind`` values match (this is the whole of R3's type check).
        cardinality: One of ``"1"``, ``"0..1"``, ``"1..n"``, ``"0..n"``.
            Meaningful for ``"in"`` ports; ``"out"`` ports are always
            fan-out-able and use ``"0..n"``.
    """

    name: str
    direction: Direction
    kind: str
    cardinality: str = "0..n"


@dataclass(frozen=True)
class BlockSpec:
    """A palette entry: one block kind with its params and ports.

    Args:
        id: Stable block identifier (used as ``Node.block``).
        label: Human-readable palette label.
        category: One of ``market``, ``price_formation``, ``policy``,
            ``feedback``, ``expectations``, ``participants``, ``analysis``.
        doc: One-line description of what the block wraps.
        feature: The feature-module this block belongs to (e.g.
            ``"core"``, ``"banking"``, ``"msr"``, ``"batch_analysis"``) —
            the vocabulary ``ets.blocks.manifest.derive_manifest`` reports
            to the frontend and, once ``src/ets/features/*`` lands, the
            directory this block's mechanism will live under. Every block
            must declare exactly one.
        params: Declared parameters (order preserved for form rendering).
        ports: Declared ports (order preserved).
        requires: Block ids that must appear elsewhere in a valid graph
            containing this block (informational; validate.py enforces the
            economically meaningful subset as R-numbered rules).
        excludes: Block ids mutually exclusive with this one on the same
            market.
    """

    id: str
    label: str
    category: str
    doc: str
    feature: str
    params: tuple[ParamSpec, ...] = field(default_factory=tuple)
    ports: tuple[PortSpec, ...] = field(default_factory=tuple)
    requires: tuple[str, ...] = field(default_factory=tuple)
    excludes: tuple[str, ...] = field(default_factory=tuple)

    def param(self, name: str) -> ParamSpec | None:
        for p in self.params:
            if p.name == name:
                return p
        return None

    def port(self, name: str, direction: Direction | None = None) -> PortSpec | None:
        for p in self.ports:
            if p.name == name and (direction is None or p.direction == direction):
                return p
        return None

    def in_ports(self) -> tuple[PortSpec, ...]:
        return tuple(p for p in self.ports if p.direction == "in")

    def out_ports(self) -> tuple[PortSpec, ...]:
        return tuple(p for p in self.ports if p.direction == "out")


class BlockRegistry:
    """Ordered collection of :class:`BlockSpec` keyed by block id."""

    def __init__(self, blocks: tuple[BlockSpec, ...] = ()) -> None:
        self._by_id: dict[str, BlockSpec] = {}
        self._order: list[str] = []
        for block in blocks:
            self.register(block)

    def register(self, block: BlockSpec) -> None:
        if block.id in self._by_id:
            raise ValueError(f"Duplicate block id in registry: '{block.id}'")
        self._by_id[block.id] = block
        self._order.append(block.id)

    def get(self, block_id: str) -> BlockSpec:
        try:
            return self._by_id[block_id]
        except KeyError as exc:
            raise KeyError(f"Unknown block id: '{block_id}'") from exc

    def __contains__(self, block_id: str) -> bool:
        return block_id in self._by_id

    def __iter__(self) -> Iterator[BlockSpec]:
        return iter(self._by_id[bid] for bid in self._order)

    def __len__(self) -> int:
        return len(self._order)

    def ids(self) -> tuple[str, ...]:
        return tuple(self._order)

    def by_category(self, category: str) -> tuple[BlockSpec, ...]:
        return tuple(b for b in self if b.category == category)
