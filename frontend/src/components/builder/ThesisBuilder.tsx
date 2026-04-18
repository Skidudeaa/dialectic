// ThesisBuilder — full-page visual thesis graph editor.
//
// Layout: MetaEditor (top bar) → GraphCanvas (center) + property panel (right).
// Bottom tabs: Scenarios | Instruments | Rules.
//
// The builder works entirely in-memory until Save is clicked, then persists
// to the backend which writes the JSON to books/.

import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Save, ArrowLeft, Download, Upload, Undo2, Redo2,
  Layers, Target, ShieldCheck, PanelRightClose, PanelRightOpen,
  Trash2, AlertTriangle,
} from "lucide-react";
import { apiFetch } from "../../lib/api";
import type {
  BuilderBook, BuilderNode, BuilderEdge, BuilderMeta,
  BuilderInstrument,
} from "../../lib/types";
import GraphCanvas from "./GraphCanvas";
import MetaEditor from "./MetaEditor";
import NodeEditor from "./NodeEditor";
import EdgeEditor from "./EdgeEditor";
import InstrumentEditor from "./InstrumentEditor";
import ScenarioEditor from "./ScenarioEditor";
import RulesEditor from "./RulesEditor";
import { validateBook, hasErrors, type ValidationIssue } from "./validation";

// ── Default empty book ───────────────────────────────────────────────

function emptyBook(): BuilderBook {
  return {
    meta: {
      title: "",
      claim: "",
      monthlyBudget: 5000,
      asOf: new Date().toISOString().slice(0, 10),
    },
    nodes: [],
    edges: [],
    instruments: {},
    scenarios: [],
    cascadePhases: {},
    rules: [],
  };
}

function newNode(x: number, y: number, existingIds: string[]): BuilderNode {
  let idx = existingIds.length + 1;
  let id = `node-${idx}`;
  while (existingIds.includes(id)) { idx++; id = `node-${idx}`; }
  return {
    id,
    label: `New Node ${idx}`,
    type: "event",
    phase: Math.max(1, Math.min(5, Math.round(x / 280) + 1)),
    state: "monitoring",
    context: "",
    x, y,
    probability: null,
    current: null,
    feeds: [],
    thresholds: [],
    indicators: [],
    countdown: false,
    deadline: null,
    irreversible: false,
    gatedBy: [],
    logic: null,
  };
}

// ── Undo/Redo ────────────────────────────────────────────────────────

interface HistoryEntry {
  nodes: BuilderNode[];
  edges: BuilderEdge[];
}

type BottomTab = "scenarios" | "instruments" | "rules" | null;

// ── Component ────────────────────────────────────────────────────────

