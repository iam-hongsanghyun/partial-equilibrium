"""``StorageBackend`` adapter seam for a hosted Supabase registry — INTERFACE ONLY.

Every method here raises :class:`NotImplementedError`. This module exists so
the ``StorageBackend`` Protocol (``pe.registry.backend``) has a second,
concrete implementer to type-check against — proving the seam
:class:`~pe.registry.sqlite_backend.SqliteBackend` sits behind is real and
swappable — without pulling in the ``supabase-py`` client, a network
dependency, or credentials this project doesn't have yet. Wiring a live
Supabase project is future work; this module sketches the shape it would
take.

A real implementation would look roughly like::

    from supabase import Client, create_client

    class SupabaseBackend:
        def __init__(self, url: str, key: str, table: str = "models") -> None:
            self._client: Client = create_client(url, key)
            self._table = table

        def save_model(self, model_id, name, config, graph, *, source="graph", domain=None):
            now = _utc_now_iso()
            payload = {
                "id": model_id,
                "name": name,
                "config_json": json.dumps(config),
                "graph_json": json.dumps(graph) if graph is not None else None,
                "source": source,
                "domain": domain,
                "updated_at": now,
            }
            existing = self._client.table(self._table).select("created_at") \\
                .eq("id", model_id).execute()
            payload["created_at"] = (
                existing.data[0]["created_at"] if existing.data else now
            )
            response = self._client.table(self._table).upsert(payload).execute()
            return _row_to_record(response.data[0])

        def get_model(self, model_id):
            response = self._client.table(self._table).select("*") \\
                .eq("id", model_id).execute()
            return _row_to_record(response.data[0]) if response.data else None

        # list_models(): .select("*").order("id") — same PostgREST call shape.
        # rename_model(): .update({"name": ..., "updated_at": ...}).eq("id", ...)
        #   — the affected-row-count check that raises KeyError on a miss
        #   mirrors SqliteBackend.rename_model's cursor.rowcount == 0 guard.
        # delete_model(): .delete().eq("id", model_id).execute(), same guard.

The schema (a ``models`` table: ``id text primary key, name text,
config_json text, graph_json text, source text, domain text, created_at
timestamptz, updated_at timestamptz``) matches
:class:`~pe.registry.sqlite_backend.SqliteBackend`'s SQLite schema exactly,
so a migration from SQLite to Supabase is a straight per-row copy — no
reshaping of ``ModelRecord``.

Row Level Security is deliberately left as a TODO for whoever wires this
up for real: a hosted multi-tenant registry needs a policy scoping rows to
the authenticated caller, which the local single-tenant SQLite backend has
no equivalent of.
"""

from __future__ import annotations

from typing import Any

from .backend import ModelRecord


class SupabaseBackend:
    """Not-yet-implemented :class:`~pe.registry.backend.StorageBackend` seam.

    Args:
        url: The Supabase project URL (e.g. ``PE_SUPABASE_URL``).
        key: The Supabase service-role or anon key (e.g.
            ``PE_SUPABASE_KEY`` — never hardcoded, always loaded via
            ``pe.registry.config``).
        table: The Postgres table name backing the registry.

    Raises:
        NotImplementedError: Every method — this is an interface sketch,
            not a working backend. See the module docstring for the
            ``supabase-py`` shape a real implementation would take.
    """

    def __init__(self, url: str | None = None, key: str | None = None, table: str = "models") -> None:
        self._url = url
        self._key = key
        self._table = table

    def _unimplemented(self, method: str) -> NotImplementedError:
        return NotImplementedError(
            f"SupabaseBackend.{method} is an interface sketch, not a live implementation — "
            "see this module's docstring for the supabase-py shape it would take. "
            "Use SqliteBackend (the default) until a Supabase project is wired up."
        )

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
        raise self._unimplemented("save_model")

    def get_model(self, model_id: str) -> ModelRecord | None:
        raise self._unimplemented("get_model")

    def list_models(self) -> list[ModelRecord]:
        raise self._unimplemented("list_models")

    def rename_model(self, model_id: str, new_name: str) -> ModelRecord:
        raise self._unimplemented("rename_model")

    def delete_model(self, model_id: str) -> None:
        raise self._unimplemented("delete_model")
