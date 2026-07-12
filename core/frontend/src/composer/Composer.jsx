import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ReactFlowProvider,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ModelGraph } from "./ModelGraph.jsx";
import {
  fetchBlockCatalogue,
  fetchTemplates,
  fetchGraphFromTemplate,
  validateGraph,
  compileGraph,
  runGraph,
  saveModel,
} from "./api.js";
import {
  blockById,
  makeNodeId,
  defaultParamsForBlock,
  evaluateConnection,
  serializeGraph,
  deserializeGraph,
} from "./graphUtils.js";
import { autoLayout } from "./autoLayout.js";
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

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function ComposerCanvas() {
  const [catalogue, setCatalogue] = useState([]);
  const [catalogueSource, setCatalogueSource] = useState(null);
  const [catalogueError, setCatalogueError] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeId, setSelectedNodeId] = useState(null);

  const [issues, setIssues] = useState([]);
  const [validated, setValidated] = useState(false);
  const [highlightNodeId, setHighlightNodeId] = useState(null);
  const [highlightEdgeIndex, setHighlightEdgeIndex] = useState(null);

  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);

  const [runPayload, setRunPayload] = useState(null);
  const [runScenarioId, setRunScenarioId] = useState(null);
  const [runActiveYear, setRunActiveYear] = useState(null);
  const [runSelPart, setRunSelPart] = useState(null);
  const [runStacked, setRunStacked] = useState(true);

  const { screenToFlowPosition, getViewport, setCenter } = useReactFlow();

  useEffect(() => {
    fetchBlockCatalogue()
      .then(({ blocks, source }) => {
        setCatalogue(blocks);
        setCatalogueSource(source);
      })
      .catch((error) => setCatalogueError(String(error?.message || error)));
    fetchTemplates().then(setTemplates);
  }, []);

  const selectedNode = useMemo(() => nodes.find((node) => node.id === selectedNodeId) || null, [nodes, selectedNodeId]);
  const selectedBlock = selectedNode?.data?.block || null;

  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      const blockId = event.dataTransfer.getData("application/x-composer-block");
      if (!blockId) return;
      const block = blockById(catalogue, blockId);
      if (!block) return;
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      const id = makeNodeId(blockId);
      const newNode = {
        id,
        type: "blockNode",
        position,
        data: {
          blockId,
          block,
          label: block.label,
          category: block.category,
          params: defaultParamsForBlock(block),
        },
      };
      setNodes((current) => current.concat(newNode));
    },
    [catalogue, screenToFlowPosition, setNodes]
  );

  const isValidConnection = useCallback(
    (connection) => {
      const sourceNode = nodes.find((node) => node.id === connection.source);
      const targetNode = nodes.find((node) => node.id === connection.target);
      const check = evaluateConnection(
        catalogue,
        {
          ...connection,
          sourceBlockId: sourceNode?.data?.blockId,
          targetBlockId: targetNode?.data?.blockId,
        },
        edges
      );
      return check.ok;
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

  const buildGraph = useCallback(
    () => serializeGraph({ nodes, edges, viewport: getViewport() }),
    [nodes, edges, getViewport]
  );

  const handleTidy = useCallback(() => {
    setNodes((current) => {
      const layout = autoLayout(
        current.map((node) => ({ id: node.id, category: node.data?.category, order: node.data?.params?.order })),
        edges.map((edge) => ({ source: edge.source, target: edge.target }))
      );
      return current.map((node) => (layout[node.id] ? { ...node, position: layout[node.id] } : node));
    });
  }, [edges, setNodes]);

  const handleValidate = useCallback(async () => {
    setBusy("validate");
    setNotice(null);
    const graph = buildGraph();
    const result = await validateGraph(graph);
    setBusy(null);
    if (result.unavailable) {
      setNotice({ kind: "validate", message: "Backend endpoint not available yet: POST /api/graph/validate." });
      setIssues([]);
      setValidated(false);
      return;
    }
    if (!result.ok) {
      setNotice({ kind: "validate", message: result.error || "Validation request failed." });
      return;
    }
    setIssues(result.data.issues || []);
    setValidated(true);
  }, [buildGraph]);

  const handleRun = useCallback(async () => {
    setBusy("run");
    setNotice(null);
    const graph = buildGraph();
    const result = await runGraph(graph);
    setBusy(null);
    if (result.unavailable) {
      setNotice({ kind: "run", message: "Backend endpoint not available yet: POST /api/graph/run." });
      return;
    }
    if (!result.ok) {
      setNotice({ kind: "run", message: result.error || "Run failed." });
      return;
    }
    const payload = result.data;
    setRunPayload(payload);
    // Select the first per-market pseudo-scenario (a linked run has one per
    // market; a single-market run has exactly one, unchanged).
    const firstScenario = flattenRunScenarios(payload.config?.scenarios || [])[0];
    setRunScenarioId(firstScenario?.id || null);
    setRunActiveYear(firstScenario?.years?.[0]?.year || null);
    setRunSelPart(null);
  }, [buildGraph]);

  const handleCompile = useCallback(async () => {
    setBusy("compile");
    setNotice(null);
    const graph = buildGraph();
    const result = await compileGraph(graph);
    setBusy(null);
    if (result.unavailable) {
      setNotice({ kind: "compile", message: "Backend endpoint not available yet: POST /api/graph/compile." });
      return;
    }
    if (!result.ok) {
      setNotice({ kind: "compile", message: result.error || "Compile failed." });
      return;
    }
    downloadJson(result.data.config, "scenario-config.json");
  }, [buildGraph]);

  const handleLoadTemplate = useCallback(async () => {
    if (!selectedTemplateId) return;
    setBusy("template");
    setNotice(null);
    const result = await fetchGraphFromTemplate(selectedTemplateId);
    setBusy(null);
    if (result.unavailable) {
      setNotice({ kind: "template", message: "Backend endpoint not available yet: GET /api/graph/from-template." });
      return;
    }
    if (!result.ok) {
      setNotice({ kind: "template", message: result.error || "Failed to load template." });
      return;
    }
    const { nodes: newNodes, edges: newEdges } = deserializeGraph(result.data.graph, catalogue);
    setNodes(newNodes);
    setEdges(newEdges);
    setSelectedNodeId(null);
    setIssues([]);
    setValidated(false);
    setRunPayload(null);
  }, [selectedTemplateId, catalogue, setNodes, setEdges]);

  const handleClearCanvas = useCallback(() => {
    if (!nodes.length && !edges.length) return;
    if (!window.confirm("Clear the canvas? This removes every node and connection.")) return;
    setNodes([]);
    setEdges([]);
    setSelectedNodeId(null);
    setIssues([]);
    setValidated(false);
    setNotice(null);
    setRunPayload(null);
  }, [nodes.length, edges.length, setNodes, setEdges]);

  const handleSaveModel = useCallback(async () => {
    const name = window.prompt("Name this model:", "");
    if (name == null) return;
    const trimmedName = name.trim();
    if (!trimmedName) {
      setNotice({ kind: "save-model", message: "Model name cannot be empty." });
      return;
    }
    setBusy("save-model");
    setNotice(null);
    const graph = buildGraph();
    const result = await saveModel(graph, trimmedName);
    setBusy(null);
    if (result.unavailable) {
      setNotice({ kind: "save-model", message: "Backend endpoint not available yet: POST /api/graph/save-model." });
      return;
    }
    if (!result.ok) {
      setNotice({ kind: "save-model", message: result.error || "Save model failed." });
      return;
    }
    setNotice({
      kind: "save-model",
      message: `Saved "${result.data.name}" as ${result.data.id} — available in the main app's template list.`,
    });
  }, [buildGraph]);

  const handleIssueClick = useCallback(
    (issue) => {
      if (issue.node) {
        setSelectedNodeId(issue.node);
        setHighlightNodeId(issue.node);
        setHighlightEdgeIndex(null);
        setNodes((current) => current.map((node) => ({ ...node, selected: node.id === issue.node })));
        const target = nodes.find((node) => node.id === issue.node);
        if (target) {
          setCenter(target.position.x + 90, target.position.y + 60, { zoom: 1, duration: 300 });
        }
      } else if (issue.edge != null) {
        setHighlightNodeId(null);
        setHighlightEdgeIndex(issue.edge);
      }
    },
    [nodes, setNodes, setCenter]
  );

  const displayNodes = useMemo(
    () =>
      nodes.map((node) =>
        node.id === highlightNodeId ? { ...node, className: "composer-node-issue-highlight" } : { ...node, className: undefined }
      ),
    [nodes, highlightNodeId]
  );
  const displayEdges = useMemo(
    () =>
      edges.map((edge, index) =>
        index === highlightEdgeIndex
          ? { ...edge, className: "composer-edge-issue-highlight", animated: true }
          : { ...edge, className: undefined, animated: false }
      ),
    [edges, highlightEdgeIndex]
  );

  const errorCount = issues.filter((issue) => issue.level === "error").length;
  const warningCount = issues.filter((issue) => issue.level === "warning").length;

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

  // Joint-equilibrium diagnostics come straight from the summary rows the
  // backend stamps ONLY on cyclic-SCC markets (present-guard): an acyclic /
  // single-market run has no such row, so every branch below is inert for it.
  const jointRows = useMemo(() => jointRowsFromSummary(runPayload?.summary), [runPayload]);
  const jointProblems = useMemo(() => jointProblemsFromRows(jointRows), [jointRows]);
  const activeJointRow = jointRowForScenario(jointRows, activeRunScenario?.name);

  return (
    <div className="composer-view">
      <div className="composer-toolbar">
        <div className="composer-toolbar-left">
          {catalogueSource === "fixture" && (
            <span className="composer-source-badge">Dev fixture — GET /api/blocks unavailable</span>
          )}
        </div>
        <div className="composer-toolbar-actions">
          <select
            value={selectedTemplateId}
            onChange={(event) => setSelectedTemplateId(event.target.value)}
            disabled={!templates.length}
            title="Start from an example model"
          >
            <option value="">Start from an example model...</option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>{template.name}</option>
            ))}
          </select>
          <button className="ghost-btn" disabled={!selectedTemplateId || busy === "template"} onClick={handleLoadTemplate}>
            Load example
          </button>
          <button className="ghost-btn" disabled={!nodes.length} onClick={handleTidy}>
            Tidy layout
          </button>
          <button className="ghost-btn" disabled={!nodes.length || busy === "validate"} onClick={handleValidate}>
            Validate
          </button>
          <button className="ghost-btn" disabled={!nodes.length || busy === "run"} onClick={handleRun}>
            Run
          </button>
          <button className="ghost-btn" disabled={!nodes.length || busy === "compile"} onClick={handleCompile}>
            Export config
          </button>
          <button className="ghost-btn" disabled={!nodes.length || busy === "save-model"} onClick={handleSaveModel}>
            Save model
          </button>
          <button
            className="ghost-btn danger-btn"
            disabled={!nodes.length && !edges.length}
            onClick={handleClearCanvas}
          >
            Clear canvas
          </button>
        </div>
      </div>

      {catalogueError && (
        <div className="server-warnings-banner">
          <div className="server-warnings-list">
            <div className="server-warning-item">Failed to load block catalogue: {catalogueError}</div>
          </div>
        </div>
      )}
      {notice && (
        <div className="server-warnings-banner">
          <div className="server-warnings-list">
            <div className="server-warning-item">{notice.message}</div>
          </div>
          <button className="server-warnings-close" onClick={() => setNotice(null)} title="Dismiss">Dismiss</button>
        </div>
      )}
      <JointNonConvergenceBanner problems={jointProblems} />

      <ModelGraph
        paletteBlocks={catalogue}
        nodes={displayNodes}
        edges={displayEdges}
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
        onRemoveNode={removeSelectedNode}
        allowKeyboardDelete
        paramPanelChildren={
          validated && (
            <div className="builder-card composer-issues-card">
              <div className="builder-card-head">
                <div>
                  <div className="eyebrow">Validation</div>
                  <h4>Graph checks</h4>
                </div>
                <div className="validation-summary">
                  <span className="validation-pill error">{errorCount} errors</span>
                  <span className="validation-pill warning">{warningCount} warnings</span>
                </div>
              </div>
              <div className="validation-list">
                {issues.length === 0 && <p className="muted">No issues found.</p>}
                {issues.map((issue, index) => (
                  <button
                    key={index}
                    type="button"
                    className={`validation-item ${issue.level} clickable`}
                    onClick={() => handleIssueClick(issue)}
                  >
                    <div className="validation-item-head">
                      <span className={`validation-dot ${issue.level}`}></span>
                      <strong>{issue.node ? `Node: ${issue.node}` : issue.edge != null ? `Edge #${issue.edge}` : "Graph"}</strong>
                    </div>
                    <div className="validation-message">{issue.message}</div>
                  </button>
                ))}
              </div>
            </div>
          )
        }
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

function Composer() {
  return (
    <ReactFlowProvider>
      <ComposerCanvas />
    </ReactFlowProvider>
  );
}

export { Composer };
