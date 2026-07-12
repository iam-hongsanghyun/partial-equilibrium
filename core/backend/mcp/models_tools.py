"""Stateless tool implementations behind the MCP models (governor) server.

Role split from ``pe.mcp.tools`` (the composer): the composer AUTHORS
models — it holds a conversational block graph and mutates it (``add_block``,
``set_params``, ...). This module OPERATES the already-configured model
registry — the bundled examples under ``examples/`` and every model saved to
``USER_SCENARIOS_DIR`` (by the composer's ``save_model``, or the web
composer's "Save model") — and never touches a model's internals: there is
no graph document here, and no add_block/set_params/new_graph equivalent.
Every tool takes a plain ``model_id`` (an example stem or a registry
``"user_<slug>"`` id, exactly as ``list_models()`` reports it) and either
inspects it, runs it, compares/sweeps it, or renames/deletes the registry
entry.

``list_models`` itself needs no governor-specific behaviour — inspecting the
registry is identical work regardless of which server asks — so it is
re-exported from ``pe.mcp.tools`` rather than reimplemented (see the
``as list_models`` import below); every other tool here is new.

Dependency law: same as any T5 app — this module may import ``pe.blocks``,
``pe.model_store``, ``pe.engine``, ``pe.analysis``, and stdlib.
"""

from __future__ import annotations

from typing import Any

from .. import model_store
from ..analysis.batch import run_batch
from ..blocks import derive_manifest
from ..engine import run_simulation_from_config
from .compact import (
    compact_model_description,
    compact_run_summary,
    compact_sweep_summary,
    sort_year_labels,
)
from .tools import list_models as list_models

# ── 1. list_models — re-exported from pe.mcp.tools, see module docstring ─


# ── 2. describe_model ──────────────────────────────────────────────────────


def _model_source(model_id: str) -> str:
    return "registry" if model_id.startswith("user_") else "example"


def describe_model(model_id: str) -> dict[str, Any]:
    """Manifest, scenarios, year span, participants, and mechanisms for one model.

    The read-only "what is this before I run it" tool: call before
    ``run_model``/``compare_models``/``sweep_model`` on an unfamiliar model
    id rather than guessing what it contains.

    Args:
        model_id: An example stem or registry ``"user_<slug>"`` id (see
            ``list_models``).

    Returns:
        See ``pe.mcp.compact.compact_model_description``.

    Raises:
        ModelStoreError: ``model_id`` matches no known model.
    """
    config = model_store.resolve_model_config(model_id)
    return compact_model_description(model_id, _model_source(model_id), config)


# ── 3. run_model ────────────────────────────────────────────────────────────


def run_model(model_id: str, scenario: str | None = None) -> dict[str, Any]:
    """Resolve a registered model's config and run it, compact summary out.

    The governor's counterpart to ``pe.mcp.tools.run_model``: that tool
    runs an in-progress composer *graph*; this one runs an already-saved
    *model* by id, with no graph document required.

    Args:
        model_id: An example stem or registry ``"user_<slug>"`` id.
        scenario: If given, only that scenario's results are returned.

    Returns:
        ``{"ok": True, "model_id", "scenarios": {...}}`` (plus a top-level
        ``"flow"`` key when non-default, D0-R2) — see
        ``pe.mcp.compact.compact_run_summary`` for the per-year shape.

    Raises:
        ModelStoreError: ``model_id`` matches no known model.
        ValueError: ``scenario`` doesn't match any scenario the run produced.
    """
    config = model_store.resolve_model_config(model_id)
    summary_df, _participant_df = run_simulation_from_config(config)
    return {
        "ok": True,
        "model_id": model_id,
        **compact_run_summary(summary_df, scenario=scenario, config=config),
    }


# ── 4. compare_models ───────────────────────────────────────────────────────

# Protocol-payload cap, not an economic/model parameter — same rationale as
# pe.mcp.compact's _MAX_YEARS_PER_SCENARIO (see pe.model_store's module
# docstring for why caps of this kind are colocated as module constants
# rather than routed through a .env loader).
_MAX_COMPARE_MODELS = 4


def _single_scenario_years(model_id: str, scenario: str | None) -> tuple[str, dict[str, Any]]:
    """Run one model and pick the one scenario ``compare_models`` aligns on.

    Args:
        model_id: The model to run.
        scenario: A scenario name to force, or ``None`` to require the
            model resolve to exactly one scenario on its own.

    Returns:
        ``(scenario_name, compact_run_summary(...)["scenarios"][scenario_name])``.

    Raises:
        ModelStoreError: ``model_id`` matches no known model.
        ValueError: ``scenario`` doesn't match any scenario the run
            produced, or ``scenario`` is ``None`` and the model has more
            than one scenario (ambiguous — pass ``scenario=`` to pick one).
    """
    config = model_store.resolve_model_config(model_id)
    summary_df, _participant_df = run_simulation_from_config(config)
    compact = compact_run_summary(summary_df, scenario=scenario)
    scenarios = compact["scenarios"]
    if scenario is not None:
        name = scenario
    elif len(scenarios) == 1:
        name = next(iter(scenarios))
    else:
        raise ValueError(
            f"Model '{model_id}' has {len(scenarios)} scenarios "
            f"({sorted(scenarios)}); pass scenario=<name> to pick one to compare."
        )
    return name, scenarios[name]


