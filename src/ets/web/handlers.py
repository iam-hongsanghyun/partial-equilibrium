from __future__ import annotations

import json
import logging
import math
import threading
import webbrowser
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from ..config import EXAMPLES_DIR, FRONTEND_DIST_DIR, USER_SCENARIOS_DIR
from ..config_io import blank_config, build_markets_from_config, load_config, save_config
from ..solvers.simulation import run_simulation, solve_scenario_path

ASSET_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".map": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def _predefined_templates() -> list[dict]:
    templates = [
        {
            "id": "blank",
            "name": "Blank Custom Config",
            "config": _decorate_frontend_config(blank_config(), template_id="blank"),
        }
    ]
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            config = load_config(path)
        except Exception:
            # Skip non-scenario JSONs (e.g. API request payload examples)
            continue
        template_id = path.stem
        label = path.stem.replace("_", " ").title()
        templates.append(
            {
                "id": template_id,
                "name": label,
                "source": "example",
                "config": _decorate_frontend_config(config, template_id=template_id),
            }
        )
    USER_SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(USER_SCENARIOS_DIR.glob("*.json")):
        config = load_config(path)
        template_id = f"user_{path.stem}"
        label = path.stem.replace("_", " ").title()
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
    ets_logger = logging.getLogger("src.ets")
    ets_logger.addHandler(_log_handler)
    try:
        summary_df, participant_df = run_simulation(markets)
    finally:
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


def _slugify_filename(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "scenario"


def _save_user_scenario(payload: dict) -> dict:
    scenario = payload.get("scenario")
    if not isinstance(scenario, dict):
        raise ValueError("Request must include a scenario object.")
    normalized_name = str(scenario.get("name", "")).strip()
    if not normalized_name:
        raise ValueError("Scenario must have a non-empty name before saving.")
    filename = payload.get("filename")
    stem = _slugify_filename(filename or normalized_name)
    path = USER_SCENARIOS_DIR / f"{stem}.json"
    USER_SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    save_config({"scenarios": [scenario]}, path)
    saved_config = load_config(path)
    return {
        "ok": True,
        "path": str(path),
        "filename": path.name,
        "template": {
            "id": f"user_{path.stem}",
            "name": f"User · {path.stem.replace('_', ' ').title()}",
            "source": "user",
            "config": _decorate_frontend_config(saved_config, template_id=f"user_{path.stem}"),
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


class ETSRequestHandler(BaseHTTPRequestHandler):
    server_version = "ETSWebApp/2.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_dist_asset("index.html")
            return
        if parsed.path == "/api/templates":
            self._write_json({"templates": _predefined_templates()})
            return
        if parsed.path.startswith("/api/"):
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        relative_path = parsed.path.lstrip("/")
        self._serve_dist_asset(relative_path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            if parsed.path == "/api/import-csv":
                payload = _handle_csv_import(body, self.headers)
            else:
                data = json.loads(body.decode("utf-8")) if body else {}
                if parsed.path == "/api/run":
                    payload = _build_dashboard_payload(data)
                elif parsed.path == "/api/save-scenario":
                    payload = _save_user_scenario(data)
                elif parsed.path == "/api/calibrate":
                    payload = _handle_calibrate(data)
                elif parsed.path == "/api/batch-run":
                    payload = _handle_batch_run(data)
                elif parsed.path == "/api/narrative":
                    payload = _handle_narrative(data)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                    return
            self._write_json(payload)
        except Exception as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args) -> None:
        return

    def _serve_dist_asset(self, relative_path: str) -> None:
        safe_path = (FRONTEND_DIST_DIR / relative_path).resolve()
        if FRONTEND_DIST_DIR.resolve() not in safe_path.parents and safe_path != FRONTEND_DIST_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not safe_path.exists() or not safe_path.is_file():
            safe_path = FRONTEND_DIST_DIR / "index.html"
        self._serve_file(safe_path)

    def _serve_file(self, path: Path) -> None:
        content_type = ASSET_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(_json_safe(payload), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def launch_web_app(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), ETSRequestHandler)
    url = f"http://{host}:{port}/"
    print(f"Starting ETS web UI at {url}")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


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
