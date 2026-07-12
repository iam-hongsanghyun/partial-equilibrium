import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNodesState, useEdgesState } from "@xyflow/react";
import { ModelGraph } from "../composer/ModelGraph.jsx";
import { blockById, defaultParamsForBlock, deserializeGraph } from "../composer/graphUtils.js";
import { fetchBlockCatalogue } from "../composer/api.js";
import { expandModelGraph } from "./peModelExpand.js";
import { graphFromScenario, parseNodeTarget, sectorParamToKey } from "./peGraphFromConfig.js";

// pe.command "Canvas" tab: the module-locked, data-editable visual editor,
// BOUND to the App's live scenario config (the single source of truth). It
// REUSES the existing graph pipeline verbatim — graphFromScenario (config ->
// §2 wire doc) -> expandModelGraph (materialise sector / technology_option
// nodes) -> deserializeGraph (autoLayout left->right) -> ModelGraph (canvas +
// palette + ParamPanel). It writes edits BACK as TARGETED config updates
// through the two mutators the App hands down (updateScenarioYears /
// updateScenarioSectors), which already route a flat scenario vs. one market of
// a joint scenario. It never compiles the graph, so it can never corrupt the
// mechanism config the Model forms own.
//
// The only ADD/REMOVE/EDIT surface is the three data-entity blocks (company,
// sector, technology option) — the market / price-formation nodes AND the
// config-driven policy/mechanism nodes (MSR/CCR/floors/ceilings/CBAM/reserve/
// expectations/baseline/..., drawn by peGraphFromConfig.mechanismNodes) are
// display-locked (selectable, but their edits are not persisted and they carry
// no Remove), which is the module lock: mechanisms are drawn here so the Canvas
// shows the FULL model for context, but stay editable only on the Model tab.
// A locked node's id never matches parseNodeTarget's data-entity patterns, so
// onChangeParam writes nothing and selectedIsDataEntity gates the Remove off —
// no per-kind branching needed, the same discipline covers every locked node.

const DATA_ENTITY_BLOCKS = new Set(["participant", "sector", "technology_option"]);

function pickDisplayYear(scenario, activeYear) {
  const years = scenario?.years || [];
  return years.find((year) => String(year.year) === String(activeYear)) || years[0] || null;
}

