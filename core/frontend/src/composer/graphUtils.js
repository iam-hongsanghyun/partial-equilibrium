// Graph <-> React Flow helpers. No block-specific knowledge lives here —
// every rule reads from the block catalogue metadata (ports, params,
// constraints) served by GET /api/blocks (or the dev fixture).

import { autoLayout } from "./autoLayout.js";

function parseCardinality(cardinality) {
  const text = String(cardinality || "0..n");
  if (text === "1") return { min: 1, max: 1 };
  if (text === "0..1") return { min: 0, max: 1 };
  if (text === "1..n") return { min: 1, max: Infinity };
  return { min: 0, max: Infinity };
}

function blockById(catalogue, blockId) {
  return catalogue.find((block) => block.id === blockId) || null;
}

function findOutputPort(block, portName) {
  return (block?.ports?.outputs || []).find((port) => port.name === portName) || null;
}

function findInputPort(block, portName) {
  return (block?.ports?.inputs || []).find((port) => port.name === portName) || null;
}

function makeNodeId(blockId) {
  return `${blockId}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

function defaultParamsForBlock(block) {
  const values = {};
  (block?.params || []).forEach((paramSpec) => {
    values[paramSpec.name] = structuredClone(paramSpec.default ?? null);
  });
  return values;
}

// Returns { ok: boolean, reason: string|null } — used both to gate React
// Flow's isValidConnection and to explain a rejected drop to the user.
function evaluateConnection(catalogue, connection, existingEdges) {
  const { source, sourceHandle, target, targetHandle } = connection;
  if (!source || !target || !sourceHandle || !targetHandle) {
    return { ok: false, reason: "Connection is missing a source or target port." };
  }
  if (source === target) {
    return { ok: false, reason: "A block cannot connect to itself." };
  }
  const sourceBlock = blockById(catalogue, connection.sourceBlockId);
  const targetBlock = blockById(catalogue, connection.targetBlockId);
  if (!sourceBlock || !targetBlock) {
    return { ok: false, reason: "Unknown block type." };
  }
  if (sourceBlock.category === "policy" && targetBlock.category === "policy") {
    return { ok: false, reason: "Edges between two policy blocks are forbidden — their order is engine-fixed." };
  }
  const outputPort = findOutputPort(sourceBlock, sourceHandle);
  const inputPort = findInputPort(targetBlock, targetHandle);
  if (!outputPort || !inputPort) {
    return { ok: false, reason: "That port does not exist on this block." };
  }
  if (!(inputPort.accepts || []).includes(outputPort.type)) {
    return { ok: false, reason: `Port type mismatch: '${targetHandle}' does not accept '${outputPort.type}'.` };
  }
  const { max } = parseCardinality(inputPort.cardinality);
  const currentCount = (existingEdges || []).filter(
    (edge) => edge.target === target && edge.targetHandle === targetHandle
  ).length;
  if (currentCount >= max) {
    return { ok: false, reason: `Port '${targetHandle}' already has its maximum of ${inputPort.cardinality} connection(s).` };
  }
  return { ok: true, reason: null };
}

// Serializes composer state to the exact §2 graph schema. `nodes` are React
// Flow nodes with `data: { blockId, params }`; `edges` are React Flow edges
// with `sourceHandle`/`targetHandle`. Node positions are opaque canvas
// metadata, never part of the node payload itself.
function serializeGraph({ nodes, edges, viewport }) {
  const positions = {};
  nodes.forEach((node) => {
    positions[node.id] = { x: node.position.x, y: node.position.y };
  });
  return {
    version: 1,
    nodes: nodes.map((node) => ({
      id: node.id,
      block: node.data.blockId,
      params: node.data.params,
    })),
    edges: edges.map((edge) => ({
      source: edge.source,
      sourcePort: edge.sourceHandle,
      target: edge.target,
      targetPort: edge.targetHandle,
    })),
    meta: {
      canvas: {
        positions,
        zoom: viewport?.zoom ?? 1,
      },
    },
  };
}

// Inverse of serializeGraph — builds React Flow nodes/edges from a §2 graph
// document (e.g. loaded from GET /api/graph/from-template).
function deserializeGraph(graph, catalogue) {
  const positions = graph?.meta?.canvas?.positions || {};
  const rawNodes = graph?.nodes || [];
  const rawEdges = graph?.edges || [];
  // When a graph carries no saved canvas positions (every backend template /
  // decompiled config does), lay it out LEFT-TO-RIGHT from the edge DAG rather
  // than dropping nodes on a meaningless grid. A per-node saved position always
  // wins over the computed one.
  const layout = autoLayout(
    rawNodes.map((node) => ({
      id: node.id,
      category: blockById(catalogue, node.block)?.category || "unknown",
      order: node.params?.order,
    })),
    rawEdges.map((edge) => ({ source: edge.source, target: edge.target }))
  );
  const nodes = rawNodes.map((node, index) => {
    const block = blockById(catalogue, node.block);
    const fallbackPosition = layout[node.id] || { x: 80 + (index % 5) * 220, y: 80 + Math.floor(index / 5) * 180 };
    return {
      id: node.id,
      type: "blockNode",
      position: positions[node.id] || fallbackPosition,
      data: {
        blockId: node.block,
        block,
        label: block?.label || node.block,
        category: block?.category || "unknown",
        params: { ...defaultParamsForBlock(block), ...node.params },
      },
    };
  });
  const edges = rawEdges.map((edge, index) => ({
    id: `edge_${index}_${edge.source}_${edge.target}`,
    source: edge.source,
    sourceHandle: edge.sourcePort,
    target: edge.target,
    targetHandle: edge.targetPort,
  }));
  return { nodes, edges, zoom: graph?.meta?.canvas?.zoom ?? 1 };
}

export {
  parseCardinality,
  blockById,
  findOutputPort,
  findInputPort,
  makeNodeId,
  defaultParamsForBlock,
  evaluateConnection,
  serializeGraph,
  deserializeGraph,
};
