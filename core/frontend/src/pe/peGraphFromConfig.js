// pe.command Canvas tab ONLY: derive a §2 wire-graph document from ONE
// scenario config (the App's live `config` is the single source of truth), so
// the visual editor renders the SAME model the Model (forms) tab edits.
//
// This is the config->graph direction the Canvas needs at mount/rebuild. It is
// deliberately DISPLAY-oriented, not a full round-trip decompiler: it emits the
// EDITABLE data-entity graph the pe-shell canvas can edit — the market, its
// price-formation node, its companies (participants), sectors and technology
// options — PLUS the DISPLAY-LOCKED policy/mechanism nodes the config declares
// (see mechanismNodes below), so the Canvas shows the FULL model for context,
// not just the data entities. The Canvas never compiles this graph back to
// config (the reverse direction is a TARGETED field update, see CanvasView.jsx),
// so a mechanism node only affects what is drawn, never config integrity — the
// backend `graph_from_config` (blocks/decompile.py) remains the authority for a
// full graph, and mechanismNodes deliberately mirrors its structural-block
// synthesis (config-driven: a node appears IFF the mechanism is actually set).
//
// Node ids mirror decompile.py's scheme (`market0`, `market0_pf`,
// `market0_p<i>`), and `peModelExpand.expandModelGraph` then materialises
// `market0_sector<i>` and `market0_p<i>_opt<j>` from the opaque `sectors` /
// `technology_options` params — so a node id alone locates its config target
// (see parseNodeTarget), no per-node metadata threading required.

import { blockById } from "../composer/graphUtils.js";

const MARKET_ID = "market0";

// Price-formation block per modelling approach (mirrors decompile.py's
// _PF_BLOCK_FOR_APPROACH) — a display node only; falls back to competitive.
const PF_BLOCK_FOR_APPROACH = {
  competitive: "competitive_clearing",
  banking: "rubin_schennach_banking",
  hotelling: "hotelling",
  nash_cournot: "nash_cournot",
};

// A sector config entry keys its name as `name`; the `sector` block spells the
// same field `sector_name` (its other three params are config-key `sectors`
// too). This is the ONLY name divergence between a data entity's node params
// and its config keys — participant/technology_option config keys equal their
// param names, so those round-trip as identity.
const SECTOR_PARAM_TO_KEY = { sector_name: "name" };

function sectorParamToKey(paramName) {
  return SECTOR_PARAM_TO_KEY[paramName] || paramName;
}

// The year grid the carbon_market node displays — every year field except the
// per-year participant list (which becomes participant nodes instead).
function yearGrid(years) {
  return (years || []).map(({ participants, ...rest }) => rest);
}

// Mirror of decompile.py's `_equals_default`: arrays compare element-wise, every
// other value by strict identity.
function valuesEqual(value, other) {
  if (Array.isArray(value) && Array.isArray(other)) {
    if (value.length !== other.length) return false;
    return value.every((item, index) => item === other[index]);
  }
  return value === other;
}

// The catalogue default for a block's config field (params are keyed by
// ParamSpec.name; config_key carries the config field name — see peModelExpand).
function paramDefault(block, configKey) {
  const spec = (block?.params || []).find((param) => (param.config_key ?? param.name) === configKey);
  return spec ? spec.default : undefined;
}

// A year-scope mechanism is ACTIVE when any market year deviates from the
// block param's default for any of its config keys (decompile.py's `_year_field`
// / `_collapse` "reads like what a human actually drew" rule, minus the
// per-year collapse the display node does not need).
function yearScopeActive(scenario, block, configKeys) {
  const years = scenario.years || [];
  return configKeys.some((key) => {
    const def = paramDefault(block, key);
    return years.some((year) => {
      const value = year[key] === undefined ? def : year[key];
      return !valuesEqual(value, def);
    });
  });
}

