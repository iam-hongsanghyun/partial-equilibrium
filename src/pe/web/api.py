"""Transport-free API functions shared by both web servers.

Moved verbatim from ``web/handlers.py`` (Order 3 of the modularization
plan). These functions know nothing about HTTP transports; they take and
return plain dicts / DataFrames. Both ``web/handlers.py`` (http.server)
and ``web/server.py`` (WSGI) dispatch to them.

The graph-composer endpoints (Order 8) live here too: ``web`` is allowed to
import ``ets.blocks`` (the reverse is forbidden — ``blocks/`` stays free of
``web``/``solvers`` imports).
"""
from __future__ import annotations

import json
import logging
import math
from copy import deepcopy

import pandas as pd

from ..blocks import BLOCK_CATALOGUE, Graph, derive_manifest, graph_from_config, validate_graph
from ..blocks.serialize import serialize_catalogue
from ..core.paths import EXAMPLES_DIR, USER_SCENARIOS_DIR
from ..config_io import blank_config, build_markets_from_config
from ..engine import run_simulation, solve_scenario_path
from ..model_store import (
    compile_graph_or_raise,
    iter_examples,
    iter_registry_models,
    save_config_as_model,
    save_graph_as_model,
    slugify_filename,
)


def _predefined_templates() -> list[dict]:
    """List every template the frontend's picker offers: blank + examples + registry.

    The example/registry enumeration (which directory, which glob, skipping
    ``*.graph.json`` sidecars, tolerating a non-scenario JSON) is
    ``ets.model_store.iter_examples``/``iter_registry_models`` — shared with
    ``ets.mcp``'s ``list_models`` tool, which needs the same raw (undecorated)
    listing. ``EXAMPLES_DIR``/``USER_SCENARIOS_DIR`` are passed through
    explicitly (rather than relying on ``model_store``'s own defaults) so
    tests that ``monkeypatch.setattr(api, "USER_SCENARIOS_DIR", ...)`` keep
    working unchanged.
    """
    templates = [
        {
            "id": "blank",
            "name": "Blank Custom Config",
            "config": _decorate_frontend_config(blank_config(), template_id="blank"),
        }
    ]
    for template_id, config in iter_examples(examples_dir=EXAMPLES_DIR):
        label = template_id.replace("_", " ").title()
        templates.append(
            {
                "id": template_id,
                "name": label,
                "source": "example",
                "config": _decorate_frontend_config(config, template_id=template_id),
            }
        )
    for template_id, config in iter_registry_models(registry_dir=USER_SCENARIOS_DIR):
        label = template_id.removeprefix("user_").replace("_", " ").title()
        templates.append(
            {
                "id": template_id,
                "name": f"User · {label}",
                "source": "user",
                "config": _decorate_frontend_config(config, template_id=template_id),
            }
        )
    return templates


def _decorate_frontend_config(config: dict, template_id: str) -> dict:
    decorated = deepcopy(config)
    palette = ["#1f6f55", "#8a6d3b", "#1f4e79", "#9c4f2f", "#5c4c8a"]
    for index, scenario in enumerate(decorated.get("scenarios", [])):
        scenario.setdefault("id", f"{template_id}_scenario_{index + 1}")
        scenario.setdefault("color", palette[index % len(palette)])
        scenario.setdefault("description", "User-defined ETS scenario.")
        for participant in scenario.get("years", [{}])[0].get("participants", []):
            participant.setdefault("sector", "Other")
        for year in scenario.get("years", []):
            for participant in year.get("participants", []):
                participant.setdefault("sector", "Other")
    return decorated


class _WarningCollector(logging.Handler):
    """Lightweight log handler that accumulates WARNING-level messages."""
    def __init__(self, store: list[str]) -> None:
        super().__init__(level=logging.WARNING)
        self._store = store

    def emit(self, record: logging.LogRecord) -> None:
        self._store.append(self.format(record))


