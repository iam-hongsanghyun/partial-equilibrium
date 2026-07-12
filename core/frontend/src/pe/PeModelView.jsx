import { useCallback, useEffect, useMemo, useState } from "react";
import { ReactFlowProvider, addEdge, useNodesState, useEdgesState, useReactFlow } from "@xyflow/react";
import { ModelGraph } from "../composer/ModelGraph.jsx";
import {
  blockById,
  makeNodeId,
  defaultParamsForBlock,
  evaluateConnection,
  serializeGraph,
  deserializeGraph,
} from "../composer/graphUtils.js";
import { fetchBlockCatalogue, fetchGraphFromTemplate, runGraph } from "../composer/api.js";
import { autoLayout } from "../composer/autoLayout.js";
import { expandModelGraph } from "./peModelExpand.js";
import { AnalysisView } from "../components/AppViews.jsx";
import { buildDraftResult } from "../components/AppShared.jsx";
import {
  flattenRunScenarios,
  jointRowsFromSummary,
  jointProblemsFromRows,
  jointRowForScenario,
  JointNonConvergenceBanner,
  JointConvergenceCard,
} from "../components/MultiMarket.jsx";
import { SectorInteraction } from "../components/SectorInteraction.jsx";

// The only blocks a pe-shell user may ADD/REMOVE: the model's DATA entities.
// The module/mechanism/market structure is fixed by the loaded model.
const DATA_ENTITY_BLOCKS = new Set(["participant", "sector", "technology_option"]);

// Where a freshly dropped data entity auto-attaches: a company/sector to the
// market, a technology option to the selected company. Nothing here can wire a
// mechanism — evaluateConnection + the data-entity source guard forbid it.
const AUTO_WIRE = {
  participant: { sourcePort: "compliance", targetBlock: "carbon_market", targetPort: "participants" },
  sector: { sourcePort: "pool", targetBlock: "carbon_market", targetPort: "sectors" },
  technology_option: { sourcePort: "option", targetBlock: "participant", targetPort: "options" },
};

