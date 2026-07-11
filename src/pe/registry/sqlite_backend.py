"""``StorageBackend`` implementation on stdlib ``sqlite3`` — no new dependency.

One ``models`` table, one row per registry model, keyed by slug. Every
public method opens a short-lived connection (WAL journal mode, a busy
timeout instead of an immediate ``SQLITE_BUSY`` error) rather than holding
one open for the process lifetime — cheap enough for a local file-backed
registry, and it sidesteps ``sqlite3``'s one-thread-per-connection rule for
the multiple request-handling threads ``pe.web.server``'s WSGI app and
``http.server`` variant can spin up (each call gets its own connection, so
there is nothing to share across threads).

Algorithm:
    Not a numerical algorithm — a storage adapter. The one piece of
    "logic" worth spelling out is the upsert's timestamp rule:

        created_at' = created_at  if a row for model_id already exists
                     = now()      otherwise
        updated_at' = now()       always

    ASCII: on conflict, keep the old created_at, always bump updated_at.
    Implemented as a single ``INSERT ... ON CONFLICT(id) DO UPDATE``
    statement (SQLite ≥ 3.24, upsert clause) rather than a
    read-then-write, so a save is one round trip and race-free within a
    single connection's transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backend import ModelRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    graph_json TEXT,
    source TEXT NOT NULL,
    domain TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string with second precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _row_to_record(row: sqlite3.Row) -> ModelRecord:
    return ModelRecord(
        id=row["id"],
        name=row["name"],
        config=json.loads(row["config_json"]),
        graph=json.loads(row["graph_json"]) if row["graph_json"] is not None else None,
        source=row["source"],
        domain=row["domain"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class SqliteBackend:
    """A :class:`~pe.registry.backend.StorageBackend` on a local SQLite file.

    Args:
        db_path: Path to the ``.sqlite`` file. Its parent directory is
            created (``mkdir(parents=True, exist_ok=True)``) and the
            ``models`` table is created (``IF NOT EXISTS``) on
            construction, so a fresh path is immediately usable.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.execute(_SCHEMA)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """One short-lived connection per call, WAL mode, as a transaction.

        ``with conn:`` (the ``sqlite3.Connection`` context manager) commits
        on clean exit and rolls back on an exception; the connection itself
        is always closed via the outer ``try/finally``.
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            with conn:
                yield conn
        finally:
            conn.close()

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
        now = _utc_now_iso()
        config_json = json.dumps(config)
        graph_json = json.dumps(graph) if graph is not None else None
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO models
                    (id, name, config_json, graph_json, source, domain, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    config_json = excluded.config_json,
                    graph_json = excluded.graph_json,
                    source = excluded.source,
                    domain = excluded.domain,
                    updated_at = excluded.updated_at
                """,
                (model_id, name, config_json, graph_json, source, domain, now, now),
            )
            row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        return _row_to_record(row)

    def get_model(self, model_id: str) -> ModelRecord | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        return _row_to_record(row) if row is not None else None

    def list_models(self) -> list[ModelRecord]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM models ORDER BY id ASC").fetchall()
        return [_row_to_record(row) for row in rows]

    def rename_model(self, model_id: str, new_name: str) -> ModelRecord:
        now = _utc_now_iso()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE models SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, model_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(model_id)
            row = conn.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()
        return _row_to_record(row)

    def delete_model(self, model_id: str) -> None:
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM models WHERE id = ?", (model_id,))
            if cursor.rowcount == 0:
                raise KeyError(model_id)
