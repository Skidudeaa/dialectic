// BuilderList — landing page for /builder.
//
// Lists every editable book in books/ with Open / Duplicate / Delete actions
// and a "New blank book" entry point. Without this, builder users have to
// either type a URL with ?edit=<id> or always create new books.

import { useEffect, useState, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft, Plus, FileJson, Trash2, Copy, BookOpen, Upload, AlertTriangle,
} from "lucide-react";
import { apiFetch } from "../../lib/api";
import type { BuilderBook } from "../../lib/types";

interface BookRow {
  id: string;
  filename: string;
  title: string;
  claim: string;
  asOf: string;
  monthlyBudget: number;
  nodes: number;
  edges: number;
  type: string;
}

export default function BuilderList() {
  const navigate = useNavigate();
  const [books, setBooks] = useState<BookRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const reload = useCallback(() => {
    setError(null);
    apiFetch<BookRow[]>("/api/thesis/builder/books")
      .then(setBooks)
      .catch(err => setError((err as Error).message));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  // ── Actions ─────────────────────────────────────────────────────────

  const handleDelete = useCallback(async (id: string) => {
    setBusy(id);
    try {
      await apiFetch(`/api/thesis/builder/books/${id}`, { method: "DELETE" });
      setPendingDelete(null);
      reload();
    } catch (err) {
      setError(`Delete failed: ${(err as Error).message}`);
    } finally {
      setBusy(null);
    }
  }, [reload]);

  const handleDuplicate = useCallback(async (id: string) => {
    setBusy(id);
    try {
      // Fetch the existing book in builder format, mutate title, POST as new
      const existing = await apiFetch<BuilderBook>(`/api/thesis/builder/books/${id}`);
      existing.meta.title = `${existing.meta.title} (copy)`;
      // strip id so backend assigns a fresh one
      delete (existing as { id?: string }).id;
      const res = await apiFetch<{ id: string }>("/api/thesis/builder/books", {
        method: "POST",
        body: JSON.stringify(existing),
      });
      navigate(`/builder?edit=${res.id}`);
    } catch (err) {
      setError(`Duplicate failed: ${(err as Error).message}`);
      setBusy(null);
    }
  }, [navigate]);

  const handleImport = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      try {
        const text = await file.text();
        // Validate it parses; the editor handles conversion (engine ↔ builder).
        JSON.parse(text);
        sessionStorage.setItem("builder:import", text);
        navigate("/builder?import=session");
      } catch (err) {
        setError(`Import error: ${(err as Error).message}`);
      }
    };
    input.click();
  }, [navigate]);

  // ── Render ──────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col h-screen bg-void">
      {/* Top toolbar */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-surface border-b border-border shrink-0">
        <button
          onClick={() => navigate("/")}
          className="flex items-center gap-1 text-[12px] font-mono text-text-muted hover:text-text-primary"
        >
          <ArrowLeft size={14} /> Back
        </button>
        <div className="w-px h-4 bg-border mx-1" />
        <BookOpen size={14} className="text-amber" />
        <span className="text-[13px] font-mono text-amber font-semibold">Thesis Builder</span>
        <span className="text-[10px] font-mono text-text-dim">— library</span>

        <div className="flex-1" />

        <button
          onClick={handleImport}
          className="flex items-center gap-1 px-2 py-1 text-[11px] font-mono text-text-muted hover:text-text-primary bg-elevated rounded"
          title="Import a JSON book file"
        >
          <Upload size={12} /> Import JSON
        </button>
        <Link
          to="/builder?edit="
          className="flex items-center gap-1 px-3 py-1 text-[12px] font-mono rounded font-semibold bg-amber text-void hover:bg-amber-dim"
        >
          <Plus size={13} /> New blank book
        </Link>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="max-w-4xl mx-auto">
          {error && (
            <div className="mb-3 px-3 py-2 bg-danger/10 border border-danger/30 rounded text-[12px] font-mono text-danger flex items-center gap-2">
              <AlertTriangle size={13} /> {error}
            </div>
          )}

          {books === null && (
            <div className="text-[12px] font-mono text-text-dim py-8 text-center">Loading…</div>
          )}

          {books !== null && books.length === 0 && (
            <div className="border border-dashed border-border rounded p-8 text-center">
              <FileJson size={32} className="mx-auto mb-3 text-text-dim" />
              <div className="text-[13px] font-mono text-text-muted mb-1">
                No books yet
              </div>
              <div className="text-[11px] font-mono text-text-dim mb-4">
                Create one from scratch or import an existing JSON file.
              </div>
              <div className="flex items-center justify-center gap-2">
                <Link
                  to="/builder?edit="
                  className="flex items-center gap-1 px-3 py-1 text-[12px] font-mono rounded font-semibold bg-amber text-void hover:bg-amber-dim"
                >
                  <Plus size={13} /> New blank book
                </Link>
                <button
                  onClick={handleImport}
                  className="flex items-center gap-1 px-3 py-1 text-[12px] font-mono text-text-muted hover:text-text-primary bg-elevated rounded border border-border"
                >
                  <Upload size={13} /> Import JSON
                </button>
              </div>
            </div>
          )}

          {books !== null && books.length > 0 && (
            <div className="border border-border rounded overflow-hidden bg-surface">
              <div className="grid grid-cols-[1fr_80px_80px_120px_180px] gap-3 px-3 py-2 border-b border-border bg-elevated text-[10px] font-mono uppercase tracking-wide text-text-dim">
                <div>Title / ID</div>
                <div className="text-right">Nodes</div>
                <div className="text-right">Edges</div>
                <div>As of</div>
                <div className="text-right">Actions</div>
              </div>
              {books.map(b => (
                <div
                  key={b.id}
                  className="grid grid-cols-[1fr_80px_80px_120px_180px] gap-3 px-3 py-2 border-b border-border last:border-b-0 items-center hover:bg-elevated/40"
                >
                  <div className="min-w-0">
                    <Link
                      to={`/builder?edit=${b.id}`}
                      className="text-[13px] font-mono text-text-primary hover:text-amber truncate block"
                    >
                      {b.title || b.id}
                    </Link>
                    <div className="text-[10px] font-mono text-text-dim truncate">
                      {b.id} · {b.filename}
                      {b.type !== "thesis-graph" && b.type !== "unknown" && (
                        <span className="ml-1 text-warning">[{b.type}]</span>
                      )}
                    </div>
                  </div>
                  <div className="text-right text-[12px] font-mono text-text-muted">{b.nodes}</div>
                  <div className="text-right text-[12px] font-mono text-text-muted">{b.edges}</div>
                  <div className="text-[11px] font-mono text-text-dim">{b.asOf || "—"}</div>
                  <div className="flex items-center justify-end gap-1">
                    <Link
                      to={`/builder?edit=${b.id}`}
                      className="px-2 py-1 text-[11px] font-mono text-amber hover:bg-amber/10 rounded"
                    >
                      Open
                    </Link>
                    <button
                      onClick={() => handleDuplicate(b.id)}
                      disabled={busy === b.id}
                      className="p-1 text-text-muted hover:text-text-primary hover:bg-elevated rounded disabled:opacity-30"
                      title="Duplicate"
                    >
                      <Copy size={12} />
                    </button>
                    {pendingDelete === b.id ? (
                      <>
                        <button
                          onClick={() => handleDelete(b.id)}
                          disabled={busy === b.id}
                          className="px-2 py-0.5 text-[10px] font-mono text-danger bg-danger/20 border border-danger/30 hover:bg-danger/30 rounded"
                        >
                          {busy === b.id ? "…" : "Confirm"}
                        </button>
                        <button
                          onClick={() => setPendingDelete(null)}
                          className="px-2 py-0.5 text-[10px] font-mono text-text-dim hover:text-text-primary rounded"
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => setPendingDelete(b.id)}
                        className="p-1 text-text-muted hover:text-danger hover:bg-danger/10 rounded"
                        title="Delete"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