function PeModelCanvas({ templateId }) {
  const [catalogue, setCatalogue] = useState([]);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [status, setStatus] = useState("Loading model…");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const [runPayload, setRunPayload] = useState(null);
  const [runScenarioId, setRunScenarioId] = useState(null);
  const [runActiveYear, setRunActiveYear] = useState(null);
  const [runSelPart, setRunSelPart] = useState(null);
  const [runStacked, setRunStacked] = useState(true);

  const { screenToFlowPosition, getViewport } = useReactFlow();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { blocks } = await fetchBlockCatalogue();
      if (cancelled) return;
      setCatalogue(blocks);
      const result = await fetchGraphFromTemplate(templateId);
      if (cancelled) return;
      if (!result.ok) {
        setStatus(result.unavailable ? "Model graph endpoint unavailable." : result.error || "Failed to load model.");
        return;
      }
      const expanded = expandModelGraph(result.data.graph, blocks);
      const { nodes: newNodes, edges: newEdges } = deserializeGraph(expanded, blocks);
      setNodes(newNodes);
      setEdges(newEdges);
      setStatus("Loaded");
    })();
    return () => {
      cancelled = true;
    };
  }, [templateId, setNodes, setEdges]);

  const dataEntityBlocks = useMemo(
    () => catalogue.filter((block) => DATA_ENTITY_BLOCKS.has(block.id)),
    [catalogue]
  );

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || null,
    [nodes, selectedNodeId]
  );
  const selectedBlock = selectedNode?.data?.block || null;
  const selectedIsDataEntity = selectedNode ? DATA_ENTITY_BLOCKS.has(selectedNode.data?.blockId) : false;

  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      const blockId = event.dataTransfer.getData("application/x-composer-block");
      if (!blockId || !DATA_ENTITY_BLOCKS.has(blockId)) return;
      const block = blockById(catalogue, blockId);
      if (!block) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      const id = makeNodeId(blockId);
      const newNode = {
        id,
        type: "blockNode",
        position,
        data: { blockId, block, label: block.label, category: block.category, params: defaultParamsForBlock(block) },
      };
      setNodes((current) => current.concat(newNode));

      // Auto-attach to the natural parent so the added entity is live at once.
      const wire = AUTO_WIRE[blockId];
      if (wire) {
        const parent =
          wire.targetBlock === "participant"
            ? (selectedIsDataEntity && selectedNode?.data?.blockId === "participant" ? selectedNode : null)
            : nodes.find((node) => node.data?.blockId === wire.targetBlock);
        if (parent) {
          setEdges((current) =>
            addEdge(
              {
                id: `edge_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
                source: id,
                sourceHandle: wire.sourcePort,
                target: parent.id,
                targetHandle: wire.targetPort,
              },
              current
            )
          );
        }
      }
    },
    [catalogue, screenToFlowPosition, setNodes, setEdges, nodes, selectedNode, selectedIsDataEntity]
  );

  // A connection is permitted only when it is a DATA-entity relationship: the
  // catalogue ports must match (evaluateConnection) AND the source must be one
  // of the three data-entity blocks — so no mechanism/market rewiring.
  const isValidConnection = useCallback(
    (connection) => {
      const sourceNode = nodes.find((node) => node.id === connection.source);
      const targetNode = nodes.find((node) => node.id === connection.target);
      const sourceBlockId = sourceNode?.data?.blockId;
      if (!DATA_ENTITY_BLOCKS.has(sourceBlockId)) return false;
      return evaluateConnection(
        catalogue,
        { ...connection, sourceBlockId, targetBlockId: targetNode?.data?.blockId },
        edges
      ).ok;
    },
    [nodes, edges, catalogue]
  );

  const onConnect = useCallback(
    (connection) => {
      setEdges((current) =>
        addEdge({ ...connection, id: `edge_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}` }, current)
      );
    },
    [setEdges]
  );

  const updateSelectedNodeParam = useCallback(
    (paramName, value) => {
      setNodes((current) =>
        current.map((node) =>
          node.id === selectedNodeId
            ? { ...node, data: { ...node.data, params: { ...node.data.params, [paramName]: value } } }
            : node
        )
      );
    },
    [selectedNodeId, setNodes]
  );

  const removeSelectedNode = useCallback(() => {
    setNodes((current) => current.filter((node) => node.id !== selectedNodeId));
    setEdges((current) => current.filter((edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId));
    setSelectedNodeId(null);
  }, [selectedNodeId, setNodes, setEdges]);

  const handleTidy = useCallback(() => {
    setNodes((current) => {
      const layout = autoLayout(
        current.map((node) => ({ id: node.id, category: node.data?.category, order: node.data?.params?.order })),
        edges.map((edge) => ({ source: edge.source, target: edge.target }))
      );
      return current.map((node) => (layout[node.id] ? { ...node, position: layout[node.id] } : node));
    });
  }, [edges, setNodes]);

  const handleRun = useCallback(async () => {
    setBusy(true);
    setNotice(null);
    const graph = serializeGraph({ nodes, edges, viewport: getViewport() });
    const result = await runGraph(graph);
    setBusy(false);
    if (result.unavailable) {
      setNotice("Run endpoint not available: POST /api/graph/run.");
      return;
    }
    if (!result.ok) {
      setNotice(result.error || "Run failed.");
      return;
    }
    const payload = result.data;
    setRunPayload(payload);
    const firstScenario = flattenRunScenarios(payload.config?.scenarios || [])[0];
    setRunScenarioId(firstScenario?.id || null);
    setRunActiveYear(firstScenario?.years?.[0]?.year || null);
    setRunSelPart(null);
  }, [nodes, edges, getViewport]);

  const runScenarios = useMemo(
    () => flattenRunScenarios(runPayload?.config?.scenarios || []),
    [runPayload]
  );
  const activeRunScenario = runScenarios.find((scenario) => scenario.id === runScenarioId) || runScenarios[0] || null;
  const activeRunYearObj =
    activeRunScenario?.years?.find((year) => String(year.year) === String(runActiveYear)) || activeRunScenario?.years?.[0] || null;
  const activeRunResult = activeRunScenario && activeRunYearObj
    ? runPayload.results?.[activeRunScenario.name]?.[String(activeRunYearObj.year)] || buildDraftResult(activeRunYearObj)
    : null;

  const jointRows = useMemo(() => jointRowsFromSummary(runPayload?.summary), [runPayload]);
  const jointProblems = useMemo(() => jointProblemsFromRows(jointRows), [jointRows]);
  const activeJointRow = jointRowForScenario(jointRows, activeRunScenario?.name);

  return (
    <div className="composer-view">
      <div className="composer-toolbar">
        <div className="composer-toolbar-left">
          <span className="composer-source-badge">{status}</span>
        </div>
        <div className="composer-toolbar-actions">
          <button className="ghost-btn" disabled={!nodes.length} onClick={handleTidy}>Tidy layout</button>
          <button className="ghost-btn" disabled={!nodes.length || busy} onClick={handleRun}>Run</button>
        </div>
      </div>

      {notice && (
        <div className="server-warnings-banner">
          <div className="server-warnings-list">
            <div className="server-warning-item">{notice}</div>
          </div>
          <button className="server-warnings-close" onClick={() => setNotice(null)} title="Dismiss">Dismiss</button>
        </div>
      )}
      <JointNonConvergenceBanner problems={jointProblems} />

      <ModelGraph
        paletteBlocks={dataEntityBlocks}
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onSelectionChange={setSelectedNodeId}
        selectedNode={selectedNode}
        selectedBlock={selectedBlock}
        onChangeParam={updateSelectedNodeParam}
        onRemoveNode={selectedIsDataEntity ? removeSelectedNode : undefined}
      />

      {runPayload && activeRunScenario && activeRunYearObj && (
        <div className="composer-run-results">
          <nav className="hdr-scenarios">
            {runScenarios.map((scenario) => (
              <button
                key={scenario.id}
                className={"pill-btn " + (runScenarioId === scenario.id ? "on" : "")}
                style={{ "--c": scenario.color }}
                onClick={() => {
                  setRunScenarioId(scenario.id);
                  setRunActiveYear(scenario.years?.[0]?.year || null);
                  setRunSelPart(null);
                }}
              >
                <i className="sw" style={{ background: scenario.color }}></i>{scenario.name}
              </button>
            ))}
          </nav>
          <JointConvergenceCard row={activeJointRow} />
          <SectorInteraction
            summary={runPayload.summary}
            scenarioName={activeRunScenario ? String(activeRunScenario.name).split(" :: ")[0] : null}
          />
          <AnalysisView
            scenario={activeRunScenario}
            yearObj={activeRunYearObj}
            activeYear={runActiveYear}
            onYearChange={setRunActiveYear}
            result={activeRunResult}
            results={runPayload.results || {}}
            scenarios={runScenarios}
            stacked={runStacked}
            onToggleStacked={() => setRunStacked((value) => !value)}
            dragSupply={() => {}}
            selPart={runSelPart}
            setSelPart={setRunSelPart}
            analysis={runPayload.analysis || []}
          />
        </div>
      )}
    </div>
  );
}

export function PeModelView({ templateId }) {
  return (
    <ReactFlowProvider>
      <PeModelCanvas templateId={templateId} />
    </ReactFlowProvider>
  );
}
