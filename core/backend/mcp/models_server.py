"""FastMCP server: wires ``pe.mcp.models_tools`` up as MCP tools over stdio.

The governance/operate-time counterpart to ``pe.mcp.server`` (the
composer). Role split (see ``INSTRUCTIONS`` below, and
``pe.mcp.models_tools``'s module docstring): ``pe-composer`` AUTHORS
models — it holds a conversational block graph and mutates it
(``add_block``/``set_params``/...); ``pe-models`` OPERATES the
already-configured model registry it produces — list, inspect, run,
compare, sweep, and rename/delete registry entries. There is no
add_block/set_params/new_graph equivalent here by design.

Run: ``python -m pe.mcp.models`` (stdio transport — the shape ``.mcp.json``
at the repo root registers for Claude Code/Desktop, alongside
``pe-composer``). See ``pe.mcp.models``'s ``__main__.py`` for why this
server's entry point is a small subpackage distinct from the flat
``models_tools.py``/``models_server.py`` modules it wires up: keeping the
implementation flat, directly under ``pe.mcp`` alongside ``tools.py``/
``server.py``, means both servers share one package's dependency law and
``tests/test_module_isolation.py`` tier (T5, by the ``pe.mcp.*`` prefix)
with no extra classification rule needed.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import models_tools

SERVER_NAME = "pe-models"

INSTRUCTIONS = """\
You operate the ETS (emissions-trading-system) model registry: the bundled \
examples under examples/ and every model saved to the shared registry under \
user-scenarios/ (the same registry pe-composer's save_model writes to, and \
the web composer's "Save model" too).

Role boundary: this server OPERATES already-configured models -- it never \
edits a model's internals. There is no add_block/set_params/new_graph tool \
here. If the user wants to change what a model contains (add a block, \
tweak a parameter, wire something new), tell them to use the pe-composer \
server instead: new_graph(template_id=<model_id>) loads this model onto its \
canvas there. This server only lists, inspects, runs, compares, sweeps, and \
renames/deletes registry entries.

Workflow:
1. Call list_models() first to see what is available -- never guess a \
model id.
2. Call describe_model(model_id) before running anything unfamiliar: it \
reports the model's scenarios, year span, participants, and configured \
mechanisms (price-formation/policy/expectations blocks) without running \
the solver. Call model_manifest(model_id) instead if you need the raw \
per-scenario feature/approach breakdown.
3. Call run_model(model_id, scenario=...) to solve one model and get a \
compact per-year summary (price, auction sold, abatement, bank if \
present). Never dump a raw table -- only report numbers that came back \
from a tool call.
4. To compare up to 4 models side by side (e.g. "with vs without MSR"), \
call compare_models(model_ids, scenario=...) -- it aligns results by year \
and adds a one-line price-delta summary. It rejects more than 4 models \
with a clear error; narrow the list instead of guessing which to drop.
5. To explore sensitivity to one parameter, call sweep_model(model_id, \
parameter_path, values) with a dotted config path (e.g. \
"scenarios[0].years[*].total_cap") and at most 8 values -- it returns \
final-year price and cumulative abatement per value, not every year of \
every run.
6. rename_model(model_id, new_name) and delete_model(model_id) only work \
on registry entries someone saved (ids starting with "user_") -- bundled \
examples are immutable and both calls reject them with a clear error. \
Confirm with the user before deleting; it is not reversible.

Do not fabricate a model's configuration or results -- everything you say \
about a model must come from this server's own tool output \
(describe_model/run_model/compare_models/sweep_model/model_manifest), \
never guessed or remembered from a previous turn.
"""


def build_server() -> FastMCP:
    """Construct the FastMCP server with every governor tool registered."""
    server = FastMCP(name=SERVER_NAME, instructions=INSTRUCTIONS)
    for fn in (
        models_tools.list_models,
        models_tools.describe_model,
        models_tools.run_model,
        models_tools.compare_models,
        models_tools.sweep_model,
        models_tools.rename_model,
        models_tools.delete_model,
        models_tools.model_manifest,
        models_tools.list_sessions,
        models_tools.run_session,
    ):
        server.tool()(fn)
    return server


mcp = build_server()


def main() -> None:
    """Entry point for ``python -m pe.mcp.models`` — serve over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