def _build_dashboard_payload(config: dict) -> dict:
    frontend_config = _decorate_frontend_config(config, template_id="run")
    markets = build_markets_from_config(frontend_config)

    # Capture logger warnings during simulation so they can be surfaced in the UI
    _warnings: list[str] = []
    _log_handler = _WarningCollector(_warnings)
    # Dual attach for the ets->pe rename window: module loggers are now `pe.*`,
    # but the legacy `ets` root is kept so pre-rename callers still collect. The
    # `ets` handle drops at 0.4.0 (D0-R1 landmine 1).
    pe_logger = logging.getLogger("pe")
    ets_logger = logging.getLogger("ets")
    pe_logger.addHandler(_log_handler)
    ets_logger.addHandler(_log_handler)
    try:
        summary_df, participant_df = run_simulation(markets)
    finally:
        pe_logger.removeHandler(_log_handler)
        ets_logger.removeHandler(_log_handler)

    by_scenario: dict[str, dict[str, dict]] = {}
    scenario_market_map: dict[str, list] = {}
    for market in markets:
        scenario_market_map.setdefault(market.scenario_name, []).append(market)

    for scenario_name, scenario_markets in scenario_market_map.items():
        ordered_markets = sorted(
            scenario_markets,
            key=lambda item: (
                float(item.year) if str(item.year).replace(".", "", 1).isdigit() else float("inf"),
                str(item.year),
            ),
        )
        for item in solve_scenario_path(ordered_markets):
            market = item["market"]
            expected_future_price = item["expected_future_price"]
            starting_bank_balances = item["starting_bank_balances"]
            equilibrium = item["equilibrium"]
            price = float(equilibrium["price"])
            participant_rows = item["participant_df"].to_dict(orient="records")
            demand_curve = []
            lower = market.price_lower_bound if market.price_lower_bound is not None else 0.0
            upper = market.price_upper_bound if market.price_upper_bound is not None else max(
                participant.penalty_price for participant in market.participants
            ) * 1.25
            point_count = 121
            for step in range(point_count):
                probe = lower + (upper - lower) * (step / (point_count - 1))
                per_part = [
                    participant.allowance_demand_or_supply(
                        probe,
                        starting_bank_balance=float(starting_bank_balances.get(participant.name, 0.0)),
                        expected_future_price=expected_future_price,
                        banking_allowed=market.banking_allowed,
                        borrowing_allowed=market.borrowing_allowed,
                        borrowing_limit=market.borrowing_limit,
                    )
                    for participant in market.participants
                ]
                demand_curve.append(
                    {
                        "p": probe,
                        "total": sum(per_part),
                        "perPart": per_part,
                    }
                )

            result = {
                "price": price,
                "Q": float(equilibrium["auction_sold"]),
                "auctionOffered": float(equilibrium["auction_offered"]),
                "auctionSold": float(equilibrium["auction_sold"]),
                "unsoldAllowances": float(equilibrium["unsold_allowances"]),
                "auctionCoverageRatio": float(equilibrium["coverage_ratio"]),
                "expectationRule": market.expectation_rule,
                "manualExpectedPrice": market.manual_expected_price,
                "expectedFuturePrice": expected_future_price,
                "totalAbate": float(sum(row["Abatement"] for row in participant_rows)),
                "totalTraded": float(sum(max(0.0, row["Net Allowances Traded"]) for row in participant_rows)),
                "revenue": float(market.calculate_auction_revenue(price, float(equilibrium["auction_sold"]))),
                "analysis": None,
                "perParticipant": [
                    {
                        "name": row["Participant"],
                        "technology": row.get("Chosen Technology", "Base Technology"),
                        "technology_mix": row.get("Technology Mix", ""),
                        "initial": row["Initial Emissions"],
                        "free": row["Free Allocation"],
                        "abatement": row["Abatement"],
                        "residual": row["Residual Emissions"],
                        "net_trade": row["Net Allowances Traded"],
                        "ratio": (
                            0.0
                            if row["Initial Emissions"] == 0
                            else row["Free Allocation"] / row["Initial Emissions"]
                        ),
                        "allowance_buys": row["Allowance Buys"],
                        "allowance_sells": row["Allowance Sells"],
                        "penalty_emissions": row["Penalty Emissions"],
                        "starting_bank_balance": row.get("Starting Bank Balance", 0.0),
                        "ending_bank_balance": row.get("Ending Bank Balance", 0.0),
                        "banked_allowances": row.get("Banked Allowances", 0.0),
                        "borrowed_allowances": row.get("Borrowed Allowances", 0.0),
                        "expected_future_price": row.get("Expected Future Price", 0.0),
                        "fixed_cost": row.get("Fixed Technology Cost", 0.0),
                        "abatement_cost": row["Abatement Cost"],
                        "allowance_cost": row["Allowance Cost"],
                        "penalty_cost": row["Penalty Cost"],
                        "sales_revenue": row["Sales Revenue"],
                        "total_compliance_cost": row["Total Compliance Cost"],
                        "indirect_emissions": row.get("Indirect Emissions", 0.0),
                        "scope2_cbam_liability": row.get("Scope 2 CBAM Liability", 0.0),
                        "cbam_liability": row.get("CBAM Liability", 0.0),
                        "sector": _lookup_sector(frontend_config, market.scenario_name, market.year, row["Participant"]),
                    }
                    for row in participant_rows
                ],
                "demandCurve": demand_curve,
            }
            by_scenario.setdefault(market.scenario_name, {})[str(market.year or "Base Year")] = result

    summary_records = summary_df.to_dict(orient="records")
    participant_records = participant_df.to_dict(orient="records")
    analysis = build_analysis(summary_df, participant_df)

    return {
        "config": frontend_config,
        "results": by_scenario,
        "summary": summary_records,
        "participants": participant_records,
        "analysis": analysis,
        "annual_plots": [],
        "plots": [],
        "output_dir": None,
        "warnings": _warnings,
    }


