from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

from ..config import DOCS_DIR, FRONTEND_DIST_DIR
from .handlers import (
    ASSET_CONTENT_TYPES,
    _build_dashboard_payload,
    _json_safe,
    _predefined_templates,
    _save_user_scenario,
    _handle_calibrate,
    _handle_batch_run,
    _handle_narrative,
    _handle_csv_import,
)


def _json_response(start_response, payload: dict, status: HTTPStatus = HTTPStatus.OK):
    data = json.dumps(_json_safe(payload), allow_nan=False).encode("utf-8")
    start_response(
        f"{status.value} {status.phrase}",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(data))),
        ],
    )
    return [data]


def _file_response(start_response, path: Path):
    if not path.exists() or not path.is_file():
        return _json_response(start_response, {"error": "Not found"}, HTTPStatus.NOT_FOUND)
    data = path.read_bytes()
    start_response(
        f"{HTTPStatus.OK.value} {HTTPStatus.OK.phrase}",
        [
            ("Content-Type", ASSET_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")),
            ("Content-Length", str(len(data))),
        ],
    )
    return [data]


def _safe_path(root: Path, relative_path: str) -> Path | None:
    resolved = (root / relative_path).resolve()
    if resolved != root.resolve() and root.resolve() not in resolved.parents:
        return None
    return resolved


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/") or "/"
    _ = parse_qs(environ.get("QUERY_STRING", ""))

    if method == "GET" and path == "/api/templates":
        return _json_response(start_response, {"templates": _predefined_templates()})

    if method == "POST" and path == "/api/run":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length) if length > 0 else b"{}"
        try:
            payload = _build_dashboard_payload(json.loads(raw.decode("utf-8")))
            return _json_response(start_response, payload)
        except Exception as exc:  # pragma: no cover - deployment path
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    if method == "POST" and path == "/api/save-scenario":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length) if length > 0 else b"{}"
        try:
            payload = _save_user_scenario(json.loads(raw.decode("utf-8")))
            return _json_response(start_response, payload)
        except Exception as exc:  # pragma: no cover - deployment path
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    if method == "POST" and path == "/api/calibrate":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length) if length > 0 else b"{}"
        try:
            payload = _handle_calibrate(json.loads(raw.decode("utf-8")))
            return _json_response(start_response, payload)
        except Exception as exc:
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    if method == "POST" and path == "/api/batch-run":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length) if length > 0 else b"{}"
        try:
            payload = _handle_batch_run(json.loads(raw.decode("utf-8")))
            return _json_response(start_response, payload)
        except Exception as exc:
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    if method == "POST" and path == "/api/narrative":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length) if length > 0 else b"{}"
        try:
            payload = _handle_narrative(json.loads(raw.decode("utf-8")))
            return _json_response(start_response, payload)
        except Exception as exc:
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    if method == "POST" and path == "/api/import-csv":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length) if length > 0 else b""

        class _FakeHeaders:
            def __init__(self, environ):
                self._ct = environ.get("CONTENT_TYPE", "")

            def get(self, key, default=""):
                if key.lower() in ("content-type", "Content-Type"):
                    return self._ct
                return default

        try:
            payload = _handle_csv_import(raw, _FakeHeaders(environ))
            return _json_response(start_response, payload)
        except Exception as exc:
            return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    if method != "GET":
        return _json_response(start_response, {"error": "Method not allowed"}, HTTPStatus.METHOD_NOT_ALLOWED)

    if path == "/":
        return _file_response(start_response, FRONTEND_DIST_DIR / "index.html")

    if path.startswith("/api/"):
        return _json_response(start_response, {"error": "Not found"}, HTTPStatus.NOT_FOUND)

    # Serve the documentation tree (tutorials HTML + reference markdown) so users
    # can study it from the deployed app. /docs/<path> → repo docs/<path>.
    if path.startswith("/docs/"):
        doc = _safe_path(DOCS_DIR, path[len("/docs/"):])
        if doc is None:
            return _json_response(start_response, {"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
        return _file_response(start_response, doc)

    safe = _safe_path(FRONTEND_DIST_DIR, path.lstrip("/"))
    if safe is None:
        return _json_response(start_response, {"error": "Forbidden"}, HTTPStatus.FORBIDDEN)
    if safe.exists() and safe.is_file():
        return _file_response(start_response, safe)
    return _file_response(start_response, FRONTEND_DIST_DIR / "index.html")


def create_app():
    """Return the WSGI application callable."""
    return app


__all__ = ["create_app", "app", "_json_response", "_file_response", "_safe_path"]
