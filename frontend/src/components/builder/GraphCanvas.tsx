// GraphCanvas — SVG-based interactive DAG with drag-to-connect edges.
//
// Nodes are positioned by phase (x) and user-drag (y). Edges render as
// bezier curves with arrowheads. Click a node to select, drag to move,
// drag from a port to create an edge.

import { useRef, useState, useCallback, useMemo } from "react";
import type { BuilderNode, BuilderEdge } from "../../lib/types";

interface Props {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
  selectedNodeId: string | null;
  selectedEdgeIdx: number | null;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (idx: number | null) => void;
  onMoveNode: (id: string, x: number, y: number) => void;
  onConnectNodes: (source: string, target: string) => void;
  onAddNode: (x: number, y: number) => void;
}

// ── Node colors by type ──────────────────────────────────────────────

const TYPE_COLORS: Record<string, { fill: string; stroke: string; text: string }> = {
  event:       { fill: "#1e1b4b", stroke: "#6366f1", text: "#a5b4fc" },
  price:       { fill: "#1a2e05", stroke: "#65a30d", text: "#bef264" },
  indicator:   { fill: "#172554", stroke: "#3b82f6", text: "#93c5fd" },
  gate:        { fill: "#3b0764", stroke: "#a855f7", text: "#d8b4fe" },
  deadline:    { fill: "#450a0a", stroke: "#ef4444", text: "#fca5a5" },
  conditional: { fill: "#431407", stroke: "#f97316", text: "#fdba74" },
  reversal:    { fill: "#134e4a", stroke: "#2dd4bf", text: "#99f6e4" },
  constraint:  { fill: "#1c1917", stroke: "#a8a29e", text: "#d6d3d1" },
};

const NODE_W = 180;
const NODE_H = 56;
const PORT_R = 6;

// ── State badge colors ───────────────────────────────────────────────

const STATE_DOT: Record<string, string> = {
  fired: "#ef4444",
  approaching: "#d4a843",
  active: "#3b82f6",
  monitoring: "#525252",
  stable: "#2dd4bf",
  resolved: "#22c55e",
  partial: "#f59e0b",
};

