// pe-shell ONLY: expand a decompiled model graph's hidden detail into
// editable data-entity nodes, so a concrete loaded model can be SEEN and its
// data entities (companies / sectors / technology options) edited on the
// canvas. The builder/composer graph is untouched by this — it keeps sectors
// and technology_options as opaque list params (its golden round-trip).
//
// This is a pure graph->graph transform on the §2 wire document (BEFORE
// deserializeGraph). It is CONFIG-SAFE: `compile_graph` already accepts the
// node representation of both sectors (a `sector` node wired into the market's
// `sectors` port) and technology options (a `technology_option` node wired
// into a participant's `options` port) as an equivalent of the opaque params,
// so a Run of the expanded graph compiles to the SAME config — plus whatever
// the user edited. We therefore MOVE the data out of the opaque param and into
// the node (never both — compile rejects the collision), keeping the round
// trip intact.
//
// Config-driven: a sector / technology_option node is synthesised IFF the
// config declares it. A model with no sectors shows no sector nodes.

import { blockById } from "../composer/graphUtils.js";

const PER_YEAR_KEY = "__per_year__";

function isPlainArray(value) {
  return Array.isArray(value);
}

function paramsFromEntry(block, entry) {
  // Map a config entry (keyed by config_key) onto a node's params (keyed by
  // ParamSpec.name), collecting any leftover keys into the same opaque `_extra`
  // pass-through compile understands.
  const params = {};
  const known = new Set();
  (block?.params || []).forEach((spec) => {
    known.add(spec.config_key);
    if (entry[spec.config_key] !== undefined) {
      params[spec.name] = entry[spec.config_key];
    }
  });
  const extra = {};
  Object.keys(entry || {}).forEach((key) => {
    if (!known.has(key)) extra[key] = entry[key];
  });
  if (Object.keys(extra).length) params._extra = extra;
  return params;
}

// graph: the §2 document from GET /api/graph/from-template. Returns a new
// document with sector / technology_option nodes materialised.
function expandModelGraph(graph, catalogue) {
  if (!graph) return graph;
  const nodes = (graph.nodes || []).map((node) => ({ ...node, params: { ...node.params } }));
  const edges = (graph.edges || []).map((edge) => ({ ...edge }));
  const sectorBlock = blockById(catalogue, "sector");
  const techBlock = blockById(catalogue, "technology_option");

  const marketNodes = nodes.filter((node) => node.block === "carbon_market");

  marketNodes.forEach((market) => {
    // Participants wired into this market's `participants` port.
    const participantIds = edges
      .filter((edge) => edge.target === market.id && edge.targetPort === "participants")
      .map((edge) => edge.source);
    const participantNodes = participantIds
      .map((id) => nodes.find((node) => node.id === id))
      .filter((node) => node && node.block === "participant");

    // Sector nodes from the market's opaque `sectors` list param (the config
    // bearing sectors). Each becomes a node wired `pool -> market.sectors`; the
    // opaque param is then removed so compile reads the nodes, not the param.
    const sectorsParam = market.params.sectors;
    const sectorNameToId = new Map();
    if (sectorBlock && isPlainArray(sectorsParam) && sectorsParam.length) {
      sectorsParam.forEach((entry, index) => {
        const nodeId = `${market.id}_sector${index}`;
        nodes.push({
          id: nodeId,
          block: "sector",
          params: {
            sector_name: entry.name ?? "New Sector",
            cap_trajectory: entry.cap_trajectory ?? null,
            auction_share_trajectory: entry.auction_share_trajectory ?? null,
            carbon_budget: entry.carbon_budget ?? 0,
            order: index,
          },
        });
        edges.push({ source: nodeId, sourcePort: "pool", target: market.id, targetPort: "sectors" });
        sectorNameToId.set(String(entry.name ?? "New Sector"), nodeId);
      });
      delete market.params.sectors;

      // Group each participant under the sector its `sector_group` names — a
      // display grouping (member_of -> sector.members); compile ignores these
      // edges, so grouping never changes the config.
      participantNodes.forEach((participant) => {
        const group = participant.params?.sector_group;
        if (group && sectorNameToId.has(String(group))) {
          edges.push({
            source: participant.id,
            sourcePort: "member_of",
            target: sectorNameToId.get(String(group)),
            targetPort: "members",
          });
        }
      });
    }
  });

  // Technology options: one `technology_option` node per entry in a
  // participant's `technology_options` list param, wired `option ->
  // participant.options`. Only a plain (not per-year) list is expanded; the
  // opaque param is removed so compile reads the nodes.
  nodes
    .filter((node) => node.block === "participant")
    .forEach((participant) => {
      const options = participant.params.technology_options;
      if (!techBlock || !isPlainArray(options) || !options.length) return;
      if (options.some((entry) => entry && typeof entry === "object" && PER_YEAR_KEY in entry)) return;
      options.forEach((entry, index) => {
        const nodeId = `${participant.id}_opt${index}`;
        nodes.push({
          id: nodeId,
          block: "technology_option",
          params: { ...paramsFromEntry(techBlock, entry), order: index },
        });
        edges.push({ source: nodeId, sourcePort: "option", target: participant.id, targetPort: "options" });
      });
      delete participant.params.technology_options;
    });

  return { ...graph, nodes, edges };
}

export { expandModelGraph };
