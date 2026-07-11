from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# `pe` resolves from the installed wheel (requirements.txt `.`), not sys.path:
# a split package (core/backend + modules/*/backend) is not reconstructable by
# putting directories on the path — only the package_dir finder reunites it.
# But the wheel's pe.core.paths lives in site-packages, so it cannot locate
# the checkout's frontend dist / examples / docs by relative parents() alone
# (vercel.json's includeFiles copies core/backend/**, core/frontend/dist/**,
# examples/**, docs/** to this checkout). Pin the data root explicitly before
# `pe` is imported so pe.core.paths.PROJECT_DIR anchors here, not site-packages.
os.environ.setdefault("PE_PROJECT_DIR", str(PROJECT_DIR))

from pe.web.server import app  # noqa: E402

__all__ = ["app"]  # re-exported for the @vercel/python ASGI/WSGI runtime
