import { ReactFlow, Background, Controls } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { BlockNode } from "./BlockNode.jsx";
import { Palette } from "./Palette.jsx";
import { ParamPanel } from "./ParamPanel.jsx";

const NODE_TYPES = { blockNode: BlockNode };

// Shared ReactFlow canvas: palette + graph + ParamPanel, laid out with the
// exact composer-layout markup so the composer is visually unchanged. This
// component carries NO policy of its own — every capability is driven by the
// props the host passes:
//   - `paletteBlocks` non-empty      -> a palette is shown (drag to add).
//   - `onConnect` present            -> nodes are connectable.
//   - `onDrop` present               -> the canvas accepts drops.
//   - `onRemoveNode` present         -> ParamPanel shows a Remove button.
//   - `allowKeyboardDelete` true     -> the Delete/Backspace key removes.
// The composer host passes the full set (unchanged behaviour); the pe-shell
// host passes a restricted set (module-locked, data-entity editable).
function ModelGraph({
  paletteBlocks = [],
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  isValidConnection,
  onDrop,
  onDragOver,
  onSelectionChange,
  selectedNode,
  selectedBlock,
  onChangeParam,
  onRemoveNode,
  allowKeyboardDelete = false,
  paramPanelChildren = null,
}) {
  const connectable = Boolean(onConnect);
  return (
    <div className="composer-layout">
      {paletteBlocks.length > 0 && <Palette blocks={paletteBlocks} />}
      <div
        className="composer-canvas-wrap"
        onDrop={onDrop}
        onDragOver={onDragOver}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          nodesConnectable={connectable}
          nodesDraggable
          deleteKeyCode={allowKeyboardDelete ? undefined : null}
          onSelectionChange={({ nodes: selectedNodes }) => onSelectionChange(selectedNodes[0]?.id || null)}
          fitView
          fitViewOptions={{ maxZoom: 1 }}
          minZoom={0.2}
          maxZoom={2}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
      <div className="composer-side">
        <ParamPanel
          node={selectedNode}
          block={selectedBlock}
          onChangeParam={onChangeParam}
          onRemoveNode={onRemoveNode}
        />
        {paramPanelChildren}
      </div>
    </div>
  );
}

export { ModelGraph };
