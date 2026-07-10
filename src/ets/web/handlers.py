from __future__ import annotations

import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..core.paths import FRONTEND_DIST_DIR

# Transport-free API functions moved to web/api.py (Order 3); re-imported
# here so the ets.webapp shim surface stays byte-compatible.
from .api import (
    _build_dashboard_payload,
    _decorate_frontend_config,
    _handle_batch_run,
    _handle_calibrate,
    _handle_csv_import,
    _handle_narrative,
    _json_safe,
    _lookup_sector,
    _predefined_templates,
    _save_user_scenario,
    _slugify_filename,
    _WarningCollector,
    build_analysis,
)
from .routes import ROUTES

__all__ = [
    "ASSET_CONTENT_TYPES",
    "ETSRequestHandler",
    "launch_web_app",
    "build_analysis",
    "_predefined_templates",
    "_decorate_frontend_config",
    "_build_dashboard_payload",
    "_save_user_scenario",
    "_slugify_filename",
    "_lookup_sector",
    "_json_safe",
    "_WarningCollector",
    "_handle_calibrate",
    "_handle_batch_run",
    "_handle_narrative",
    "_handle_csv_import",
]

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


class ETSRequestHandler(BaseHTTPRequestHandler):
    server_version = "ETSWebApp/2.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_dist_asset("index.html")
            return
        if parsed.path.startswith("/api/"):
            route = ROUTES.get(("GET", parsed.path))
            if route is not None:
                query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                try:
                    self._write_json(route(b"", self.headers, query))
                except Exception as exc:
                    self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        relative_path = parsed.path.lstrip("/")
        self._serve_dist_asset(relative_path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            route = ROUTES.get(("POST", parsed.path))
            if route is None:
                # Preserve pre-routes behaviour: unknown POST paths parsed
                # the JSON body first, so a malformed body yields 400, a
                # well-formed one 404.
                json.loads(body.decode("utf-8")) if body else {}
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return
            query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            payload = route(body, self.headers, query)
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
