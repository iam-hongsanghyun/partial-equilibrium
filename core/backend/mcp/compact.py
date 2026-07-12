"""Compact result/manifest shapes shared by both MCP servers (composer + models).

``pe.engine.run_simulation_from_config`` returns full pandas DataFrames —
one row per scenario-year, with a ``f"{participant} <metric>"`` column for
*every* participant in the model — far too wide to hand an AI assistant
inline. This module keeps only the handful of scenario-level columns a
conversational "how did the model do" answer needs, and caps how many years
of one scenario it shows, so a run's output stays a small, bounded size
regardless of how many participants or years the model has.

Used by both servers: ``pe.mcp.tools`` (the composer — ``run_model`` on an
in-progress graph) and ``pe.mcp.models_tools`` (the governor — ``run_model``/
``describe_model``/``compare_models``/``sweep_model`` on an already-saved
model id), so the compact shapes stay identical regardless of which server
an AI assistant is talking to.

Engineering caps below (``_MAX_YEARS_PER_SCENARIO``, ``_ROUND_DECIMALS``) are
not economic/model parameters — see ``pe.model_store``'s module docstring
for why this repo colocates constants of this kind in code rather than a
``.env`` loader.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

from ..blocks import derive_manifest
from ..config_io import DEFAULT_FLOW_LABEL, DEFAULT_FLOW_UNIT, normalize_config

_MAX_YEARS_PER_SCENARIO = 12
_ROUND_DECIMALS = 4
_NONZERO_ATOL = 1e-9


def _flow_header_line(config: dict[str, Any]) -> str | None:
    """``"flow: <label> [<unit>]"`` for a config, or ``None`` when every default.

    D0-R2 (docs/platform-spec-d0-d1.md §5): flow_label/flow_unit are
    display-only and absent by default (the D1 COMPAT RULE — a carbon
    scenario never carries either key). This helper is the ONE place the
    MCP describe/run surfaces derive that display line, so an existing
    carbon-model's ``description``/``run_model`` output is byte-for-byte
    unchanged (this returns ``None`` and callers skip the line entirely)
    while a non-carbon model (e.g. the RPS/REC showcase, flow_label "REC")
    gains one extra line/key.

    Args:
        config: A (normalized) scenario-config dict.

    Returns:
        ``None`` if no scenario in ``config`` declares ``flow_label`` or
        ``flow_unit``; otherwise ``"flow: <label> [<unit>]"`` using the
        first (declaration-order-independent, sorted) declared pair,
        substituting :data:`~pe.config_io.DEFAULT_FLOW_LABEL` /
        :data:`~pe.config_io.DEFAULT_FLOW_UNIT` for whichever half of the
        pair a scenario leaves unset.
    """
    pairs: set[tuple[str, str]] = set()
    for scenario in config.get("scenarios", []):
        label = scenario.get("flow_label")
        unit = scenario.get("flow_unit")
        if label or unit:
            pairs.add(
                (
                    str(label) if label else DEFAULT_FLOW_LABEL,
                    str(unit) if unit else DEFAULT_FLOW_UNIT,
                )
            )
    if not pairs:
        return None
    label, unit = sorted(pairs)[0]
    return f"flow: {label} [{unit}]"


# (compact key, summary_df column label) — see core/market/reporting.py:scenario_summary
# for where every one of these column labels is written.
_CORE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("price", "Equilibrium Carbon Price"),
    ("auction_offered", "Auction Offered"),
    ("auction_sold", "Auction Sold"),
    ("total_abatement", "Total Abatement"),
)
_BANK_COLUMNS: tuple[tuple[str, str], ...] = (
    ("bank", "Total Ending Bank"),
    ("borrowed", "Total Borrowed Allowances"),
)
_MSR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("msr_withheld", "MSR Withheld"),
    ("msr_released", "MSR Released"),
    ("msr_reserve_pool", "MSR Reserve Pool"),
)
_CCR_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ccr_cap_adjustment", "CCR Cap Adjustment"),
    ("ccr_emissions_deviation", "CCR Emissions Deviation"),
    ("ccr_cost_deviation", "CCR Cost Deviation"),
)
_OPTIONAL_COLUMN_GROUPS: tuple[tuple[tuple[str, str], ...], ...] = (
    _BANK_COLUMNS,
    _MSR_COLUMNS,
    _CCR_COLUMNS,
)
# D2 joint-equilibrium convergence diagnostics — stamped ONLY on cyclic-SCC
# market rows (dispatch key-presence guard); an acyclic/single-market run never
# carries them. Unlike the groups above these are PRESENCE-guarded, not
# nonzero-guarded: a non-converged cyclic SCC stamps ``Joint Converged = 0.0``,
# which is exactly the case the user most needs surfaced — a nonzero filter
# would wrongly hide it.
_JOINT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("joint_converged", "Joint Converged"),
    ("joint_outer_iterations", "Joint Outer Iterations"),
    ("joint_max_normalized_change", "Joint Max Normalized Change"),
    ("joint_cycle_detected", "Joint Cycle Detected"),
)


def _round(value: Any) -> Any:
    try:
        return round(float(value), _ROUND_DECIMALS)
    except (TypeError, ValueError):
        return value


def _any_nonzero(frame: pd.DataFrame, columns: tuple[tuple[str, str], ...]) -> bool:
    return any(
        bool((frame[label].astype(float).abs() > _NONZERO_ATOL).any())
        for _, label in columns
        if label in frame.columns
    )


def _year_sort_index(frame: pd.DataFrame) -> pd.Index:
    """Chronological row order for one scenario's rows.

    Numeric year labels (``"2026"``) sort numerically; a non-numeric label
    (e.g. the ``"Base Year"`` fallback ``scenario_summary`` uses when a
    market has no explicit year) sorts after every numeric one, by falling
    back to the label itself only where the numeric parse failed.
    """
    if "Year" not in frame.columns:
        return frame.index
    numeric = pd.to_numeric(frame["Year"], errors="coerce")
    order_key = numeric.fillna(numeric.max(skipna=True) + 1 if numeric.notna().any() else 0)
    return order_key.sort_values().index


def compact_run_summary(
    summary_df: pd.DataFrame,
    *,
    scenario: str | None = None,
    max_years_per_scenario: int = _MAX_YEARS_PER_SCENARIO,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reduce a solved run's scenario-summary frame to a chat-sized dict.

    Args:
        summary_df: The scenario-summary frame — the first element of
            ``run_simulation_from_config``'s return tuple (one row per
            scenario-year).
        scenario: If given, only that scenario's rows are included; raises
            ``ValueError`` if no scenario in ``summary_df`` has that name.
        max_years_per_scenario: Truncate each scenario's year list to this
            many rows (chronological, from the start) — keeps the payload
            bounded for long-horizon models.
        config: The run's (normalized) scenario-config dict, if available —
            when given AND at least one scenario declares a non-default
            ``flow_label``/``flow_unit`` (D0-R2), the returned dict gains a
            top-level ``"flow"`` key (:func:`_flow_header_line`). ``None``
            (the default) never adds the key — an existing carbon-model
            caller that doesn't pass ``config`` is byte-for-byte unchanged.

    Returns:
        ``{"scenarios": {name: {"years": [...], "total_years": int,
        "truncated": bool}}, "flow": "<label> [<unit>]" (only when
        non-default and ``config`` given)}``. Each year row always carries
        ``year``, ``price``, ``auction_offered``, ``auction_sold``,
        ``total_abatement``; ``bank``/``borrowed`` are added only if the
        scenario ever has a nonzero bank/borrow balance, and the three
        ``msr_*``/``ccr_*`` columns only if MSR/CCR is ever active — no
        participant-level columns, no raw DataFrame.

    Raises:
        ValueError: ``scenario`` is given and matches no scenario in
            ``summary_df``.
    """
    flow_line = _flow_header_line(config) if config is not None else None

    if summary_df.empty:
        result: dict[str, Any] = {"scenarios": {}}
        if flow_line is not None:
            result["flow"] = flow_line
        return result

    if scenario is not None:
        available = sorted(summary_df["Scenario"].unique())
        if scenario not in available:
            raise ValueError(f"Unknown scenario '{scenario}'; available: {available}")
        summary_df = summary_df[summary_df["Scenario"] == scenario]

    scenarios: dict[str, Any] = {}
    for scenario_name, frame in summary_df.groupby("Scenario", sort=False):
        ordered = frame.loc[_year_sort_index(frame)]
        total_years = len(ordered)
        truncated = total_years > max_years_per_scenario
        shown = ordered.iloc[:max_years_per_scenario]

        optional_groups = [
            columns for columns in _OPTIONAL_COLUMN_GROUPS if _any_nonzero(ordered, columns)
        ]
        # Joint diagnostics: presence-guarded (see _JOINT_COLUMNS) — a cyclic SCC
        # stamps them on every row of its member scenarios; acyclic runs omit them.
        if any(label in ordered.columns for _, label in _JOINT_COLUMNS):
            optional_groups = [*optional_groups, _JOINT_COLUMNS]

        years = []
        for _, row in shown.iterrows():
            year_row: dict[str, Any] = {"year": row.get("Year", "Base Year")}
            for key, label in _CORE_COLUMNS:
                if label in row:
                    year_row[key] = _round(row[label])
            for columns in optional_groups:
                for key, label in columns:
                    if label in row:
                        year_row[key] = _round(row[label])
            years.append(year_row)

        scenarios[str(scenario_name)] = {
            "years": years,
            "total_years": total_years,
            "truncated": truncated,
        }

    result = {"scenarios": scenarios}
    if flow_line is not None:
        result["flow"] = flow_line
    return result