export default function GraphCanvas({
  nodes, edges, selectedNodeId, selectedEdgeIdx,
  onSelectNode, onSelectEdge, onMoveNode, onConnectNodes, onAddNode,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  // Pan & zoom state
  const [pan, setPan] = useState({ x: 40, y: 40 });
  const [zoom, setZoom] = useState(1);

  // Drag state
  const dragRef = useRef<{
    type: "node" | "pan" | "connect";
    nodeId?: string;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
    // For connect mode
    sourceId?: string;
    mouseX?: number;
    mouseY?: number;
  } | null>(null);
  const [connectLine, setConnectLine] = useState<{
    x1: number; y1: number; x2: number; y2: number;
  } | null>(null);

  // Convert screen coords to SVG coords
  const screenToSvg = useCallback((sx: number, sy: number) => {
    return { x: (sx - pan.x) / zoom, y: (sy - pan.y) / zoom };
  }, [pan, zoom]);

  // ── Mouse handlers ─────────────────────────────────────────────────

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    const rect = svgRef.current!.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    // Check if we're on a port (output port = right side of node)
    const target = e.target as SVGElement;
    const portNodeId = target.getAttribute("data-port-out");
    if (portNodeId) {
      const node = nodes.find(n => n.id === portNodeId);
      if (node) {
        dragRef.current = {
          type: "connect",
          sourceId: portNodeId,
          startX: sx, startY: sy,
          origX: node.x + NODE_W, origY: node.y + NODE_H / 2,
          mouseX: node.x + NODE_W, mouseY: node.y + NODE_H / 2,
        };
        return;
      }
    }

    // Check if we're on a node body
    const nodeId = target.getAttribute("data-node-id") ||
                   target.closest("[data-node-id]")?.getAttribute("data-node-id");
    if (nodeId) {
      const node = nodes.find(n => n.id === nodeId);
      if (node) {
        onSelectNode(nodeId);
        onSelectEdge(null);
        dragRef.current = {
          type: "node",
          nodeId,
          startX: sx, startY: sy,
          origX: node.x, origY: node.y,
        };
        return;
      }
    }

    // Otherwise, pan
    onSelectNode(null);
    onSelectEdge(null);
    dragRef.current = {
      type: "pan",
      startX: e.clientX, startY: e.clientY,
      origX: pan.x, origY: pan.y,
    };
  }, [nodes, pan, onSelectNode, onSelectEdge]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const rect = svgRef.current!.getBoundingClientRect();

    if (d.type === "node" && d.nodeId) {
      const dx = (e.clientX - rect.left - d.startX) / zoom;
      const dy = (e.clientY - rect.top - d.startY) / zoom;
      onMoveNode(d.nodeId, d.origX + dx, d.origY + dy);
    } else if (d.type === "pan") {
      setPan({
        x: d.origX + (e.clientX - d.startX),
        y: d.origY + (e.clientY - d.startY),
      });
    } else if (d.type === "connect" && d.sourceId) {
      const svgPos = screenToSvg(e.clientX - rect.left, e.clientY - rect.top);
      setConnectLine({
        x1: d.origX, y1: d.origY,
        x2: svgPos.x, y2: svgPos.y,
      });
    }
  }, [zoom, onMoveNode, screenToSvg]);

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    const d = dragRef.current;
    if (d?.type === "connect" && d.sourceId) {
      // Check if we dropped on a node's input port
      const target = e.target as SVGElement;
      const portNodeId = target.getAttribute("data-port-in") ||
                         target.getAttribute("data-node-id") ||
                         target.closest("[data-node-id]")?.getAttribute("data-node-id");
      if (portNodeId && portNodeId !== d.sourceId) {
        onConnectNodes(d.sourceId, portNodeId);
      }
      setConnectLine(null);
    }
    dragRef.current = null;
  }, [onConnectNodes]);

  // ── Zoom ───────────────────────────────────────────────────────────

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const rect = svgRef.current!.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.1 : 0.9;
    const newZoom = Math.max(0.2, Math.min(3, zoom * factor));
    // Zoom toward mouse
    setPan({
      x: mx - (mx - pan.x) * (newZoom / zoom),
      y: my - (my - pan.y) * (newZoom / zoom),
    });
    setZoom(newZoom);
  }, [zoom, pan]);

  // ── Double-click to add node ───────────────────────────────────────

  const handleDoubleClick = useCallback((e: React.MouseEvent) => {
    const rect = svgRef.current!.getBoundingClientRect();
    const pos = screenToSvg(e.clientX - rect.left, e.clientY - rect.top);
    onAddNode(pos.x - NODE_W / 2, pos.y - NODE_H / 2);
  }, [screenToSvg, onAddNode]);

  // ── Edge click ─────────────────────────────────────────────────────

  const handleEdgeClick = useCallback((idx: number, e: React.MouseEvent) => {
    e.stopPropagation();
    onSelectEdge(idx);
    onSelectNode(null);
  }, [onSelectEdge, onSelectNode]);

  // ── Render ─────────────────────────────────────────────────────────

  // Compute edge paths
  const edgePaths = useMemo(() => {
    return edges.map((edge) => {
      const src = nodes.find(n => n.id === edge.source);
      const tgt = nodes.find(n => n.id === edge.target);
      if (!src || !tgt) return null;
      const x1 = src.x + NODE_W;
      const y1 = src.y + NODE_H / 2;
      const x2 = tgt.x;
      const y2 = tgt.y + NODE_H / 2;
      const dx = Math.abs(x2 - x1) * 0.5;
      const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
      return { d, x1, y1, x2, y2, edge };
    });
  }, [edges, nodes]);

  return (
    <svg
      ref={svgRef}
      className="w-full h-full bg-void cursor-grab select-none"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onWheel={handleWheel}
      onDoubleClick={handleDoubleClick}
      style={{ cursor: dragRef.current?.type === "pan" ? "grabbing" : "grab" }}
    >
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="7"
          refX="10" refY="3.5" orient="auto" fill="#525252">
          <polygon points="0 0, 10 3.5, 0 7" />
        </marker>
        <marker id="arrowhead-selected" markerWidth="10" markerHeight="7"
          refX="10" refY="3.5" orient="auto" fill="#d4a843">
          <polygon points="0 0, 10 3.5, 0 7" />
        </marker>
        {/* Grid pattern */}
        <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
          <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#1a1a1a" strokeWidth="0.5" />
        </pattern>
      </defs>

      <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
        {/* Background grid */}
        <rect x="-5000" y="-5000" width="10000" height="10000" fill="url(#grid)" />

        {/* Phase columns (subtle labels) */}
        {[1, 2, 3, 4, 5].map(phase => (
          <text
            key={phase}
            x={(phase - 1) * 280 + 100 + NODE_W / 2}
            y={-10}
            textAnchor="middle"
            fill="#333"
            fontSize="11"
            fontFamily="monospace"
          >
            Phase {phase}
          </text>
        ))}

        {/* Edges */}
        {edgePaths.map((ep, i) => {
          if (!ep) return null;
          const selected = selectedEdgeIdx === i;
          return (
            <g key={i}>
              {/* Fat invisible hit area */}
              <path
                d={ep.d}
                fill="none"
                stroke="transparent"
                strokeWidth="14"
                style={{ cursor: "pointer" }}
                onClick={(e) => handleEdgeClick(i, e)}
              />
              <path
                d={ep.d}
                fill="none"
                stroke={selected ? "#d4a843" : "#525252"}
                strokeWidth={selected ? 2 : 1.5}
                strokeDasharray={ep.edge.strength < 0.5 ? "4,4" : undefined}
                markerEnd={selected ? "url(#arrowhead-selected)" : "url(#arrowhead)"}
                style={{ cursor: "pointer" }}
                onClick={(e) => handleEdgeClick(i, e)}
              />
              {/* Strength label on edge midpoint */}
              {selected && (
                <text
                  x={(ep.x1 + ep.x2) / 2}
                  y={(ep.y1 + ep.y2) / 2 - 8}
                  textAnchor="middle"
                  fill="#d4a843"
                  fontSize="10"
                  fontFamily="monospace"
                >
                  {ep.edge.mechanism || `strength: ${ep.edge.strength}`}
                </text>
              )}
            </g>
          );
        })}

        {/* Connect-in-progress line */}
        {connectLine && (
          <line
            x1={connectLine.x1} y1={connectLine.y1}
            x2={connectLine.x2} y2={connectLine.y2}
            stroke="#d4a843"
            strokeWidth="2"
            strokeDasharray="6,3"
            pointerEvents="none"
          />
        )}

        {/* Nodes */}
        {nodes.map(node => {
          const colors = TYPE_COLORS[node.type] || TYPE_COLORS.event;
          const isSelected = selectedNodeId === node.id;
          return (
            <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
              {/* Node body */}
              <rect
                data-node-id={node.id}
                width={NODE_W}
                height={NODE_H}
                rx="6"
                fill={colors.fill}
                stroke={isSelected ? "#d4a843" : colors.stroke}
                strokeWidth={isSelected ? 2.5 : 1.5}
                style={{ cursor: "move" }}
              />

              {/* State dot */}
              <circle
                data-node-id={node.id}
                cx="14" cy="14"
                r="4"
                fill={STATE_DOT[node.state] || STATE_DOT.monitoring}
              />

              {/* Type badge */}
              <text
                data-node-id={node.id}
                x={NODE_W - 8} y="14"
                textAnchor="end"
                fill={colors.text}
                fontSize="8"
                fontFamily="monospace"
                opacity="0.6"
              >
                {node.type}
              </text>

              {/* Label */}
              <text
                data-node-id={node.id}
                x={NODE_W / 2} y="28"
                textAnchor="middle"
                fill={colors.text}
                fontSize="12"
                fontWeight="600"
                fontFamily="Inter, system-ui, sans-serif"
              >
                {node.label.length > 20 ? node.label.slice(0, 18) + "…" : node.label}
              </text>

              {/* Phase badge */}
              <text
                data-node-id={node.id}
                x={NODE_W / 2} y="46"
                textAnchor="middle"
                fill={colors.text}
                fontSize="9"
                fontFamily="monospace"
                opacity="0.5"
              >
                P{node.phase}{node.feeds.length > 0 ? ` · ${node.feeds.length} feed${node.feeds.length > 1 ? "s" : ""}` : ""}
              </text>

              {/* Input port (left) */}
              <circle
                data-port-in={node.id}
                data-node-id={node.id}
                cx="0" cy={NODE_H / 2}
                r={PORT_R}
                fill="#1a1a1a"
                stroke={colors.stroke}
                strokeWidth="1.5"
                style={{ cursor: "crosshair" }}
              />

              {/* Output port (right) */}
              <circle
                data-port-out={node.id}
                cx={NODE_W} cy={NODE_H / 2}
                r={PORT_R}
                fill="#1a1a1a"
                stroke={colors.stroke}
                strokeWidth="1.5"
                style={{ cursor: "crosshair" }}
              />
            </g>
          );
        })}
      </g>

      {/* Zoom indicator */}
      <text x="10" y="20" fill="#525252" fontSize="10" fontFamily="monospace">
        {Math.round(zoom * 100)}% · dbl-click to add node
      </text>
    </svg>
  );
}