// DISPLAY-LOCKED policy/mechanism nodes for ONE scenario, mirroring the
// structural-block synthesis in decompile.py's `_decompile_market_body`
// (node ids, block ids and market ports all match its scheme). CONFIG-DRIVEN:
// a node appears IFF the config actually sets that mechanism — `msr_enabled`, a
// non-default year value, a non-empty trajectory, a non-zero reference price —
// so a bare model draws none. These nodes are VIEW-ONLY on the Canvas: their
// ids never match parseNodeTarget's data-entity patterns, so the Canvas never
// persists an edit to them and never offers a Remove (the module structure is
// locked; the user edits mechanisms on the Model tab). OBA owns no config keys
// (never synthesised, matching decompile), and banking is drawn as the price-
// formation node already (model_approach -> rubin_schennach_banking), so neither
// gets a separate mechanism node here.
function mechanismNodes(scenario, catalogue) {
  const nodes = [];
  const edges = [];

  const addPolicy = (nodeSuffix, blockId) => {
    if (!blockById(catalogue, blockId)) return;
    const id = `${MARKET_ID}_${nodeSuffix}`;
    nodes.push({ id, block: blockId, params: {} });
    edges.push({ source: id, sourcePort: "policy", target: MARKET_ID, targetPort: "policies" });
  };

  // Flag-gated scenario-scope mechanisms (msr/ccr/investment).
  if (scenario.msr_enabled) {
    const mode = scenario.msr_mode ?? "bank_threshold";
    addPolicy("msr", mode === "bank_threshold" ? "msr_bank_threshold" : "kmsr_decree");
  }
  if (scenario.ccr_enabled) addPolicy("ccr", "ccr");
  if (scenario.investment_feedback_enabled) addPolicy("investment", "endogenous_investment");

  // Year-scope price-control / policy blocks (active on any deviating year).
  const yearBlocks = [
    { suffix: "floor", blockId: "price_floor", keys: ["price_lower_bound"], trajectory: "price_floor_trajectory" },
    { suffix: "ceiling", blockId: "price_ceiling", keys: ["price_upper_bound"], trajectory: "price_ceiling_trajectory" },
    { suffix: "reserve", blockId: "auction_reserve", keys: ["auction_reserve_price", "minimum_bid_coverage", "unsold_treatment"] },
    { suffix: "cancel", blockId: "cancellation", keys: ["cancelled_allowances"] },
    { suffix: "cbam", blockId: "cbam", keys: ["eua_price", "eua_prices", "eua_price_ensemble"] },
    { suffix: "hoard", blockId: "hoarding", keys: ["hoarding_inflow"] },
  ];
  yearBlocks.forEach(({ suffix, blockId, keys, trajectory }) => {
    const block = blockById(catalogue, blockId);
    if (!block) return;
    const active = yearScopeActive(scenario, block, keys) || (trajectory && scenario[trajectory]);
    if (active) addPolicy(suffix, blockId);
  });

  // Scenario-scope trajectory / value policy blocks.
  if (scenario.cap_trajectory) addPolicy("cap", "cap_path");
  if (scenario.free_allocation_trajectories) addPolicy("falloc", "free_allocation_phaseout");

  // Expectations (its own port) and the price-elastic baseline (its own port).
  const expBlock = blockById(catalogue, "expectations");
  if (expBlock && yearScopeActive(scenario, expBlock, ["expectation_rule", "manual_expected_price"])) {
    const id = `${MARKET_ID}_exp`;
    nodes.push({ id, block: "expectations", params: {} });
    edges.push({ source: id, sourcePort: "expectations", target: MARKET_ID, targetPort: "expectations" });
  }
  if (scenario.reference_carbon_price && blockById(catalogue, "price_elastic_baseline")) {
    const id = `${MARKET_ID}_baseline`;
    nodes.push({ id, block: "price_elastic_baseline", params: {} });
    edges.push({ source: id, sourcePort: "baseline", target: MARKET_ID, targetPort: "baseline" });
  }

  return { nodes, edges };
}

// Build the §2 wire document for ONE scenario, using `displayYear`'s
// participants as the model's company structure. `sectors` and each
// participant's `technology_options` stay as opaque list params here —
// expandModelGraph turns them into their own nodes downstream.
function graphFromScenario(scenario, catalogue, displayYear) {
  if (!scenario) return { version: 1, nodes: [], edges: [], meta: {} };
  const nodes = [];
  const edges = [];

  const marketParams = { name: scenario.name, years: yearGrid(scenario.years) };
  if ((scenario.sectors || []).length) marketParams.sectors = scenario.sectors;
  nodes.push({ id: MARKET_ID, block: "carbon_market", params: marketParams });

  const pfBlockId = PF_BLOCK_FOR_APPROACH[scenario.model_approach] || "competitive_clearing";
  if (blockById(catalogue, pfBlockId)) {
    nodes.push({ id: `${MARKET_ID}_pf`, block: pfBlockId, params: {} });
    edges.push({ source: `${MARKET_ID}_pf`, sourcePort: "price_formation", target: MARKET_ID, targetPort: "price_formation" });
  }

  const participants = (displayYear?.participants) || (scenario.years?.[0]?.participants) || [];
  participants.forEach((participant, index) => {
    const id = `${MARKET_ID}_p${index}`;
    nodes.push({ id, block: "participant", params: { ...participant, order: index } });
    edges.push({ source: id, sourcePort: "compliance", target: MARKET_ID, targetPort: "participants" });
  });

  // Draw the config's DISPLAY-LOCKED policy/mechanism blocks (view-only) so the
  // Canvas shows the full model, not just its data entities.
  const mechanism = mechanismNodes(scenario, catalogue);
  nodes.push(...mechanism.nodes);
  edges.push(...mechanism.edges);

  return { version: 1, nodes, edges, meta: {} };
}

// Locate the config target a canvas node id maps to. Ids are the decompile.py /
// expandModelGraph scheme, so the id alone is enough — no side table.
function parseNodeTarget(nodeId) {
  let match;
  if ((match = /^market\d+_p(\d+)_opt(\d+)$/.exec(nodeId))) {
    return { kind: "technology_option", participantIndex: Number(match[1]), optionIndex: Number(match[2]) };
  }
  if ((match = /^market\d+_p(\d+)$/.exec(nodeId))) {
    return { kind: "participant", index: Number(match[1]) };
  }
  if ((match = /^market\d+_sector(\d+)$/.exec(nodeId))) {
    return { kind: "sector", index: Number(match[1]) };
  }
  return { kind: "other" };
}

export { graphFromScenario, parseNodeTarget, sectorParamToKey, MARKET_ID };