# ── shared "list a runnable model" entry (composer's list_models, the ────
# ── governor's list_models/describe_model) ───────────────────────────────


def describe_model_entry(model_id: str, source: str, config: dict[str, Any]) -> dict[str, Any]:
    """One ``list_models()`` row: id/name/source/feature chips/description.

    The single place this "what is this model, at a glance" summary is
    built — both ``pe.mcp.tools.list_models`` (the composer) and
    ``pe.mcp.models_tools.describe_model`` (the governor) call this rather
    than each deriving their own label/description text.

    Args:
        model_id: An example stem or registry ``"user_<slug>"`` id.
        source: ``"example"`` or ``"registry"``.
        config: The model's scenario-config dict.

    Returns:
        ``{"id", "name", "source", "features", "approach", "description"}``
        — ``features``/``approach`` are ``derive_manifest(config)``'s
        top-level lists; ``name`` is title-cased from the id (registry ids
        drop their ``"user_"`` prefix first); ``description`` is a one-line
        scenario-count/approach/features summary, PLUS a trailing
        ``- flow: <label> [<unit>]`` segment (:func:`_flow_header_line`)
        when at least one scenario declares a non-default D0-R2
        flow_label/flow_unit — omitted entirely for a carbon model (the
        existing description text is byte-for-byte unchanged).
    """
    manifest = derive_manifest(config)
    scenario_names = [str(s.get("name", "")) for s in config.get("scenarios", [])]
    label = model_id.removeprefix("user_") if source == "registry" else model_id
    description = (
        f"{len(scenario_names)} scenario(s) - approach: "
        f"{', '.join(manifest['approach']) or 'n/a'} - "
        f"features: {', '.join(manifest['features'])}"
    )
    flow_line = _flow_header_line(config)
    if flow_line is not None:
        description = f"{description} - {flow_line}"
    return {
        "id": model_id,
        "name": label.replace("_", " ").title(),
        "source": source,
        "features": manifest["features"],
        "approach": manifest["approach"],
        "description": description,
    }