# ── Graph composer endpoints (blocks-graph-plan.md §5, Order 8) ─────────────


def _serialize_block_catalogue() -> dict:
    """Handle GET /api/blocks — the palette/param-form contract, §5.

    Delegates to ``ets.blocks.serialize`` (shared with ``ets.mcp``'s
    ``list_blocks``/``describe_block`` tools) — see that module's docstring
    for why the wire-shape functions live next to the catalogue rather than
    here.
    """
    return {"blocks": serialize_catalogue(BLOCK_CATALOGUE)}


def _handle_graph_validate(data: dict) -> dict:
    """Handle POST /api/graph/validate — always 200; 400 is JSON-parse-only."""
    try:
        graph = Graph.from_dict(data.get("graph") or {})
    except Exception as exc:
        return {"ok": False, "issues": [{"level": "error", "rule": "malformed", "message": str(exc)}]}
    issues = validate_graph(graph)
    return {
        "ok": not any(issue.level == "error" for issue in issues),
        "issues": [issue.to_dict() for issue in issues],
    }


def _compile_graph_or_raise(graph: Graph) -> dict:
    """Validate then compile, raising a summarised error on any ERROR issue.

    The caller (route dispatch) already turns any raised exception into a 400
    ``{"error": str(exc)}`` — this just makes that message useful instead of a
    raw CompileError/config_io traceback fragment. Delegates to
    ``ets.model_store.compile_graph_or_raise`` (shared with ``ets.mcp``'s
    ``run_model``/``save_model`` tools, which hit the same validate-then-compile
    step); ``ModelStoreError`` is a ``ValueError`` subclass so this stays a
    drop-in replacement for the pre-refactor bare-``ValueError`` version.
    """
    return compile_graph_or_raise(graph)


def _handle_graph_compile(data: dict) -> dict:
    """Handle POST /api/graph/compile — {graph} -> {"config": <scenario config>}."""
    graph = Graph.from_dict(data.get("graph") or {})
    return {"config": _compile_graph_or_raise(graph)}


def _handle_graph_run(data: dict) -> dict:
    """Handle POST /api/graph/run — today's /api/run payload plus a "graph" echo."""
    graph_payload = data.get("graph") or {}
    graph = Graph.from_dict(graph_payload)
    config = _compile_graph_or_raise(graph)
    payload = _build_dashboard_payload(config)
    payload["graph"] = graph_payload
    return payload


def _resolve_config_by_id(template_id: str | None) -> dict:
    """Resolve a template/user-model id to its compiled scenario config.

    The shared id-resolution step behind every "operate on an existing
    model" endpoint (``GET /api/graph/from-template``,
    ``GET /api/model-manifest``): both example templates (id == the
    ``examples/*.json`` stem) and saved user models (id ==
    ``user_<slug>``, as returned by ``_handle_graph_save_model`` /
    ``_save_user_scenario``) resolve through the same
    ``_predefined_templates()`` listing ``GET /api/templates`` serves, so a
    manifest or a from-template lookup for one id always agrees with what
    the template picker shows.

    Args:
        template_id: A template/user-model id, or ``None``.

    Returns:
        The resolved scenario-config dict (``_decorate_frontend_config``
        output).

    Raises:
        ValueError: ``template_id`` is falsy, or matches no known template.
    """
    if not template_id:
        raise ValueError("Query parameter 'id' is required.")
    for template in _predefined_templates():
        if template["id"] == template_id:
            return template["config"]
    raise ValueError(f"Unknown template id '{template_id}'.")