def _price_delta_summary(model_ids: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """One-line price-spread summary across a ``compare_models`` result's rows."""
    deltas: list[tuple[str, float]] = []
    for row in rows:
        prices = [
            row[model_id]["price"]
            for model_id in model_ids
            if model_id in row and "price" in row[model_id]
        ]
        if len(prices) >= 2:
            deltas.append((str(row["year"]), max(prices) - min(prices)))

    if not deltas:
        return {"note": "No year has a comparable price across every compared model."}

    widest_year, widest_delta = max(deltas, key=lambda item: item[1])
    narrowest_year, narrowest_delta = min(deltas, key=lambda item: item[1])
    return {
        "price_delta_min": round(narrowest_delta, 4),
        "price_delta_max": round(widest_delta, 4),
        "note": (
            f"Price difference ranges {round(narrowest_delta, 4)} (year {narrowest_year}) "
            f"to {round(widest_delta, 4)} (year {widest_year}) across the compared models."
        ),
    }


def compare_models(model_ids: list[str], scenario: str | None = None) -> dict[str, Any]:
    """Run up to 4 models and align their per-year results for comparison.

    Args:
        model_ids: 2-4 model ids (example stems or registry ``"user_<slug>"``
            ids), in the order the comparison should be reported.
        scenario: A scenario name to compare across every model. Required
            when any compared model has more than one scenario; optional
            when every model resolves to exactly one on its own.

    Returns:
        ``{"model_ids": [...], "scenario": {model_id: scenario_name, ...},
        "years": [{"year", <model_id>: {price, auction_sold,
        total_abatement, bank if present, ...}, ...}, ...], "summary":
        {"price_delta_min", "price_delta_max", "note"}}``. ``years`` is
        sorted chronologically (``pe.mcp.compact.sort_year_labels``); a
        model missing a given year (mismatched horizons) simply has no key
        for that year's row rather than a fabricated value. ``model_ids``
        preserves the caller's input order everywhere (deterministic).

    Raises:
        ValueError: Fewer than 2 or more than 4 ``model_ids``, or a
            ``scenario`` ambiguity/mismatch (see ``_single_scenario_years``).
        ModelStoreError: Any ``model_id`` matches no known model.
    """
    if len(model_ids) < 2:
        raise ValueError("compare_models needs at least 2 model ids.")
    if len(model_ids) > _MAX_COMPARE_MODELS:
        raise ValueError(
            f"compare_models supports at most {_MAX_COMPARE_MODELS} models at a time; "
            f"got {len(model_ids)}. Compare a smaller subset."
        )

    scenario_used: dict[str, str] = {}
    per_model_years: dict[str, dict[str, dict[str, Any]]] = {}
    for model_id in model_ids:
        name, year_block = _single_scenario_years(model_id, scenario)
        scenario_used[model_id] = name
        per_model_years[model_id] = {str(row["year"]): row for row in year_block["years"]}

    all_years = sort_year_labels(year for years in per_model_years.values() for year in years)

    rows: list[dict[str, Any]] = []
    for year in all_years:
        row: dict[str, Any] = {"year": year}
        for model_id in model_ids:
            year_row = per_model_years[model_id].get(year)
            if year_row is not None:
                row[model_id] = {k: v for k, v in year_row.items() if k != "year"}
        rows.append(row)

    return {
        "model_ids": list(model_ids),
        "scenario": scenario_used,
        "years": rows,
        "summary": _price_delta_summary(model_ids, rows),
    }


# ── 5. sweep_model ──────────────────────────────────────────────────────────

# Protocol-payload cap, not an economic/model parameter — same rationale as
# _MAX_COMPARE_MODELS above.
_MAX_SWEEP_VALUES = 8


def sweep_model(model_id: str, parameter_path: str, values: list[Any]) -> dict[str, Any]:
    """Sweep one dotted config path on a registered model, headline results only.

    Thin wrapper over ``pe.analysis.batch.run_batch`` for exactly one sweep
    axis: resolves ``model_id`` to its config, runs every value in
    ``values`` through ``run_batch``, and compacts each run down to its
    final-year price and cumulative abatement (see
    ``pe.mcp.compact.compact_sweep_summary``) instead of every year of
    every run.

    Args:
        model_id: An example stem or registry ``"user_<slug>"`` id.
        parameter_path: A dotted/bracketed config path, e.g.
            ``"scenarios[0].years[*].total_cap"`` (``[*]`` applies the
            value to every item in that list — see ``run_batch``'s
            ``_set_path`` for the exact grammar).
        values: 1-8 values to try at that path.

    Returns:
        ``{"model_id", "parameter_path", "runs": [...], "n_runs",
        "n_errors"}`` — see ``compact_sweep_summary`` for each run's shape.

    Raises:
        ModelStoreError: ``model_id`` matches no known model.
        ValueError: ``values`` is empty or has more than 8 entries.
    """
    if not values:
        raise ValueError("sweep_model needs at least one value to try.")
    if len(values) > _MAX_SWEEP_VALUES:
        raise ValueError(
            f"sweep_model supports at most {_MAX_SWEEP_VALUES} values at a time; "
            f"got {len(values)}."
        )
    config = model_store.resolve_model_config(model_id)
    batch = run_batch(config, [{"path": parameter_path, "values": values}])
    return {
        "model_id": model_id,
        "parameter_path": parameter_path,
        **compact_sweep_summary(batch),
    }


# ── 6. rename_model / delete_model ──────────────────────────────────────────


def rename_model(model_id: str, new_name: str) -> dict[str, Any]:
    """Rename a registry model (re-slugs its on-disk id).

    User registry entries only (ids starting with ``"user_"``) — bundled
    examples are immutable and raise a clear error rather than silently
    no-op'ing. This only changes a model's display name/id; use
    ``pe-composer``'s ``save_model`` (on a graph loaded via
    ``new_graph(template_id=...)``) to change what a model actually
    contains.

    Args:
        model_id: The registry model's current ``"user_<slug>"`` id.
        new_name: The new display name; also the basis of the new id.

    Returns:
        ``{"id", "name", "note"}`` — ``id`` is the new ``"user_<slug>"``.

    Raises:
        ModelStoreError: ``model_id`` isn't a registry id (an example, or
            unknown), ``new_name`` is empty, or the new slug collides with
            a different existing registry model.
    """
    saved = model_store.rename_registry_model(model_id, new_name)
    return {
        "id": saved.id,
        "name": saved.name,
        "note": f"Renamed '{model_id}' to '{saved.id}'.",
    }


def delete_model(model_id: str) -> dict[str, Any]:
    """Delete a registry model's config and (if present) its graph sidecar.

    User registry entries only — bundled examples are immutable and raise a
    clear error rather than silently no-op'ing.

    Args:
        model_id: The registry model's ``"user_<slug>"`` id.

    Returns:
        ``{"id", "deleted": True}``.

    Raises:
        ModelStoreError: ``model_id`` isn't a registry id, or doesn't exist.
    """
    model_store.delete_registry_model(model_id)
    return {"id": model_id, "deleted": True}


# ── 7. model_manifest ───────────────────────────────────────────────────────


def model_manifest(model_id: str) -> dict[str, Any]:
    """Raw ``derive_manifest`` passthrough for one registered model.

    Args:
        model_id: An example stem or registry ``"user_<slug>"`` id.

    Returns:
        ``pe.blocks.derive_manifest``'s full output (``features``,
        ``blocks``, ``approach``, ``categories``, ``scenarios``) — more
        detail than ``describe_model``'s ``manifest``/``mechanisms``
        summary, for callers that want the raw per-scenario breakdown too.

    Raises:
        ModelStoreError: ``model_id`` matches no known model.
    """
    config = model_store.resolve_model_config(model_id)
    return derive_manifest(config)


# ── 8. list_sessions / run_session (pe.command SESSION tier) ────────────────


def list_sessions() -> dict[str, Any]:
    """List every saved pe.command SESSION (a model populated with a user's data).

    Sessions are a distinct registry tier from models: they never appear in
    ``list_models`` (the model corpus / builder template picker), only here.
    Each carries a ``source_model_id`` link back to the model it was
    instantiated from.

    Returns:
        ``{"sessions": [{"id", "name", "source_model_id", "updated_at"}, ...]}``,
        ordered deterministically by id.
    """
    return {
        "sessions": [
            {
                "id": record.id,
                "name": record.name,
                "source_model_id": record.source_model_id,
                "updated_at": record.updated_at,
            }
            for record in model_store.list_sessions()
        ]
    }


def run_session(session_id: str, scenario: str | None = None) -> dict[str, Any]:
    """Resolve a saved SESSION's full config and run it, compact summary out.

    The session counterpart to :func:`run_model`: runs a ``"sess_<slug>"``
    session (its stored full runnable state) rather than a model.

    Args:
        session_id: A ``"sess_<slug>"`` id (see :func:`list_sessions`).
        scenario: If given, only that scenario's results are returned.

    Returns:
        ``{"ok": True, "session_id", "scenarios": {...}}`` — same compact
        per-year shape as :func:`run_model`.

    Raises:
        ModelStoreError: ``session_id`` isn't a session id, or matches none.
        ValueError: ``scenario`` doesn't match any scenario the run produced.
    """
    config = model_store.resolve_session(session_id).config
    summary_df, _participant_df = run_simulation_from_config(config)
    return {
        "ok": True,
        "session_id": session_id,
        **compact_run_summary(summary_df, scenario=scenario, config=config),
    }
