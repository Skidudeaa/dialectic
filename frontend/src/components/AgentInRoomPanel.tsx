// Agent-in-room panel (Unit 11).
//
// WHY: The desk's LLM (via @claude / @gpt / @gemini / @compare in chat)
// is the third analyst in the room — but its state-of-the-world is
// invisible to the humans. This panel renders:
//   - Header: which book / current snapshot revision the agent is
//     reasoning against, plus the "default model" constant.
//   - Body: scrollable list of recent LLM calls — timestamp, model
//     badge, prompt-first-80, tool-call chips, latency, status.
//   - Footer: default model + last fetch timestamp.
//
// Refresh strategy: 15s poll + listen for any state_update WS frame
// (the coordinator broadcasts one on every commit) and refetch on
// receipt so the snapshot-revision line stays current.

import { useEffect, useState, useCallback } from "react";
import { Bot, RefreshCw, CheckCircle2, XCircle, Clock3 } from "lucide-react";
import { apiFetch, subscribeRoomMessages } from "../lib/api";
import type {
  AgentCallRow,
  AgentLogResponse,
  AgentState,
  ThesisBook,
} from "../lib/types";

interface Props {
  bookId: string | null;
  books: ThesisBook[];
  roomId?: string | null;
}

const POLL_INTERVAL_MS = 15_000;
const LOG_LIMIT = 20;

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  if (diff < 60_000) return `${Math.round(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  return `${Math.round(diff / 86_400_000)}d ago`;
}

function StatusChip({ status }: { status: string }) {
  if (status === "success") {
    return (
      <span className="inline-flex items-center gap-0.5 text-teal text-[10px] font-mono px-1 py-px rounded bg-teal/10 border border-teal/30">
        <CheckCircle2 size={9} /> ok
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="inline-flex items-center gap-0.5 text-danger text-[10px] font-mono px-1 py-px rounded bg-danger/10 border border-danger/30">
        <XCircle size={9} /> err
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-amber text-[10px] font-mono px-1 py-px rounded bg-amber/10 border border-amber/30">
      <Clock3 size={9} /> {status}
    </span>
  );
}

function ModelBadge({ model }: { model: string }) {
  // Color families picked to echo the chat @mention palette.
  let cls = "text-text-muted bg-elevated border-border/50";
  const m = model.toLowerCase();
  if (m.includes("claude")) cls = "text-amber bg-amber/10 border-amber/30";
  else if (m.includes("gpt")) cls = "text-teal bg-teal/10 border-teal/30";
  else if (m.includes("gemini")) cls = "text-blue bg-blue/10 border-blue/30";
  else if (m.includes("deepseek")) cls = "text-purple bg-purple/10 border-purple/30";
  return (
    <span
      className={`inline-block text-[9px] font-mono px-1 py-px rounded border truncate max-w-[20ch] ${cls}`}
      title={model}
    >
      {model}
    </span>
  );
}

function ToolChips({ tools }: { tools: string[] }) {
  if (!tools || tools.length === 0) {
    return <span className="text-[9px] text-text-dim font-mono">no-tools</span>;
  }
  return (
    <span className="inline-flex flex-wrap gap-0.5">
      {tools.map((t, i) => (
        <span
          key={`${t}-${i}`}
          className="text-[9px] font-mono px-1 py-px rounded bg-elevated border border-border/50 text-text-muted"
        >
          {t}
        </span>
      ))}
    </span>
  );
}

export default function AgentInRoomPanel({ bookId, books, roomId }: Props) {
  const [state, setState] = useState<AgentState | null>(null);
  const [rows, setRows] = useState<AgentCallRow[]>([]);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeBook = books.find((b) => b.id === bookId) || null;

  const loadAll = useCallback(async () => {
    try {
      setError(null);
      const logQs = new URLSearchParams({ limit: String(LOG_LIMIT) });
      if (roomId) logQs.set("room_id", roomId);
      const stateQs = bookId ? `?thesis_id=${encodeURIComponent(bookId)}` : "";
      const [logResp, stateResp] = await Promise.all([
        apiFetch<AgentLogResponse>(`/api/v1/agent/log?${logQs.toString()}`),
        apiFetch<AgentState>(`/api/v1/agent/state${stateQs}`),
      ]);
      setRows(logResp.rows || []);
      setFetchedAt(logResp.fetchedAt || new Date().toISOString());
      setState(stateResp);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load agent data");
    } finally {
      setLoading(false);
    }
  }, [bookId, roomId]);

  // Initial load + 15s poll.
  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [loadAll]);

  // Refetch on any state_update — coordinator bumps a snapshot revision so
  // the header line would otherwise lag up to 15s.
  useEffect(() => {
    const unsub = subscribeRoomMessages((msg) => {
      if (msg.type === "state_update") {
        loadAll();
      }
    });
    return () => {
      unsub();
    };
  }, [loadAll]);

  return (
    <section className="space-y-1.5">
      <header className="flex items-center justify-between border-b border-border pb-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <Bot size={13} className="text-amber shrink-0" />
          <h2 className="font-mono text-xs text-amber font-semibold truncate">
            Agent in room
          </h2>
        </div>
        <button
          onClick={loadAll}
          className="text-text-dim hover:text-amber p-0.5"
          title="Refresh now"
          aria-label="Refresh agent panel"
        >
          <RefreshCw size={11} />
        </button>
      </header>

      {/* Snapshot context */}
      <div className="text-[10px] font-mono text-text-muted space-y-0.5">
        <div className="flex items-center justify-between gap-1">
          <span className="text-text-dim">book</span>
          <span className="truncate max-w-[22ch]" title={bookId || ""}>
            {activeBook?.title ?? bookId ?? "—"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-text-dim">snapshot rev</span>
          <span className="text-text-primary font-semibold">
            {state?.snapshot_revision ?? "n/a"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-text-dim">last call</span>
          <span className="flex items-center gap-1">
            {state?.last_call_status && (
              <StatusChip status={state.last_call_status} />
            )}
            <span className="text-text-muted">
              {relativeTime(state?.last_call_ts)}
            </span>
          </span>
        </div>
      </div>

      {/* Call feed */}
      <div className="border-t border-border pt-1">
        <div className="text-[9px] uppercase tracking-widest text-text-dim font-mono mb-1">
          Recent calls · {rows.length}
        </div>
        {loading && rows.length === 0 && (
          <p className="text-[10px] text-text-dim font-mono">Loading…</p>
        )}
        {error && (
          <p className="text-[10px] text-danger font-mono">{error}</p>
        )}
        {!loading && !error && rows.length === 0 && (
          <p className="text-[10px] text-text-dim font-mono">
            No LLM calls yet — @mention claude/gpt/gemini in chat to seed the log.
          </p>
        )}
        <ul className="space-y-1">
          {rows.map((row, i) => (
            <li
              key={`${row.ts}-${i}`}
              className="bg-elevated/50 border border-border/60 rounded px-1.5 py-1 text-[10px] font-mono"
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-text-dim shrink-0">
                  {relativeTime(row.ts)}
                </span>
                <ModelBadge model={row.model} />
                <StatusChip status={row.status} />
              </div>
              <div
                className="text-text-muted mt-0.5 truncate"
                title={row.prompt_first_80}
              >
                {row.prompt_first_80 || <em className="text-text-dim">(empty)</em>}
              </div>
              <div className="flex items-center justify-between mt-0.5 text-[9px]">
                <ToolChips tools={row.tool_calls || []} />
                <span className="text-text-dim flex items-center gap-1">
                  <span>{Math.round(row.latency_ms)}ms</span>
                  {row.snapshot_revision !== null && (
                    <span title="Snapshot revision at call time">
                      · rev {row.snapshot_revision}
                    </span>
                  )}
                </span>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <footer className="border-t border-border pt-1 text-[9px] text-text-dim font-mono flex items-center justify-between">
        <span>
          Default model:{" "}
          <span className="text-text-muted">
            {state?.default_model ?? "—"}
          </span>
        </span>
        <span>
          {fetchedAt ? `updated ${relativeTime(fetchedAt)}` : "—"}
        </span>
      </footer>
    </section>
  );
}