def _handle_graph_from_template(template_id: str | None) -> dict:
    """Handle GET /api/graph/from-template?id=<template_id> -> {"graph"}.

    For a ``user_<slug>`` model saved through ``_handle_graph_save_model``,
    the original composer graph is returned verbatim from its
    ``<slug>.graph.json`` sidecar when present, rather than reconstructed by
    decompiling the compiled scenario config — that round-trips exactly what
    the admin drew (including canvas metadata) instead of an approximation.
    User templates saved via the older ``/api/save-scenario`` flow (no
    sidecar) fall back to decompile, same as example templates.
    """
    if template_id and template_id.startswith("user_"):
        graph_path = USER_SCENARIOS_DIR / f"{template_id.removeprefix('user_')}.graph.json"
        if graph_path.exists():
            raw_graph = json.loads(graph_path.read_text(encoding="utf-8"))
            return {"graph": Graph.from_dict(raw_graph).to_dict()}
    return {"graph": graph_from_config(_resolve_config_by_id(template_id)).to_dict()}


def _handle_model_manifest_get(template_id: str | None) -> dict:
    """Handle GET /api/model-manifest?id=<template_id> -> the manifest dict.

    Resolves ``template_id`` exactly like ``GET /api/graph/from-template``
    (``_resolve_config_by_id``, which both example templates and saved
    ``user_<slug>`` models go through), then derives its manifest.
    """
    return derive_manifest(_resolve_config_by_id(template_id))


def _handle_model_manifest_post(data: dict) -> dict:
    """Handle POST /api/model-manifest — {config} -> the manifest dict.

    Args:
        data: A raw scenario-config dict (``{"scenarios": [...]}``), i.e.
            the same payload ``POST /api/run`` accepts.
    """
    return derive_manifest(data)


# Delegates to ets.model_store (shared with ets.mcp's save_model tool) —
# kept as a module-level name because ets.webapp / ets.web.handlers
# re-export it under this exact spelling for backward compatibility.
_slugify_filename = slugify_filename


def _handle_graph_save_model(data: dict) -> dict:
    """Handle POST /api/graph/save-model — "build" a graph into the scenario registry.

    Validates the graph and compiles it to a scenario config using the same
    convention as ``/api/graph/compile`` (a ``ValueError`` summarising every
    ERROR-level issue, turned into a 400 by the route dispatcher), then
    persists two files under ``USER_SCENARIOS_DIR`` so the result is both an
    ordinary runnable user scenario and a re-editable composer model:

    * ``<slug>.json`` — the compiled scenario config, saved through the same
      ``config_io.save_config`` helper as ``/api/save-scenario`` uses, so it
      is picked up by ``_predefined_templates`` (``GET /api/templates``) and
      runs unmodified through ``POST /api/run``.
    * ``<slug>.graph.json`` — the source composer graph verbatim, read back
      by ``_handle_graph_from_template`` so the admin can reopen this model
      for editing.

    Design note — sidecar file, not an embedded config key: an earlier
    design embedded the graph as a top-level ``"composer_graph"`` key on the
    scenario config. That does not survive the save/reload round trip:
    ``config_io.normalize_config`` (invoked by both ``save_config`` and
    ``load_config``, and therefore by every read of a user scenario file —
    ``/api/templates``, ``/api/run``, ``/api/graph/from-template`` decompile
    fallback) rebuilds its return value as exactly ``{"scenarios": [...]}``,
    unconditionally dropping any other top-level key. A sidecar file avoids
    fighting that normalization boundary.

    The validate-compile-persist logic itself lives in
    ``ets.model_store.save_graph_as_model`` — shared with ``ets.mcp``'s
    ``save_model`` tool, which needs a model saved through the composer
    conversation to appear in this same registry immediately. This handler
    is now just the HTTP-payload adapter around it.

    Args:
        data: Parsed request body, ``{"graph": <Graph wire dict>, "name": <display name>}``.

    Returns:
        ``{"id": "user_<slug>", "name": <name>, "config": <compiled config>}``.

    Raises:
        ValueError: Empty ``name``, or graph validation/compile failure.
    """
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("Request must include a non-empty 'name'.")
    graph = Graph.from_dict(data.get("graph") or {})
    saved = save_graph_as_model(graph, name, registry_dir=USER_SCENARIOS_DIR)

    return {
        "id": saved.id,
        "name": saved.name,
        "config": saved.config,
    }