export default function ThesisBuilder() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const editId = searchParams.get("edit");

  const [book, setBook] = useState<BuilderBook>(emptyBook());
  const [bookId, setBookId] = useState<string | null>(editId);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeIdx, setSelectedEdgeIdx] = useState<number | null>(null);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [bottomTab, setBottomTab] = useState<BottomTab>(null);

  // Confirm-before-delete state for the destructive top-toolbar button.
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Pre-save validation issues. Populated on save attempt; if any errors,
  // save is blocked and the issues panel is shown.
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([]);
  const [showIssues, setShowIssues] = useState(false);

  // Undo/redo
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyIdx, setHistoryIdx] = useState(-1);
  const skipHistoryRef = useRef(false);

  // Push to undo stack
  const pushHistory = useCallback((nodes: BuilderNode[], edges: BuilderEdge[]) => {
    if (skipHistoryRef.current) { skipHistoryRef.current = false; return; }
    setHistory(prev => {
      const trimmed = prev.slice(0, historyIdx + 1);
      const next = [...trimmed, { nodes: JSON.parse(JSON.stringify(nodes)), edges: JSON.parse(JSON.stringify(edges)) }];
      if (next.length > 50) next.shift();
      return next;
    });
    setHistoryIdx(prev => Math.min(prev + 1, 49));
  }, [historyIdx]);

  const undo = useCallback(() => {
    if (historyIdx <= 0) return;
    const entry = history[historyIdx - 1];
    skipHistoryRef.current = true;
    setBook(prev => ({ ...prev, nodes: entry.nodes, edges: entry.edges }));
    setHistoryIdx(prev => prev - 1);
  }, [history, historyIdx]);

  const redo = useCallback(() => {
    if (historyIdx >= history.length - 1) return;
    const entry = history[historyIdx + 1];
    skipHistoryRef.current = true;
    setBook(prev => ({ ...prev, nodes: entry.nodes, edges: entry.edges }));
    setHistoryIdx(prev => prev + 1);
  }, [history, historyIdx]);

  // ── Convert engine-format JSON → builder format (used by Import) ─────
  // Pulled out so both file-picker import and BuilderList sessionStorage
  // import share one normalisation path.
  const adoptRawBook = useCallback((raw: Record<string, unknown>) => {
    if (!raw || !raw.meta || !raw.nodes) {
      throw new Error("JSON is missing meta/nodes");
    }
    const isEngine = Array.isArray(raw.edges) &&
      (raw.edges as Record<string, unknown>[]).some(e => "from" in e);
    if (!isEngine) {
      setBook(raw as unknown as BuilderBook);
      return;
    }
    const nodes: BuilderNode[] = (raw.nodes as Record<string, unknown>[]).map((n, i) => ({
      id: n.id as string,
      label: (n.label as string) || (n.id as string),
      type: (n.type as BuilderNode["type"]) || "event",
      phase: (n.phase as number) || 1,
      state: (n.state as BuilderNode["state"]) || "monitoring",
      context: (n.context as string) || "",
      x: (n._builderX as number) ?? ((((n.phase as number) || 1) - 1) * 280 + 100),
      y: (n._builderY as number) ?? (i * 120 + 60),
      probability: (n.probability as number | null) ?? null,
      current: (n.current as number | null) ?? null,
      feeds: (n.feeds as BuilderNode["feeds"]) || [],
      thresholds: (n.thresholds as BuilderNode["thresholds"]) || [],
      indicators: (n.indicators as BuilderNode["indicators"]) || [],
      countdown: !!n.countdown,
      deadline: (n.deadline as string | null) ?? null,
      irreversible: !!n.irreversible,
      gatedBy: (n.gatedBy as string[]) || [],
      logic: (n.logic as string | null) ?? null,
    }));
    const edges: BuilderEdge[] = ((raw.edges as Record<string, unknown>[]) || []).map(e => ({
      source: e.from as string,
      target: e.to as string,
      mechanism: (e.mechanism as string) || "",
      lag: (e.lag as string) || "",
      strength: (e.strength as number) ?? 0.7,
    }));
    const meta = raw.meta as Record<string, unknown>;
    setBook({
      meta: {
        title: (meta.title as string) || "",
        claim: (meta.claim as string) || "",
        monthlyBudget: (meta.monthlyBudget as number) || 5000,
        asOf: (meta.asOf as string) || new Date().toISOString().slice(0, 10),
      },
      nodes,
      edges,
      instruments: (raw.instruments as BuilderBook["instruments"]) || {},
      scenarios: (raw.scenarios as BuilderBook["scenarios"]) || [],
      cascadePhases: (raw.cascadePhases as BuilderBook["cascadePhases"]) || {},
      rules: (raw.rules as string[]) || [],
    });
  }, []);

  // ── Load existing book ─────────────────────────────────────────────

  useEffect(() => {
    if (!editId) return;
    apiFetch<BuilderBook>(`/api/thesis/builder/books/${editId}`)
      .then(data => {
        setBook(data);
        setBookId(data.id ?? null);
        pushHistory(data.nodes, data.edges);
        setStatus(`Loaded: ${data.meta.title}`);
      })
      .catch(err => setStatus(`Error loading: ${err.message}`));
  }, [editId]);

  // ── Import-from-session (set by BuilderList when user picks a file) ──
  useEffect(() => {
    if (searchParams.get("import") !== "session") return;
    const stashed = sessionStorage.getItem("builder:import");
    if (!stashed) return;
    sessionStorage.removeItem("builder:import");
    try {
      adoptRawBook(JSON.parse(stashed));
      setDirty(true);
      setStatus("Imported — review and Save");
      // Strip the ?import= flag so a refresh doesn't re-trigger
      window.history.replaceState(null, "", "/builder");
    } catch (err) {
      setStatus(`Import error: ${(err as Error).message}`);
    }
  }, [searchParams, adoptRawBook]);

  // ── Beforeunload guard for unsaved changes ─────────────────────────
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Modern browsers ignore the message but require returnValue to be set.
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // ── Keyboard shortcuts ─────────────────────────────────────────────

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
      if (mod && e.key === "z" && e.shiftKey) { e.preventDefault(); redo(); }
      if (mod && e.key === "s") { e.preventDefault(); handleSave(); }
      if (e.key === "Delete" || e.key === "Backspace") {
        if (document.activeElement?.tagName === "INPUT" || document.activeElement?.tagName === "TEXTAREA" || document.activeElement?.tagName === "SELECT") return;
        if (selectedNodeId) deleteNode(selectedNodeId);
        else if (selectedEdgeIdx !== null) deleteEdge(selectedEdgeIdx);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  // ── Node operations ────────────────────────────────────────────────

  const updateNodes = useCallback((nodes: BuilderNode[]) => {
    setBook(prev => ({ ...prev, nodes }));
    setDirty(true);
    pushHistory(nodes, book.edges);
  }, [book.edges, pushHistory]);

  const updateEdges = useCallback((edges: BuilderEdge[]) => {
    setBook(prev => ({ ...prev, edges }));
    setDirty(true);
    pushHistory(book.nodes, edges);
  }, [book.nodes, pushHistory]);

  const addNode = useCallback((x: number, y: number) => {
    const node = newNode(x, y, book.nodes.map(n => n.id));
    const nodes = [...book.nodes, node];
    updateNodes(nodes);
    setSelectedNodeId(node.id);
    setSelectedEdgeIdx(null);
  }, [book.nodes, updateNodes]);

  const moveNode = useCallback((id: string, x: number, y: number) => {
    // Don't push history for every pixel — just update in place
    setBook(prev => ({
      ...prev,
      nodes: prev.nodes.map(n => n.id === id ? { ...n, x, y } : n),
    }));
    setDirty(true);
  }, []);

  const updateNode = useCallback((updated: BuilderNode) => {
    const oldNode = book.nodes.find(n => n.id === selectedNodeId);
    const nodes = book.nodes.map(n => n.id === selectedNodeId ? updated : n);

    // If ID changed, update all edges and instruments referencing old ID
    if (oldNode && oldNode.id !== updated.id) {
      const edges = book.edges.map(e => ({
        ...e,
        source: e.source === oldNode.id ? updated.id : e.source,
        target: e.target === oldNode.id ? updated.id : e.target,
      }));
      const instruments = { ...book.instruments };
      if (instruments[oldNode.id]) {
        instruments[updated.id] = instruments[oldNode.id];
        delete instruments[oldNode.id];
      }
      setBook(prev => ({ ...prev, nodes, edges, instruments }));
      setSelectedNodeId(updated.id);
      setDirty(true);
      pushHistory(nodes, edges);
      return;
    }

    updateNodes(nodes);
  }, [book.nodes, book.edges, book.instruments, selectedNodeId, updateNodes, pushHistory]);

  const deleteNode = useCallback((id: string) => {
    const nodes = book.nodes.filter(n => n.id !== id);
    const edges = book.edges.filter(e => e.source !== id && e.target !== id);
    const instruments = { ...book.instruments };
    delete instruments[id];
    setBook(prev => ({ ...prev, nodes, edges, instruments }));
    setSelectedNodeId(null);
    setDirty(true);
    pushHistory(nodes, edges);
  }, [book.nodes, book.edges, book.instruments, pushHistory]);

  const connectNodes = useCallback((source: string, target: string) => {
    // Don't create duplicate edges
    if (book.edges.some(e => e.source === source && e.target === target)) return;
    const edge: BuilderEdge = { source, target, mechanism: "", lag: "", strength: 0.7 };
    const edges = [...book.edges, edge];
    updateEdges(edges);
    setSelectedEdgeIdx(edges.length - 1);
    setSelectedNodeId(null);
  }, [book.edges, updateEdges]);

  const deleteEdge = useCallback((idx: number) => {
    const edges = book.edges.filter((_, i) => i !== idx);
    updateEdges(edges);
    setSelectedEdgeIdx(null);
  }, [book.edges, updateEdges]);

  // ── Save ───────────────────────────────────────────────────────────

  const handleSave = useCallback(async () => {
    // Pre-save structural validation. Errors block save; warnings don't.
    const issues = validateBook(book);
    setValidationIssues(issues);
    if (hasErrors(issues)) {
      setShowIssues(true);
      setStatus(`Save blocked: ${issues.filter(i => i.severity === "error").length} error(s)`);
      return;
    }
    setShowIssues(false);
    setSaving(true);
    setStatus(null);
    try {
      const url = bookId
        ? `/api/thesis/builder/books/${bookId}`
        : "/api/thesis/builder/books";
      const method = bookId ? "PUT" : "POST";
      const res = await apiFetch<{ id: string; filename: string }>(url, { method, body: JSON.stringify(book) });
      setBookId(res.id);
      setDirty(false);
      setStatus(`Saved as ${res.id}`);
      // Update URL if this was a new book
      if (!bookId) {
        window.history.replaceState(null, "", `/builder?edit=${res.id}`);
      }
    } catch (err: unknown) {
      setStatus(`Save failed: ${(err as Error).message}`);
    } finally {
      setSaving(false);
    }
  }, [book, bookId]);

  // ── Import/Export JSON ─────────────────────────────────────────────

  const handleExportJSON = useCallback(() => {
    const blob = new Blob([JSON.stringify(book, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${bookId || "thesis"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [book, bookId]);

  const handleImportJSON = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        adoptRawBook(JSON.parse(await file.text()));
        setDirty(true);
        setStatus("Imported from file");
      } catch (err) {
        setStatus(`Import error: ${(err as Error).message}`);
      }
    };
    input.click();
  }, [adoptRawBook]);

  // ── Delete (editor-side) ───────────────────────────────────────────
  const handleDelete = useCallback(async () => {
    if (!bookId) return;
    try {
      await apiFetch(`/api/thesis/builder/books/${bookId}`, { method: "DELETE" });
      setDirty(false);
      navigate("/builder");
    } catch (err) {
      setStatus(`Delete failed: ${(err as Error).message}`);
      setConfirmDelete(false);
    }
  }, [bookId, navigate]);

  // ── Derived state ──────────────────────────────────────────────────

  const selectedNode = selectedNodeId ? book.nodes.find(n => n.id === selectedNodeId) : null;
  const selectedEdge = selectedEdgeIdx !== null ? book.edges[selectedEdgeIdx] : null;

  // ── Render ─────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen bg-void">
      {/* ── Top toolbar ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-surface border-b border-border shrink-0">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-1 text-[12px] font-mono text-text-muted hover:text-text-primary"
        >
          <ArrowLeft size={14} /> Back
        </button>

        <div className="w-px h-4 bg-border mx-1" />

        <span className="text-[13px] font-mono text-amber font-semibold">Thesis Builder</span>

        {bookId && (
          <span className="text-[10px] font-mono text-text-dim">({bookId})</span>
        )}

        <div className="flex-1" />

        {/* Undo/Redo */}
        <button onClick={undo} disabled={historyIdx <= 0}
          className="p-1 text-text-dim hover:text-text-primary disabled:opacity-30" title="Undo (Cmd+Z)">
          <Undo2 size={14} />
        </button>
        <button onClick={redo} disabled={historyIdx >= history.length - 1}
          className="p-1 text-text-dim hover:text-text-primary disabled:opacity-30" title="Redo (Cmd+Shift+Z)">
          <Redo2 size={14} />
        </button>

        <div className="w-px h-4 bg-border mx-1" />

        {/* Panel toggle */}
        <button onClick={() => setRightPanelOpen(!rightPanelOpen)}
          className="p-1 text-text-dim hover:text-text-primary" title="Toggle property panel">
          {rightPanelOpen ? <PanelRightClose size={14} /> : <PanelRightOpen size={14} />}
        </button>

        <div className="w-px h-4 bg-border mx-1" />

        {/* Import/Export */}
        <button onClick={handleImportJSON}
          className="flex items-center gap-1 px-2 py-1 text-[11px] font-mono text-text-muted hover:text-text-primary bg-elevated rounded"
          title="Import JSON">
          <Upload size={12} /> Import
        </button>
        <button onClick={handleExportJSON}
          className="flex items-center gap-1 px-2 py-1 text-[11px] font-mono text-text-muted hover:text-text-primary bg-elevated rounded"
          title="Export JSON">
          <Download size={12} /> Export
        </button>

        <div className="w-px h-4 bg-border mx-1" />

        {/* Delete (only for saved books) */}
        {bookId && (
          confirmDelete ? (
            <>
              <span className="text-[10px] font-mono text-danger">Delete {bookId}?</span>
              <button
                onClick={handleDelete}
                className="px-2 py-0.5 text-[10px] font-mono text-danger bg-danger/20 border border-danger/30 hover:bg-danger/30 rounded"
              >
                Confirm
              </button>
              <button
                onClick={() => setConfirmDelete(false)}
                className="px-2 py-0.5 text-[10px] font-mono text-text-dim hover:text-text-primary rounded"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="p-1 text-text-muted hover:text-danger hover:bg-danger/10 rounded"
              title="Delete this book"
            >
              <Trash2 size={14} />
            </button>
          )
        )}

        <div className="w-px h-4 bg-border mx-1" />

        {/* Save */}
        <button
          onClick={handleSave}
          disabled={saving}
          className={`flex items-center gap-1 px-3 py-1 text-[12px] font-mono rounded font-semibold ${
            dirty
              ? "bg-amber text-void hover:bg-amber-dim"
              : "bg-elevated text-text-muted"
          }`}
          title={dirty ? "Unsaved changes (Cmd/Ctrl+S)" : "All changes saved"}
        >
          {dirty && <span className="text-void leading-none" aria-hidden>●</span>}
          <Save size={13} />
          {saving ? "Saving..." : dirty ? "Save" : "Saved"}
        </button>

        {/* Status */}
        {status && (
          <span className="text-[10px] font-mono text-text-dim ml-2">{status}</span>
        )}
      </div>

      {/* Validation issues panel — shown when save is blocked or warnings exist */}
      {showIssues && validationIssues.length > 0 && (
        <div className="shrink-0 border-b border-danger/30 bg-danger/5 px-3 py-2">
          <div className="flex items-center justify-between mb-1">
            <div className="flex items-center gap-1.5 text-[11px] font-mono text-danger">
              <AlertTriangle size={12} />
              {validationIssues.filter(i => i.severity === "error").length} error(s),{" "}
              {validationIssues.filter(i => i.severity === "warning").length} warning(s)
            </div>
            <button
              onClick={() => setShowIssues(false)}
              className="text-[10px] font-mono text-text-dim hover:text-text-primary"
            >
              Dismiss
            </button>
          </div>
          <ul className="space-y-0.5 max-h-[120px] overflow-y-auto">
            {validationIssues.map((iss, i) => (
              <li
                key={i}
                className={`text-[11px] font-mono ${
                  iss.severity === "error" ? "text-danger" : "text-warning"
                }`}
              >
                <span className="opacity-60">[{iss.scope}{iss.ref ? ` ${iss.ref}` : ""}]</span>{" "}
                {iss.message}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Meta bar ──────────────────────────────────────────────── */}
      <MetaEditor
        meta={book.meta}
        onChange={(meta: BuilderMeta) => { setBook(prev => ({ ...prev, meta })); setDirty(true); }}
      />

      {/* ── Main content ──────────────────────────────────────────── */}
      <div className="flex flex-1 min-h-0">
        {/* Graph canvas */}
        <div className="flex-1 relative">
          <GraphCanvas
            nodes={book.nodes}
            edges={book.edges}
            selectedNodeId={selectedNodeId}
            selectedEdgeIdx={selectedEdgeIdx}
            onSelectNode={setSelectedNodeId}
            onSelectEdge={setSelectedEdgeIdx}
            onMoveNode={moveNode}
            onConnectNodes={connectNodes}
            onAddNode={addNode}
          />

          {/* Node count badge */}
          <div className="absolute bottom-2 left-2 flex items-center gap-3 px-2 py-1 bg-surface/80 backdrop-blur rounded border border-border">
            <span className="text-[10px] font-mono text-text-dim">
              {book.nodes.length} nodes · {book.edges.length} edges
            </span>
          </div>
        </div>

        {/* Right property panel */}
        {rightPanelOpen && (
          <div className="w-[300px] shrink-0 border-l border-border bg-surface overflow-hidden flex flex-col">
            {selectedNode ? (
              <>
                <NodeEditor
                  node={selectedNode}
                  allNodeIds={book.nodes.map(n => n.id)}
                  onChange={updateNode}
                  onDelete={() => deleteNode(selectedNode.id)}
                />
                {/* Instruments for selected node */}
                <div className="border-t border-border px-3 py-2 max-h-[200px] overflow-y-auto">
                  <InstrumentEditor
                    nodeId={selectedNode.id}
                    nodeLabel={selectedNode.label}
                    instruments={book.instruments[selectedNode.id] || []}
                    onChange={(instruments: BuilderInstrument[]) => {
                      setBook(prev => ({
                        ...prev,
                        instruments: { ...prev.instruments, [selectedNode.id]: instruments },
                      }));
                      setDirty(true);
                    }}
                  />
                </div>
              </>
            ) : selectedEdge ? (
              <EdgeEditor
                edge={selectedEdge}
                sourceLabel={book.nodes.find(n => n.id === selectedEdge.source)?.label || selectedEdge.source}
                targetLabel={book.nodes.find(n => n.id === selectedEdge.target)?.label || selectedEdge.target}
                onChange={(updated: BuilderEdge) => {
                  const edges = [...book.edges];
                  edges[selectedEdgeIdx!] = updated;
                  updateEdges(edges);
                }}
                onDelete={() => deleteEdge(selectedEdgeIdx!)}
              />
            ) : (
              <div className="flex-1 flex items-center justify-center p-4">
                <div className="text-center space-y-2">
                  <div className="text-text-dim text-[12px] font-mono">
                    No selection
                  </div>
                  <div className="text-text-dim text-[11px] font-mono space-y-1">
                    <p>• Double-click canvas to add a node</p>
                    <p>• Click a node to edit properties</p>
                    <p>• Drag from a port (○) to connect nodes</p>
                    <p>• Click an edge to edit it</p>
                    <p>• Delete/Backspace to remove selected</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

      </div>

      {/* ── Bottom tabs ───────────────────────────────────────────── */}
      <div className="shrink-0 border-t border-border bg-surface">
        {/* Tab buttons */}
        <div className="flex items-center gap-0 px-2 border-b border-border">
          {(
            [
              { id: "scenarios" as const, icon: Target, label: "Scenarios", count: book.scenarios.length },
              { id: "instruments" as const, icon: Layers, label: "All Instruments", count: Object.values(book.instruments).flat().length },
              { id: "rules" as const, icon: ShieldCheck, label: "Rules", count: book.rules.length },
            ] as const
          ).map(tab => (
            <button
              key={tab.id}
              onClick={() => setBottomTab(bottomTab === tab.id ? null : tab.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-mono border-b-2 ${
                bottomTab === tab.id
                  ? "border-amber text-amber"
                  : "border-transparent text-text-dim hover:text-text-primary"
              }`}
            >
              <tab.icon size={12} />
              {tab.label}
              {tab.count > 0 && (
                <span className="text-[9px] bg-elevated px-1 rounded">{tab.count}</span>
              )}
            </button>
          ))}

          {/* Summary stats */}
          <div className="flex-1" />
          <div className="flex items-center gap-3 text-[10px] font-mono text-text-dim pr-2">
            <span>{book.nodes.filter(n => n.state === "fired").length} fired</span>
            <span>{book.nodes.filter(n => n.state === "approaching").length} approaching</span>
            <span>${book.meta.monthlyBudget.toLocaleString()}/mo</span>
          </div>
        </div>

        {/* Tab content */}
        {bottomTab && (
          <div className="max-h-[250px] overflow-y-auto px-3 py-2">
            {bottomTab === "scenarios" && (
              <ScenarioEditor
                scenarios={book.scenarios}
                nodeIds={book.nodes.map(n => n.id)}
                onChange={(scenarios) => { setBook(prev => ({ ...prev, scenarios })); setDirty(true); }}
              />
            )}
            {bottomTab === "instruments" && (
              <div className="space-y-3">
                {book.nodes.map(node => {
                  const insts = book.instruments[node.id];
                  if (!insts || insts.length === 0) return null;
                  return (
                    <div key={node.id} className="space-y-1">
                      <div className="text-[11px] font-mono text-amber">{node.label} ({node.id})</div>
                      <div className="grid grid-cols-[80px_1fr_60px_60px_60px_60px] gap-1 text-[10px] font-mono text-text-dim">
                        <span>Ticker</span><span>Role</span><span>$/mo</span><span>Ref</span><span>Target</span><span>Stop</span>
                      </div>
                      {insts.map((inst, i) => (
                        <div key={i} className="grid grid-cols-[80px_1fr_60px_60px_60px_60px] gap-1 text-[11px] font-mono text-text-primary">
                          <span className="text-amber">{inst.id}</span>
                          <span className="text-text-muted truncate">{inst.role}</span>
                          <span>${inst.monthly}</span>
                          <span>{inst.ref}</span>
                          <span>{inst.targetLow ?? "—"}</span>
                          <span>{inst.stop ?? "—"}</span>
                        </div>
                      ))}
                    </div>
                  );
                })}
                {Object.values(book.instruments).flat().length === 0 && (
                  <div className="text-[11px] font-mono text-text-dim py-2">
                    Select a node and add instruments in the right panel.
                  </div>
                )}
              </div>
            )}
            {bottomTab === "rules" && (
              <RulesEditor
                rules={book.rules}
                onChange={(rules) => { setBook(prev => ({ ...prev, rules })); setDirty(true); }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}
