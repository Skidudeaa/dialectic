// CrossBookMatrix — every book on one screen.
//
// The legacy CrossBookPanel surfaces *correlation flags* between books
// (recession-aligned, shared-market). That answers a different question
// than "what's hot right now across the whole cockpit?". This component
// fills that gap: one row per book, columns for phase / top signals /
// open trades / freshness. Click a row to make that book the active one.
//
// Data sources:
//   - bookStates (passed in, kept warm by Dashboard) for phase, node
//     states, confluence scores, and snapshot timestamp.
//   - /api/v1/trades for open trade counts grouped by book.
//   - 30s self-refresh for trades; bookStates refresh from parent.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Layers, RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { OpenTradeSummary, ThesisBook, ThesisState } from "../lib/types";
import { bookShortId, worstStateColor } from "./BookTabBar";

interface Props {
  books: ThesisBook[];
  bookStates: Record<string, ThesisState | null | undefined>;
  activeBookId: string | null;
  onSelect: (id: string) => void;
}

const TRADES_REFRESH_MS = 30_000;

/** "12s" / "5m" / "3h" / "2d" — same vocabulary as ThesisViewer/OutboxBadge. */
function relativeAge(iso: string | undefined | null): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

/** Snapshot age >2h is suspicious; >12h is broken. */
function ageClass(iso: string | undefined | null): string {
  if (!iso) return "text-text-dim";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "text-text-dim";
  const seconds = (Date.now() - then) / 1000;
  if (seconds > 12 * 3600) return "text-danger";
  if (seconds > 2 * 3600) return "text-amber";
  return "text-text-muted";
}

function topSignals(state: ThesisState | null | undefined, k: number = 3): string[] {
  if (!state || !state.confluenceScores) return [];
  return Object.entries(state.confluenceScores)
    .filter(([, score]) => Number.isFinite(score) && score > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, k)
    .map(([id]) => id);
}

function phaseLabel(state: ThesisState | null | undefined): {
  text: string;
  cls: string;
} {
  if (!state?.cascadePhase) return { text: "—", cls: "text-text-dim" };
  const { number, key, status } = state.cascadePhase;
  const text = `${number}. ${key}`;
  // "WE ARE HERE" / STARTING / IN_PROGRESS lifts the row visually.
  if (status === "WE ARE HERE" || status === "IN_PROGRESS") {
    return { text: `${text} · ${status}`, cls: "text-amber" };
  }
  if (status === "STARTING") {
    return { text: `${text} · ${status}`, cls: "text-teal" };
  }
  return { text, cls: "text-text-muted" };
}