def _save_user_scenario(payload: dict) -> dict:
    """Handle POST /api/save-scenario — the pre-composer raw-scenario save flow.

    Superseded by ``/api/graph/save-model`` (:func:`_handle_graph_save_model`)
    for anything drawn on the composer canvas, but still the save path for a
    scenario edited directly as JSON. Delegates to
    ``ets.model_store.save_config_as_model`` (shared registry-write path,
    same as every other save endpoint) rather than writing
    ``config_io.save_config`` straight to ``USER_SCENARIOS_DIR`` — that kept
    this handler's own file write from bypassing the active
    :class:`~pe.registry.backend.StorageBackend` (a saved-but-not-registered
    model would never show up in ``GET /api/templates`` or ``ets.mcp``'s
    ``list_models``).

    Args:
        payload: ``{"scenario": <scenario dict>, "filename": <optional
            override stem>}``.

    Returns:
        ``{"ok", "path", "filename", "template": {"id", "name", "source",
        "config"}}``.

    Raises:
        ValueError: Missing/empty ``scenario``/name, or (via
            :class:`~pe.model_store.ModelStoreError`, itself a
            ``ValueError``) an all-non-alphanumeric ``filename``.
    """
    scenario = payload.get("scenario")
    if not isinstance(scenario, dict):
        raise ValueError("Request must include a scenario object.")
    normalized_name = str(scenario.get("name", "")).strip()
    if not normalized_name:
        raise ValueError("Scenario must have a non-empty name before saving.")
    filename = payload.get("filename")
    saved = save_config_as_model(
        {"scenarios": [scenario]},
        str(filename or normalized_name),
        registry_dir=USER_SCENARIOS_DIR,
    )
    return {
        "ok": True,
        "path": str(saved.config_path),
        "filename": saved.config_path.name,
        "template": {
            "id": saved.id,
            "name": f"User · {saved.config_path.stem.replace('_', ' ').title()}",
            "source": "user",
            "config": _decorate_frontend_config(saved.config, template_id=saved.id),
        },
    }


def _lookup_sector(config: dict, scenario_name: str, year: str | None, participant_name: str) -> str:
    for scenario in config.get("scenarios", []):
        if scenario.get("name") != scenario_name:
            continue
        for year_item in scenario.get("years", []):
            if str(year_item.get("year")) != str(year):
                continue
            for participant in year_item.get("participants", []):
                if participant.get("name") == participant_name:
                    return participant.get("sector", "Other")
    return "Other"


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value


def _handle_calibrate(data: dict) -> dict:
    """Handle POST /api/calibrate — fit abatement slopes to observed prices."""
    from ..analysis.calibration import calibrate_slopes
    config = data.get("config")
    observed_prices = data.get("observed_prices", {})
    participant_names = data.get("participant_names", [])
    if not config:
        raise ValueError("Request must include a 'config' field.")
    if not observed_prices:
        raise ValueError("Request must include 'observed_prices' dict.")
    if not participant_names:
        raise ValueError("Request must include 'participant_names' list.")
    initial_slopes = data.get("initial_slopes")
    max_iter = int(data.get("max_iter", 500))
    return calibrate_slopes(
        base_config=config,
        observed_prices=observed_prices,
        participant_names=participant_names,
        initial_slopes=initial_slopes,
        max_iter=max_iter,
    )


def _handle_batch_run(data: dict) -> dict:
    """Handle POST /api/batch-run — sweep parameters and aggregate results."""
    from ..analysis.batch import run_batch
    config = data.get("config")
    sweeps = data.get("sweeps", [])
    if not config:
        raise ValueError("Request must include a 'config' field.")
    if not sweeps:
        raise ValueError("Request must include a 'sweeps' list.")
    return run_batch(base_config=config, sweeps=sweeps)


def _handle_narrative(data: dict) -> dict:
    """Handle POST /api/narrative — generate plain-language summary."""
    from ..analysis.narrative import generate_narrative
    results = data.get("results", [])
    scenario_name = str(data.get("scenario_name", ""))
    narrative = generate_narrative(results, scenario_name=scenario_name)
    return {"narrative": narrative}


def _handle_csv_import(body: bytes, headers) -> dict:
    """Handle POST /api/import-csv — convert CSV to ETS config."""
    from ..analysis.csv_import import csv_to_config
    content_type = headers.get("Content-Type", "") or headers.get("content-type", "") or ""

    if "multipart/form-data" in content_type:
        # Parse multipart — extract 'file' and optional 'scenario_name' fields
        # Use a simple boundary-based parser
        import email
        full = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
        msg = email.message_from_bytes(full)
        csv_text = None
        scenario_name = "Imported Scenario"
        for part in msg.walk():
            cd = part.get("Content-Disposition", "")
            if 'name="file"' in cd:
                csv_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
            elif 'name="scenario_name"' in cd:
                scenario_name = part.get_payload(decode=True).decode("utf-8", errors="replace").strip()
        if csv_text is None:
            raise ValueError("Multipart form must include a 'file' field with CSV content.")
    else:
        # Treat entire body as CSV text
        csv_text = body.decode("utf-8", errors="replace")
        scenario_name = "Imported Scenario"

    config = csv_to_config(csv_text, scenario_name=scenario_name)
    return {"config": config, "ok": True}


