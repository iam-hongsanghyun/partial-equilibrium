"""The storage-backend seam: ``StorageBackend`` plus its wire record type.

``pe.model_store`` (the transport-free scenario-registry I/O every app tier
shares) used to read/write user-saved models as ``<slug>.json`` /
``<slug>.graph.json`` file pairs directly. This module is the abstraction
that lets ``model_store`` delegate that persistence to a swappable backend
instead — :class:`~pe.registry.sqlite_backend.SqliteBackend` today, a
hosted Postgres/Supabase table later (:class:`~pe.registry.supabase_backend.
SupabaseBackend`, interface-only for now) — without either
``model_store`` or its callers (``pe.web.api``, ``pe.mcp.*``) knowing which
one is active.

Design choices:

* **The backend owns timestamps, not the caller.** ``save_model`` doesn't
  take ``created_at``/``updated_at`` parameters — a backend stamps
  ``created_at`` once (preserved across every subsequent update of the same
  ``model_id``) and refreshes ``updated_at`` on every write. Pushing clock
  reads down into the backend keeps ``model_store`` (and every caller above
  it) free of ``datetime.now()`` calls scattered through business logic —
  one place decides "now", consistent with the reproducibility conventions
  (``CLAUDE.md``: prefer an injected/controlled source of non-determinism
  over ad hoc calls at every call site).
* **``rename_model`` renames the DISPLAY NAME in place; it never re-keys
  the row.** A generic key-value store has no business deriving a new
  primary key from a new name — that's exactly the domain-specific
  "id is a slug of the display name" policy ``pe.model_store`` implements
  today (see ``rename_registry_model``'s docstring for why THAT layer
  composes ``get_model``/``save_model``/``delete_model`` instead of calling
  this method when the registry id must change too).
* **``ModelRecord`` is backend-agnostic wire data** — plain ``dict``/``str``
  fields only (JSON-serializable config/graph payloads), so a Postgres/
  PostgREST-backed implementation round-trips it exactly like SQLite does.

References:
    ``pe.model_store`` module docstring (the T5-shared registry-I/O module
    this backend seam sits underneath); ``docs/blocks-graph-plan.md`` §3
    (why persistence lives outside ``pe.blocks``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ModelRecord:
    """One persisted registry model, as returned by a :class:`StorageBackend`.

    Args:
        id: The registry slug (e.g. ``"k_msr"``) — **not** prefixed with
            ``"user_"``; that prefix is a ``pe.model_store``/app-facing
            convention, not a storage-layer concern.
        name: Display name (e.g. ``"K-MSR"``).
        config: The compiled scenario-config dict (``{"scenarios": [...]}"``).
        graph: The source composer graph dict, or ``None`` when this model
            was saved without one (e.g. through the legacy raw-scenario
            save flow, which has no composer graph to round-trip).
        source: Provenance tag — ``"graph"`` (saved via a composer
            :class:`~pe.blocks.Graph`) or ``"config"`` (saved from an
            already-compiled config, no graph). Free-form beyond that so a
            future writer can add its own tag without a schema change.
        domain: Optional domain-pack classification (see
            ``docs/platform-plan-d0-d1.md``'s domain-taxonomy work, R5) —
            unpopulated (``None``) by every current writer; reserved for
            when the composer/CLI start tagging saved models by domain
            pack. Never a hardcoded domain value from this module.
        created_at: ISO-8601 UTC timestamp, set once at first save.
        updated_at: ISO-8601 UTC timestamp, refreshed on every save.
    """

    id: str
    name: str
    config: dict[str, Any]
    graph: dict[str, Any] | None
    source: str
    domain: str | None
    created_at: str
    updated_at: str


class StorageBackend(Protocol):
    """Structural interface every model-registry storage adapter implements.

    ``pe.model_store``'s public functions (``save_graph_as_model``,
    ``iter_registry_models``, ``resolve_model_config``,
    ``resolve_model_graph``, ``rename_registry_model``,
    ``delete_registry_model``) delegate USER-model persistence to whichever
    :class:`StorageBackend` is active (``pe.registry.config.get_backend``)
    — bundled ``examples/*.json`` are never routed through here; they stay
    read-only files (see ``pe.model_store``'s module docstring).
    """

    def save_model(
        self,
        model_id: str,
        name: str,
        config: dict[str, Any],
        graph: dict[str, Any] | None,
        *,
        source: str = "graph",
        domain: str | None = None,
    ) -> ModelRecord:
        """Insert or upsert one model. Idempotent on ``model_id``.

        Args:
            model_id: The registry slug (unprefixed).
            name: Display name.
            config: The compiled scenario-config dict.
            graph: The source composer graph dict, or ``None``.
            source: Provenance tag, see :class:`ModelRecord`.
            domain: Optional domain-pack tag, see :class:`ModelRecord`.

        Returns:
            The persisted :class:`ModelRecord`, with ``created_at``
            preserved from any prior save of the same ``model_id`` and
            ``updated_at`` refreshed to now.
        """
        ...

    def get_model(self, model_id: str) -> ModelRecord | None:
        """Fetch one model by id, or ``None`` if no such model is saved."""
        ...

    def list_models(self) -> list[ModelRecord]:
        """List every saved model, ordered deterministically by ``id``."""
        ...

    def rename_model(self, model_id: str, new_name: str) -> ModelRecord:
        """Update a model's display name in place; ``id`` is unchanged.

        Args:
            model_id: The registry slug (unprefixed).
            new_name: The new display name.

        Returns:
            The updated :class:`ModelRecord`.

        Raises:
            KeyError: No model with ``model_id`` exists.
        """
        ...

    def delete_model(self, model_id: str) -> None:
        """Delete one model by id.

        Raises:
            KeyError: No model with ``model_id`` exists.
        """
        ...