export default function CrossBookMatrix({
  books,
  bookStates,
  activeBookId,
  onSelect,
}: Props) {
  const [trades, setTrades] = useState<OpenTradeSummary[]>([]);
  const [tradesError, setTradesError] = useState<string | null>(null);
  const [loadingTrades, setLoadingTrades] = useState(false);
  const [tickNow, setTickNow] = useState(() => Date.now());

  const loadTrades = useCallback(async () => {
    setLoadingTrades(true);
    try {
      const data = await apiFetch<OpenTradeSummary[]>("/api/v1/trades");
      setTrades(data);
      setTradesError(null);
    } catch {
      setTradesError("Failed to load open trades");
    } finally {
      setLoadingTrades(false);
    }
  }, []);

  useEffect(() => {
    loadTrades();
    const t = setInterval(loadTrades, TRADES_REFRESH_MS);
    return () => clearInterval(t);
  }, [loadTrades]);

  // Re-tick once per minute so relativeAge stays accurate without refetching.
  useEffect(() => {
    const t = setInterval(() => setTickNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  // Suppress unused-var lint — tickNow is read implicitly via the rerender.
  void tickNow;

  const tradesByBook = useMemo(() => {
    const map: Record<string, OpenTradeSummary[]> = {};
    for (const t of trades) {
      const book = t.book || "";
      if (!book) continue;
      if (!map[book]) map[book] = [];
      map[book].push(t);
    }
    return map;
  }, [trades]);

  return (
    <div data-testid="cross-book-matrix">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest flex items-center gap-1">
          <Layers size={11} className="text-amber" /> Cross-Book Matrix
        </span>
        <button
          onClick={loadTrades}
          disabled={loadingTrades}
          className="text-text-dim hover:text-amber p-0.5"
          title="Refresh trades"
          aria-label="Refresh cross-book matrix"
        >
          <RefreshCw size={11} className={loadingTrades ? "animate-spin" : ""} />
        </button>
      </div>

      {tradesError && (
        <div className="text-[10px] text-danger font-mono mb-1 px-1">
          {tradesError}{" "}
          <button onClick={loadTrades} className="underline hover:text-amber">
            retry
          </button>
        </div>
      )}

      {books.length === 0 ? (
        <div className="text-[10px] text-text-dim font-mono px-1 py-2">
          No books loaded.
        </div>
      ) : (
        <div className="border border-border rounded overflow-hidden">
          {/* Header row — sticky col labels */}
          <div className="grid grid-cols-[6rem_minmax(7rem,1fr)_minmax(8rem,1.4fr)_4rem_3.5rem] text-[9px] uppercase tracking-widest text-text-dim font-mono bg-elevated/40 border-b border-border">
            <div className="px-2 py-1">Book</div>
            <div className="px-2 py-1">Phase</div>
            <div className="px-2 py-1">Top Signals</div>
            <div className="px-2 py-1 text-right">Trades</div>
            <div className="px-2 py-1 text-right">Age</div>
          </div>

          {books.map((book) => {
            const state = bookStates[book.id];
            const dot = worstStateColor(state);
            const phase = phaseLabel(state);
            const signals = topSignals(state);
            const myTrades = tradesByBook[book.id] || [];
            const isActive = book.id === activeBookId;
            return (
              <button
                key={book.id}
                onClick={() => onSelect(book.id)}
                title={book.title}
                className={`w-full grid grid-cols-[6rem_minmax(7rem,1fr)_minmax(8rem,1.4fr)_4rem_3.5rem] text-left items-center text-[11px] font-mono border-b border-border/40 last:border-0 transition-colors ${
                  isActive
                    ? "bg-elevated text-amber"
                    : "text-text-muted hover:bg-elevated/60 hover:text-text-primary"
                }`}
                data-testid={`matrix-row-${book.id}`}
              >
                <div className="px-2 py-1.5 flex items-center gap-1.5 min-w-0">
                  <span
                    className={`inline-block w-1.5 h-1.5 rounded-full shrink-0 ${dot.cls}`}
                    aria-hidden="true"
                  />
                  <span className="truncate">{bookShortId(book.id)}</span>
                </div>
                <div className={`px-2 py-1.5 truncate ${phase.cls}`}>
                  {phase.text}
                </div>
                <div className="px-2 py-1.5 truncate text-text-muted">
                  {signals.length > 0 ? (
                    signals.join(", ")
                  ) : (
                    <span className="text-text-dim">—</span>
                  )}
                </div>
                <div className="px-2 py-1.5 text-right">
                  {myTrades.length > 0 ? (
                    <span className="text-amber">{myTrades.length}</span>
                  ) : (
                    <span className="text-text-dim">0</span>
                  )}
                </div>
                <div
                  className={`px-2 py-1.5 text-right ${ageClass(state?.timestamp)}`}
                >
                  {relativeAge(state?.timestamp)}
                </div>
              </button>
            );
          })}
        </div>
      )}

      <p className="text-[9px] text-text-dim font-mono mt-1.5 px-1 leading-snug">
        Click a row to switch active book. Dot reflects worst node state. Ages
        update every minute; trades refresh every 30s.
      </p>
    </div>
  );
}
