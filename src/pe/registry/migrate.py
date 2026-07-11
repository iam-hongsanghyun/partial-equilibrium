"""One-time backfill: existing ``<slug>.json``/``<slug>.graph.json`` file
pairs under ``USER_SCENARIOS_DIR`` into the active :class:`StorageBackend`.

Every model saved through ``pe.model_store`` (``save_graph_as_model`` /
``save_config_as_model``) already writes to BOTH the active backend and the
on-disk file pair (see ``pe.model_store``'s module docstring for why the
file mirror stays), so this migration only matters for models that were
saved BEFORE this backend seam existed — pure file writes with no matching
backend row yet. Idempotent: re-running it just re-upserts the same slugs
(``StorageBackend.save_model`` is itself an upsert), so it's safe to run
on every deploy rather than tracking "have I migrated yet" state anywhere.

Run it directly::

    python -m pe.registry.migrate

or import :func:`migrate_user_scenarios_to_sqlite` and call it from
whatever bootstraps the chosen deployment (e.g. a serverless cold-start
hook) — it is pure Python, no argparse/CLI framework required for the one
knob (``registry_dir``) it takes.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config_io import load_config
from ..core.paths import USER_SCENARIOS_DIR
from .config import get_backend_for_directory


def migrate_user_scenarios_to_sqlite(*, registry_dir: Path | None = None) -> list[str]:
    """Import every ``<slug>.json`` (+ ``.graph.json`` sidecar) under ``registry_dir``.

    Args:
        registry_dir: Directory to scan. Defaults to
            ``pe.core.paths.USER_SCENARIOS_DIR``. Resolves to a backend the
            same way ``pe.model_store`` does
            (:func:`pe.registry.config.get_backend_for_directory`), so
            migrating a test's ``tmp_path`` registry lands in that same
            tmp_path's isolated SQLite file, not the production one.

    Returns:
        The sorted list of slugs migrated (``path.stem`` for every
        ``*.json`` file found, excluding ``*.graph.json`` sidecars) —
        empty if ``registry_dir`` has no scenario files yet.
    """
    directory = registry_dir if registry_dir is not None else USER_SCENARIOS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    backend = get_backend_for_directory(directory)

    migrated: list[str] = []
    for config_path in sorted(directory.glob("*.json")):
        if config_path.name.endswith(".graph.json"):
            continue
        try:
            config = load_config(config_path)
        except Exception:
            # Same tolerance as pe.model_store.iter_registry_models: a
            # non-scenario JSON file in the registry directory is skipped,
            # not fatal to the whole migration run.
            continue

        slug = config_path.stem
        graph_path = config_path.with_name(f"{slug}.graph.json")
        graph_payload: dict | None = None
        if graph_path.exists():
            try:
                graph_payload = json.loads(graph_path.read_text(encoding="utf-8"))
            except Exception:
                graph_payload = None

        backend.save_model(
            slug,
            slug.replace("_", " ").title(),
            config,
            graph_payload,
            source="graph" if graph_payload is not None else "config",
            domain=None,
        )
        migrated.append(slug)
    return migrated


if __name__ == "__main__":
    _migrated = migrate_user_scenarios_to_sqlite()
    if _migrated:
        print(f"Migrated {len(_migrated)} model(s): {', '.join(_migrated)}")
    else:
        print("No user-scenarios files found to migrate.")