function CanvasView({ scenario, activeYear, updateScenarioYears, updateScenarioSectors }) {
  const [catalogue, setCatalogue] = useState([]);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [status, setStatus] = useState("Loading model…");

  // Working copy of the scenario the canvas is editing. Seeded from the prop at
  // mount; thereafter the canvas is the writer (targeted mutators persist into
  // the App, which re-renders us with the same scenario), so we advance this
  // ref locally to keep add/remove rebuilds consistent without re-deriving the
  // whole graph on every keystroke (which would drop focus).
  const scenarioRef = useRef(scenario);

  const rebuildFrom = useCallback(
    (nextScenario, blocks) => {
      const displayYear = pickDisplayYear(nextScenario, activeYear);
      const wireDoc = graphFromScenario(nextScenario, blocks, displayYear);
      const expanded = expandModelGraph(wireDoc, blocks);
      const { nodes: nextNodes, edges: nextEdges } = deserializeGraph(expanded, blocks);
      setNodes(nextNodes);
      setEdges(nextEdges);
      setSelectedNodeId(null);
    },
    [activeYear]
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { blocks } = await fetchBlockCatalogue();
      if (cancelled) return;
      setCatalogue(blocks);
      scenarioRef.current = scenario;
      rebuildFrom(scenario, blocks);
      setStatus("Loaded");
    })();
    return () => {
      cancelled = true;
    };
    // Mount-only: the canvas is remounted (keyed on scenario id in app.jsx)
    // when the active scenario / market changes, so it always builds from the
    // current config; its own edits must NOT trigger a rebuild here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  // --- config write-back (targeted; never a full compile) --------------------

  // Advance the local working scenario and persist through the App's mutator.
  const mutateYears = useCallback(
    (mapYears, { rebuild }) => {
      const next = { ...scenarioRef.current, years: mapYears(scenarioRef.current.years || []) };
      scenarioRef.current = next;
      updateScenarioYears(mapYears);
      if (rebuild) rebuildFrom(next, catalogue);
    },
    [updateScenarioYears, rebuildFrom, catalogue]
  );

  const mutateSectors = useCallback(
    (mapSectors, { rebuild }) => {
      const next = { ...scenarioRef.current, sectors: mapSectors(scenarioRef.current.sectors || []) };
      scenarioRef.current = next;
      updateScenarioSectors(mapSectors);
      if (rebuild) rebuildFrom(next, catalogue);
    },
    [updateScenarioSectors, rebuildFrom, catalogue]
  );

  const setParticipantField = (index, field, value) =>
    mutateYears(
      (years) =>
        years.map((year) => ({
          ...year,
          participants: (year.participants || []).map((participant, i) =>
            i === index ? { ...participant, [field]: value } : participant
          ),
        })),
      { rebuild: false }
    );

  const setTechOptionField = (participantIndex, optionIndex, field, value) =>
    mutateYears(
      (years) =>
        years.map((year) => ({
          ...year,
          participants: (year.participants || []).map((participant, i) =>
            i === participantIndex
              ? {
                  ...participant,
                  technology_options: (participant.technology_options || []).map((option, j) =>
                    j === optionIndex ? { ...option, [field]: value } : option
                  ),
                }
              : participant
          ),
        })),
      { rebuild: false }
    );

  const setSectorField = (index, field, value) =>
    mutateSectors(
      (sectors) => sectors.map((sector, i) => (i === index ? { ...sector, [sectorParamToKey(field)]: value } : sector)),
      { rebuild: false }
    );

  // A live param edit updates the visible node (no rebuild -> keeps focus) and
  // writes the one changed field to config. Which config field is decided by
  // the node id alone (parseNodeTarget); param names equal config keys for
  // participant / technology_option, and sectorParamToKey covers `sector_name`.
  const onChangeParam = useCallback(
    (paramName, value) => {
      setNodes((current) =>
        current.map((node) =>
          node.id === selectedNodeId
            ? { ...node, data: { ...node.data, params: { ...node.data.params, [paramName]: value } } }
            : node
        )
      );
      if (!selectedNode) return;
      const target = parseNodeTarget(selectedNode.id);
      if (target.kind === "participant") setParticipantField(target.index, paramName, value);
      else if (target.kind === "technology_option") setTechOptionField(target.participantIndex, target.optionIndex, paramName, value);
      else if (target.kind === "sector") setSectorField(target.index, paramName, value);
    },
    // setParticipantField / setTechOptionField / setSectorField are stable
    // enough for this handler (they close over the same mutators/refs).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedNodeId, selectedNode]
  );

  // --- add / remove data entities (rebuild so ids stay canonical) ------------

  const blankParticipant = () => {
    const block = blockById(catalogue, "participant");
    const count = (pickDisplayYear(scenarioRef.current, activeYear)?.participants || []).length;
    return { ...defaultParamsForBlock(block), name: `Company ${count + 1}` };
  };

  const blankSector = () => {
    const count = (scenarioRef.current.sectors || []).length;
    return { name: `Sector ${count + 1}`, cap_trajectory: null, auction_share_trajectory: null, carbon_budget: 0 };
  };

  const blankTechOption = () => {
    const block = blockById(catalogue, "technology_option");
    return { ...defaultParamsForBlock(block), name: "New option" };
  };

  const addParticipant = () => {
    const entity = blankParticipant();
    mutateYears(
      (years) => years.map((year) => ({ ...year, participants: [...(year.participants || []), { ...entity }] })),
      { rebuild: true }
    );
  };

  const addSector = () => {
    const entity = blankSector();
    mutateSectors((sectors) => [...sectors, entity], { rebuild: true });
  };

  const addTechOption = (participantIndex) => {
    const entity = blankTechOption();
    mutateYears(
      (years) =>
        years.map((year) => ({
          ...year,
          participants: (year.participants || []).map((participant, i) =>
            i === participantIndex
              ? { ...participant, technology_options: [...(participant.technology_options || []), { ...entity }] }
              : participant
          ),
        })),
      { rebuild: true }
    );
  };

  // Drop from the palette: a company / sector attaches to the market; a
  // technology option attaches to the currently-selected company (mirrors the
  // PeModelView auto-wire). Config is the sink; the graph rebuilds from it.
  const onDrop = useCallback(
    (event) => {
      event.preventDefault();
      const blockId = event.dataTransfer.getData("application/x-composer-block");
      if (!DATA_ENTITY_BLOCKS.has(blockId)) return;
      if (blockId === "participant") addParticipant();
      else if (blockId === "sector") addSector();
      else if (blockId === "technology_option") {
        const target = selectedNode ? parseNodeTarget(selectedNode.id) : { kind: "other" };
        if (target.kind === "participant") addTechOption(target.index);
        else setStatus("Select a company first, then drop a technology option onto it.");
      }
    },
    // handlers close over stable mutators/refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedNode]
  );

  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const removeSelectedNode = useCallback(() => {
    if (!selectedNode) return;
    const target = parseNodeTarget(selectedNode.id);
    if (target.kind === "participant") {
      mutateYears(
        (years) => years.map((year) => ({ ...year, participants: (year.participants || []).filter((_, i) => i !== target.index) })),
        { rebuild: true }
      );
    } else if (target.kind === "sector") {
      mutateSectors((sectors) => sectors.filter((_, i) => i !== target.index), { rebuild: true });
    } else if (target.kind === "technology_option") {
      mutateYears(
        (years) =>
          years.map((year) => ({
            ...year,
            participants: (year.participants || []).map((participant, i) =>
              i === target.participantIndex
                ? { ...participant, technology_options: (participant.technology_options || []).filter((_, j) => j !== target.optionIndex) }
                : participant
            ),
          })),
        { rebuild: true }
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode]);

  return (
    <div className="composer-view">
      <div className="composer-toolbar">
        <div className="composer-toolbar-left">
          <span className="composer-source-badge">{status}</span>
        </div>
      </div>

      <ModelGraph
        paletteBlocks={dataEntityBlocks}
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onSelectionChange={setSelectedNodeId}
        selectedNode={selectedNode}
        selectedBlock={selectedBlock}
        onChangeParam={onChangeParam}
        onRemoveNode={selectedIsDataEntity ? removeSelectedNode : undefined}
      />
    </div>
  );
}

export { CanvasView };
