// CommandPalette — runtime surface over /api/v1/commands.
//
// WHY separate from the inline Ctrl+K palette in Dashboard.tsx: that palette
// is a panel-jumper (rooms / panels / actions). THIS palette introspects the
// backend registry so the LLM and the operator see the same list of
// executable commands. Triggered via Ctrl+Shift+K (or Cmd+Shift+K) so the
// two palettes coexist without keybinding conflicts.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Command as CommandIcon, Zap } from "lucide-react";
import { apiFetch } from "../lib/api";
import { useToast } from "./toast";

interface CommandSpec {
  id: string;
  title: string;
  description: string;
  category: string;
  input_schema: {
    type?: string;
    properties?: Record<string, {
      type?: string;
      description?: string;
      enum?: unknown[];
    }>;
    required?: string[];
  };
  output_schema: unknown;
  tags?: string[];
}

interface CommandsCatalog {
  commands: CommandSpec[];
}

interface Props {
  /** Optional default book id for commands that accept `book_id`. */
  defaultBookId?: string | null;
}

export default function CommandPalette({ defaultBookId }: Props) {
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<CommandSpec[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [args, setArgs] = useState<Record<string, string>>({});
  const [running, setRunning] = useState(false);
  const { toast } = useToast();

  // Keybinding: Ctrl+Shift+K / Cmd+Shift+K toggles this palette. Stays out
  // of the existing Ctrl+K handler in Dashboard.tsx.
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
        setQuery("");
        setSelectedId(null);
        setArgs({});
        return;
      }
      if (e.key === "Escape" && open) {
        setOpen(false);
        setSelectedId(null);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open]);

  // Lazy fetch — only when the palette is first opened.
  useEffect(() => {
    if (!open || catalog.length > 0) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch<CommandsCatalog>("/api/v1/commands");
        if (!cancelled) setCatalog(data.commands);
      } catch (err) {
        if (!cancelled) setLoadError((err as Error).message || "Failed to load commands");
      }
    })();
    return () => { cancelled = true; };
  }, [open, catalog.length]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return catalog;
    return catalog.filter((c) =>
      c.id.toLowerCase().includes(q) ||
      c.title.toLowerCase().includes(q) ||
      c.category.toLowerCase().includes(q),
    );
  }, [query, catalog]);

  const selected = useMemo(
    () => catalog.find((c) => c.id === selectedId) || null,
    [catalog, selectedId],
  );

  const requiredFields = useMemo<string[]>(() => {
    return selected?.input_schema?.required ?? [];
  }, [selected]);

  // Seed arg defaults when a command is selected (e.g. prefill book_id).
  useEffect(() => {
    if (!selected) {
      setArgs({});
      return;
    }
    const defaults: Record<string, string> = {};
    const props = selected.input_schema?.properties || {};
    for (const key of Object.keys(props)) {
      if (key === "book_id" && defaultBookId) {
        defaults[key] = defaultBookId;
      }
    }
    setArgs(defaults);
  }, [selected, defaultBookId]);

  const dispatch = useCallback(async () => {
    if (!selected) return;
    setRunning(true);
    try {
      const body: Record<string, unknown> = {};
      const props = selected.input_schema?.properties || {};
      for (const [key, value] of Object.entries(args)) {
        if (value === "" && !(selected.input_schema.required || []).includes(key)) continue;
        const spec = props[key];
        if (spec?.type === "integer" || spec?.type === "number") {
          const n = Number(value);
          body[key] = Number.isNaN(n) ? value : n;
        } else {
          body[key] = value;
        }
      }
      const result = await apiFetch<{ ok: boolean; result: unknown }>(
        `/api/v1/commands/${selected.id}`,
        { method: "POST", body: JSON.stringify(body) },
      );
      toast(`Ran ${selected.title}`, "success");
      // Expose result on window for quick dev inspection.
      (window as unknown as { __lastCommandResult?: unknown }).__lastCommandResult = result.result;
      setOpen(false);
      setSelectedId(null);
    } catch (err) {
      const raw = (err as Error).message || "Command failed";
      // apiFetch bubbles the raw body — try to extract a validation message.
      let msg = raw;
      try {
        const idx = raw.indexOf("{");
        if (idx >= 0) {
          const parsed = JSON.parse(raw.slice(idx));
          if (parsed?.detail?.validation_errors) {
            msg = parsed.detail.validation_errors
              .map((v: { field: string; message: string }) => `${v.field}: ${v.message}`)
              .join("; ");
          } else if (typeof parsed?.detail === "string") {
            msg = parsed.detail;
          }
        }
      } catch {
        /* ignore parse failure, fall back to raw */
      }
      toast(msg, "error");
    } finally {
      setRunning(false);
    }
  }, [selected, args, toast]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-24"
      role="dialog"
      aria-modal="true"
      aria-label="Backend command palette"
      onClick={() => setOpen(false)}
    >
      <div className="absolute inset-0 bg-void/60" />
      <div
        className="relative bg-surface border border-border rounded w-full max-w-md shadow-2xl animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <CommandIcon size={12} className="text-amber" aria-hidden="true" />
          <span className="text-[10px] font-mono text-text-dim uppercase tracking-widest">
            Commands
          </span>
          <span className="ml-auto text-[9px] font-mono text-text-dim">
            {catalog.length} registered
          </span>
        </div>

        {!selected ? (
          <>
            <input
              className="w-full bg-transparent border-b border-border px-3 py-2 text-xs font-mono text-text-primary focus:outline-none placeholder-text-dim"
              placeholder="Search backend commands..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && filtered.length > 0) {
                  setSelectedId(filtered[0].id);
                }
              }}
              autoFocus
              aria-label="Command search"
            />
            <div className="max-h-64 overflow-y-auto py-1" role="listbox">
              {loadError && (
                <p className="text-[10px] text-danger px-3 py-2 font-mono">
                  {loadError}
                </p>
              )}
              {filtered.map((cmd) => (
                <button
                  key={cmd.id}
                  onClick={() => setSelectedId(cmd.id)}
                  role="option"
                  aria-selected={false}
                  className="w-full text-left px-3 py-1.5 text-xs flex items-center justify-between hover:bg-elevated/60"
                >
                  <span className="font-mono flex flex-col items-start">
                    <span className="text-text-primary">{cmd.title}</span>
                    <span className="text-[9px] text-text-dim">{cmd.id}</span>
                  </span>
                  <span className="text-[9px] text-text-dim uppercase">{cmd.category}</span>
                </button>
              ))}
              {filtered.length === 0 && !loadError && (
                <p className="text-[10px] text-text-dim px-3 py-2 font-mono">
                  {catalog.length === 0 ? "Loading..." : "No matches"}
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="p-3">
            <div className="mb-2">
              <p className="text-xs font-mono text-text-primary">{selected.title}</p>
              <p className="text-[10px] text-text-dim font-mono">{selected.description}</p>
            </div>
            {Object.entries(selected.input_schema?.properties || {}).map(([key, spec]) => {
              const required = requiredFields.includes(key);
              const isEnum = Array.isArray(spec.enum);
              return (
                <label key={key} className="block mb-2">
                  <span className="text-[10px] font-mono text-text-dim uppercase">
                    {key}{required ? " *" : ""}
                  </span>
                  {isEnum ? (
                    <select
                      className="input w-full mt-0.5"
                      value={args[key] ?? ""}
                      onChange={(e) => setArgs({ ...args, [key]: e.target.value })}
                    >
                      <option value="">— select —</option>
                      {(spec.enum as string[]).map((opt) => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className="input w-full mt-0.5"
                      type="text"
                      value={args[key] ?? ""}
                      onChange={(e) => setArgs({ ...args, [key]: e.target.value })}
                      placeholder={spec.description || key}
                      autoFocus
                    />
                  )}
                </label>
              );
            })}
            <div className="flex gap-2 mt-3">
              <button
                onClick={dispatch}
                disabled={running}
                className="btn-primary flex items-center gap-1 text-xs"
              >
                <Zap size={11} /> {running ? "Running..." : "Run"}
              </button>
              <button
                onClick={() => { setSelectedId(null); setArgs({}); }}
                className="btn-secondary text-xs"
              >
                Back
              </button>
            </div>
          </div>
        )}

        <div className="border-t border-border px-3 py-1 text-[9px] text-text-dim font-mono flex justify-between">
          <span>
            <span className="kbd">↵</span> pick first · <span className="kbd">Esc</span> close
          </span>
          <span>
            <span className="kbd">{navigator.platform.match(/Mac|iPhone|iPad/) ? "Cmd" : "Ctrl"}+Shift+K</span>
          </span>
        </div>
      </div>
    </div>
  );
}
