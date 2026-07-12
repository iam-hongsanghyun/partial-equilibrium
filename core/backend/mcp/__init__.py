"""Two AI-guided ETS MCP (Model Context Protocol) servers: composer + models.

A T5 app, same tier as ``pe.web``/``pe.cli`` (``tests/test_module_isolation.py``):
both servers wire the same primitives ``pe.web``'s endpoints use
(``pe.blocks``, ``pe.model_store``, ``pe.engine``, ``pe.analysis``) up as
MCP tools instead of HTTP routes, so an AI assistant can hold a conversation
with a user over stdio.

Role split between the two servers:

* **pe-composer** (``server.py`` + ``tools.py``) AUTHORS models — it holds a
  conversational block graph (``new_graph``/``add_block``/``set_params``/
  ``check``) and lets the user build a scenario turn by turn, then
  ``save_model``s it to the shared registry.
* **pe-models** (``models_server.py`` + ``models_tools.py``) OPERATES the
  already-configured registry that produces — ``list_models``,
  ``describe_model``, ``run_model``, ``compare_models``, ``sweep_model``,
  ``rename_model``/``delete_model``, ``model_manifest``. It never edits a
  model's internals; there is no add_block/set_params/new_graph equivalent
  here by design.

Package layout:

* ``tools.py`` / ``models_tools.py`` — the stateless tool implementations
  (importable and testable directly, with no MCP transport involved).
  ``models_tools.list_models`` is re-exported from ``tools.py`` rather than
  reimplemented — both servers list the identical registry.
* ``suggestions.py`` — the rule -> plain-language-suggestion table behind the
  composer's ``check`` tool's ``next_steps``.
* ``compact.py`` — the compact result/manifest shapes shared by both
  servers (``run_model``'s per-scenario/per-year summary,
  ``describe_model``'s manifest/mechanism overview, ``sweep_model``'s
  per-value headlines, ...).
* ``server.py`` / ``models_server.py`` — the FastMCP servers that register
  each module's functions and hold the server-level ``instructions``
  playbook.
* ``__main__.py`` — ``python -m pe.mcp`` entry point (composer, stdio
  transport). ``models/__main__.py`` is the analogous entry point for
  ``python -m pe.mcp.models`` (the governor) — a small subpackage that
  exists only to make that a valid module path, distinct from the flat
  ``models_server.py``/``models_tools.py`` it wires up (see that
  subpackage's docstring).

Install: the ``mcp`` optional-dependency group (``uv sync --extra mcp`` or
``--all-extras``). Registration: the repo-root ``.mcp.json`` (both servers).
"""

from __future__ import annotations

__all__: list[str] = []
