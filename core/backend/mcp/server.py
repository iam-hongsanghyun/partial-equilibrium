"""FastMCP server: wires ``pe.mcp.tools`` functions up as MCP tools over stdio.

Every tool in ``pe.mcp.tools`` is a stateless, plain function
(``Graph.from_dict -> ... -> Graph.to_dict``), so this module has nothing to
do except register them and describe the composer conversation loop in
``instructions`` (the server-level playbook every MCP client surfaces to its
model). See ``pe.mcp.tools``'s module docstring for the "graph document is
the conversation state" design principle this whole server rests on.

Run: ``python -m pe.mcp`` (stdio transport — the shape ``.mcp.json`` at the
repo root registers for Claude Code/Desktop).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import tools

SERVER_NAME = "pe-composer"

INSTRUCTIONS = """\
You help a user compose an ETS (emissions-trading-system) scenario model by \
talking it through, not by asking them to write JSON by hand.

The graph document is the conversation's state: you hold it (the "graph" \
dict every mutating tool returns), pass it back into the next tool call, \
and narrate what changed in plain language. Every tool is stateless -- \
there is no server-side session, so if you lose track of the current graph \
just ask the user to re-share it or start over with new_graph().

Workflow:
1. Start from the user's question ("model a cap-and-trade market with a \
reserve", "reproduce the K-MSR paper", "add a price floor to my model"). \
Call list_models() and list_blocks() to see what already exists before \
proposing anything specific -- prefer starting from a matching example or \
saved model over a blank graph.
2. Call new_graph() for a blank minimum-viable market (one participant, one \
year, competitive clearing), or new_graph(template_id=...) to start from an \
example or a previously saved model.
3. Propose blocks one or two at a time, in plain language, explaining what \
each one does and what it needs (describe_block(block_id) gives its \
params/ports/requires/excludes). Only call add_block / set_params / \
remove_node once the user agrees to that specific change.
4. ALWAYS call check(graph) again after every mutation. Read its \
"next_steps": for each one, ask the user the question it poses -- do not \
silently apply the suggested fix yourself. Only mutate the graph again once \
they say yes.
5. Once check(graph)["ok"] is true, call run_model(graph) and summarise the \
result in plain language (price path, abatement, bank/MSR/CCR activity if \
present) -- never dump the raw tool output verbatim, and never report a \
number that didn't come back from run_model.
6. When the user is happy with the model, offer save_model(graph, name). \
Mention that a saved model appears immediately in both run.command's \
template picker and pe.command's model list.

Do not guess at economically meaningful defaults (CCR reference values, MSR \
thresholds, carbon budgets, discount rates) on the user's behalf -- ask \
them, or point them at describe_block's declared defaults/units and let \
them decide.
"""


def build_server() -> FastMCP:
    """Construct the FastMCP server with every composer tool registered."""
    server = FastMCP(name=SERVER_NAME, instructions=INSTRUCTIONS)
    for fn in (
        tools.list_models,
        tools.list_blocks,
        tools.describe_block,
        tools.new_graph,
        tools.add_block,
        tools.set_params,
        tools.remove_node,
        tools.check,
        tools.run_model,
        tools.save_model,
    ):
        server.tool()(fn)
    return server


mcp = build_server()


def main() -> None:
    """Entry point for ``python -m pe.mcp`` — serve over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