def build_analysis(summary_df: pd.DataFrame, participant_df: pd.DataFrame) -> list[str]:
    analysis: list[str] = []
    if summary_df.empty:
        return ["No simulation output was produced."]

    working_summary = summary_df.copy()
    if "Year" not in working_summary.columns:
        working_summary["Year"] = "Base Year"

    year_series = (
        participant_df["Year"]
        if "Year" in participant_df.columns
        else pd.Series(["Base Year"] * len(participant_df), index=participant_df.index)
    )

    for _, row in working_summary.iterrows():
        scenario = row["Scenario"]
        year = row["Year"]
        price = float(row["Equilibrium Carbon Price"])
        abatement = float(row["Total Abatement"])
        revenue = float(row["Total Auction Revenue"])
        scenario_slice = participant_df[
            (participant_df["Scenario"] == scenario) & (year_series == year)
        ]
        if scenario_slice.empty:
            analysis.append(
                f"{scenario} ({year}): equilibrium carbon price is {price:.2f}, total abatement is {abatement:.2f}, and auction revenue is {revenue:.2f}."
            )
            continue

        top_abatement = scenario_slice.sort_values("Abatement", ascending=False).iloc[0]
        biggest_buyer = scenario_slice.sort_values("Net Allowances Traded", ascending=False).iloc[0]
        biggest_seller = scenario_slice.sort_values("Net Allowances Traded", ascending=True).iloc[0]

        analysis.append(
            f"{scenario} ({year}): price clears at {price:.2f}; total abatement is {abatement:.2f}; auction revenue is {revenue:.2f}."
        )
        analysis.append(
            f"Compliance channels: firms abate {float(row.get('Total Abatement', 0.0)):.2f}, buy {float(row.get('Total Allowance Buys', 0.0)):.2f} allowances, sell {float(row.get('Total Allowance Sells', 0.0)):.2f}, and send {float(row.get('Total Penalty Emissions', 0.0)):.2f} emissions into the penalty channel."
        )
        analysis.append(
            f"Expectation rule: {row.get('Expectation Rule', 'next_year_baseline')} with expected future price {float(scenario_slice['Expected Future Price'].mean()) if 'Expected Future Price' in scenario_slice.columns else 0.0:.2f}."
        )
        if float(row.get("Total Banked Allowances", 0.0)) > 0.0 or float(
            row.get("Total Borrowed Allowances", 0.0)
        ) > 0.0:
            analysis.append(
                f"Intertemporal channel: firms carry {float(row.get('Total Banked Allowances', 0.0)):.2f} allowances forward and borrow {float(row.get('Total Borrowed Allowances', 0.0)):.2f} from future years."
            )
        analysis.append(
            f"Largest abatement comes from {top_abatement['Participant']} ({float(top_abatement['Abatement']):.2f}). Biggest buyer is {biggest_buyer['Participant']} ({float(biggest_buyer['Net Allowances Traded']):.2f}); biggest seller is {biggest_seller['Participant']} ({abs(float(biggest_seller['Net Allowances Traded'])):.2f})."
        )

    if len(working_summary) > 1:
        sorted_summary = working_summary.copy()
        sorted_summary["_year_sort"] = pd.to_numeric(sorted_summary["Year"], errors="coerce")
        sorted_summary = sorted_summary.sort_values(
            by=["Scenario", "_year_sort", "Year"], ascending=[True, True, True]
        )
        for scenario, group in sorted_summary.groupby("Scenario"):
            if len(group) < 2:
                continue
            first = group.iloc[0]
            last = group.iloc[-1]
            price_delta = float(last["Equilibrium Carbon Price"]) - float(first["Equilibrium Carbon Price"])
            abatement_delta = float(last["Total Abatement"]) - float(first["Total Abatement"])
            analysis.append(
                f"{scenario} trend: from {first['Year']} to {last['Year']}, carbon price changes by {price_delta:.2f} and total abatement changes by {abatement_delta:.2f}."
            )

    return analysis