# ── shared year-label ordering (describe_model's year span, sweep_model's ─
# ── final-year pick, compare_models' aligned year axis) ──────────────────


def sort_year_labels(labels: Iterable[str]) -> list[str]:
    """Chronological order for a set of year labels: numeric first, then lexicographic.

    Same ordering rule as :func:`_year_sort_index` (numeric year labels sort
    numerically; a non-numeric label, e.g. a Hotelling scenario's "Base
    Year" fallback, sorts after every numeric one) but for a plain
    collection of label strings rather than a ``summary_df``'s ``"Year"``
    column.

    Args:
        labels: Year label strings; duplicates are fine (deduplicated).

    Returns:
        Deduplicated labels, numeric ones ascending by value, followed by
        any non-numeric ones in lexicographic order.
    """

    def _sort_key(label: str) -> tuple[int, float, str]:
        try:
            return (0, float(label), label)
        except (TypeError, ValueError):
            return (1, 0.0, label)

    return sorted(set(labels), key=_sort_key)


# ── describe_model: manifest + scenario/year/participant/mechanism ───────


_STRUCTURAL_MANIFEST_CATEGORIES = frozenset({"market", "participants"})


def compact_model_description(model_id: str, source: str, config: dict[str, Any]) -> dict[str, Any]:
    """Manifest + scenario/year/participant/mechanism overview for ``describe_model``.

    Builds on :func:`describe_model_entry`'s ``{id, name, source, features,
    approach, description}`` with the extra detail a governor needs before
    running a model: every scenario name, the overall year span, every
    participant name across every scenario, and a "mechanisms" breakdown —
    the non-structural block categories in play (e.g. ``price_formation``,
    ``policy``, ``expectations``, ``analysis``, whichever the catalogue
    reports), each mapped to its block ids. The ``market``/``participants``
    categories are omitted here — already covered by ``scenarios``/
    ``participants`` below, not "mechanisms" in the governance sense.

    Args:
        model_id: An example stem or registry ``"user_<slug>"`` id.
        source: ``"example"`` or ``"registry"``.
        config: The model's scenario-config dict.

    Returns:
        :func:`describe_model_entry`'s dict, plus ``{"scenarios": [names],
        "years": {"start", "end", "count"}, "participants": [names],
        "mechanisms": {category: [block_id, ...]}}``.
    """
    overview = describe_model_entry(model_id, source, config)
    manifest = derive_manifest(config)
    normalized = normalize_config(config)

    scenario_names = [str(scenario["name"]) for scenario in normalized["scenarios"]]
    year_labels = sort_year_labels(
        str(year["year"]) for scenario in normalized["scenarios"] for year in scenario["years"]
    )
    participants = sorted(
        {
            str(participant["name"])
            for scenario in normalized["scenarios"]
            for year in scenario["years"]
            for participant in year.get("participants", [])
            if participant.get("name")
        }
    )
    mechanisms = {
        category: blocks
        for category, blocks in manifest["categories"].items()
        if category not in _STRUCTURAL_MANIFEST_CATEGORIES
    }

    return {
        **overview,
        "scenarios": scenario_names,
        "years": {
            "start": year_labels[0] if year_labels else None,
            "end": year_labels[-1] if year_labels else None,
            "count": len(year_labels),
        },
        "participants": participants,
        "mechanisms": mechanisms,
    }


