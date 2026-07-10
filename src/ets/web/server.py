from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

from ..core.paths import DOCS_DIR, FRONTEND_DIST_DIR
from .api import _json_safe
from .handlers import ASSET_CONTENT_TYPES
from .routes import ROUTES


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


class _FakeHeaders:
    def __init__(self, environ):
        self._ct = environ.get("CONTENT_TYPE", "")

    def get(self, key, default=""):
        if key.lower() in ("content-type", "Content-Type"):
            return self._ct
        return default


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/") or "/"
    query = {key: values[0] for key, values in parse_qs(environ.get("QUERY_STRING", "")).items()}

    route = ROUTES.get((method, path))
    if route is not None:
        if method == "GET":
            try:
                return _json_response(start_response, route(b"", _FakeHeaders(environ), query))
            except Exception as exc:
                return _json_response(start_response, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length) if length > 0 else b""
        try:
            payload = route(raw, _FakeHeaders(environ), query)
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
