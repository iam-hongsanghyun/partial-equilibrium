"""Entry point for ``python -m pe.mcp`` — starts the composer MCP server on stdio."""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()