# ── sweep_model: per-value headline results ───────────────────────────────


def compact_sweep_summary(batch: dict[str, Any]) -> dict[str, Any]:
    """Reduce ``pe.analysis.batch.run_batch``'s output to per-value headlines.

    Args:
        batch: ``run_batch``'s return value for a single-parameter sweep
            (one entry in ``sweeps``) — ``{"runs": [...], "n_runs",
            "n_errors", "sweep_axes"}``.

    Returns:
        ``{"runs": [{"params", "error", "final_year", "final_price",
        "cumulative_abatement"}, ...], "n_runs", "n_errors"}`` — one entry
        per swept value, in ``batch["runs"]`` order. ``final_year`` is the
        chronologically-last year in that run's results (see
        :func:`sort_year_labels`); ``final_price``/``cumulative_abatement``
        are ``None`` when the run errored or produced no year rows.
    """
    runs: list[dict[str, Any]] = []
    for run in batch["runs"]:
        result_years = run["results"]
        if run["error"] is not None or not result_years:
            runs.append(
                {
                    "params": run["params"],
                    "error": run["error"],
                    "final_year": None,
                    "final_price": None,
                    "cumulative_abatement": None,
                }
            )
            continue
        year_order = sort_year_labels(str(row["year"]) for row in result_years)
        final_year = year_order[-1]
        final_row = next(row for row in result_years if str(row["year"]) == final_year)
        cumulative_abatement = sum(float(row["total_abatement"]) for row in result_years)
        runs.append(
            {
                "params": run["params"],
                "error": None,
                "final_year": final_year,
                "final_price": _round(float(final_row["price"])),
                "cumulative_abatement": _round(cumulative_abatement),
            }
        )
    return {"runs": runs, "n_runs": batch["n_runs"], "n_errors": batch["n_errors"]}
