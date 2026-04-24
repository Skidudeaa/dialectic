// ThesisViewer — primary read-only view of a thesis snapshot.
//
// Information density is non-negotiable: the analyst stares at this all day.
// Optimisation goals (in order):
//   1. Cascade phase recognisable in <200ms ("WE ARE HERE" callout).
//   2. Fired/approaching nodes dominate the visual field.
//   3. Stale data NEVER renders as live truth (timestamp + age glyph).
//   4. Analyst can drill into a node (price vs threshold) without leaving panel.
//   5. Filter/sort by movement, collapse stable nodes when noisy.
import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
  RefreshCw,
  AlertTriangle,
  ChevronRight,
  ChevronDown,
  Filter as FilterIcon,
  Activity,
  Clock,
} from "lucide-react";
import { apiFetch, getTVIndicators } from "../lib/api";
import type { ThesisBook, ThesisState, TVIndicatorReading } from "../lib/types";
import TVIndicatorBadge from "./TVIndicatorBadge";

interface Props {
  bookId: string | null;
  books: ThesisBook[];
}

// ── Constants ────────────────────────────────────────────────────────────

const PHASE_NAMES: Record<number, string> = {
  1: "Shock",
  2: "Transmission",
  3: "Amplification",
  4: "Policy Response",
  5: "Resolution",
};

// One-line "next signpost" hint per phase (display-only operator nudge).
const PHASE_NEXT_HINT: Record<number, string> = {
  1: "Watch transmission channels for first downstream firings.",
  2: "Look for amplification — multi-path confluence on shared nodes.",
  3: "Policy response (rates / fiscal / sanctions) signals a phase turn.",
  4: "Resolution requires sustained reversal across upstream nodes.",
  5: "Thesis lifecycle complete — close out remaining positions.",
};

// State sort priority (lower = higher in list).
const STATE_ORDER: Record<string, number> = {
  fired: 0,
  approaching: 1,
  gated: 2,
  monitoring: 3,
  constrained: 4,
  stable: 5,
};

// Snapshot freshness thresholds (seconds).
const STALE_AFTER = 30 * 60; // 30m → amber chip
const VERY_STALE_AFTER = 6 * 60 * 60; // 6h → red chip

// Filter pills for node list.
type NodeFilter = "all" | "moving" | "fired" | "approaching" | "stable";

// ── Helpers ──────────────────────────────────────────────────────────────

function stateBadgeClass(state: string): string {
  switch (state) {
    case "fired":
      return "badge-fired";
    case "approaching":
      return "badge-approaching";
    case "stable":
      return "badge-stable";
    case "gated":
      return "badge-gated";
    default:
      return "badge-monitoring";
  }
}

/** Rough state weight (0-1) used to sort the cascade ribbon and phase color. */
function phaseColor(n: number): string {
  if (n >= 4) return "bg-teal";
  if (n >= 3) return "bg-danger";
  if (n >= 1) return "bg-amber";
  return "bg-elevated";
}

/** Format daysRemaining as "3d 14h" instead of "3.58d". */
function formatDays(days: number): string {
  if (days < 0) return `${Math.abs(Math.round(days))}d ago`;
  if (days < 1) {
    const hours = Math.max(1, Math.round(days * 24));
    return `${hours}h`;
  }
  const wholeDays = Math.floor(days);
  const remHours = Math.round((days - wholeDays) * 24);
  if (remHours === 0 || wholeDays >= 14) return `${wholeDays}d`;
  return `${wholeDays}d ${remHours}h`;
}

function countdownClass(days: number): string {
  if (days <= 1) return "text-danger animate-pulse";
  if (days <= 3) return "text-danger";
  if (days <= 7) return "text-amber";
  if (days <= 14) return "text-amber/70";
  return "text-text-muted";
}

/** Format an ISO timestamp as "12s" / "5m" / "3h" / "2d". */
function relativeAge(iso: string | undefined): { label: string; seconds: number } | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  let label: string;
  if (seconds < 60) label = `${Math.round(seconds)}s`;
  else if (seconds < 3600) label = `${Math.round(seconds / 60)}m`;
  else if (seconds < 86400) label = `${Math.round(seconds / 3600)}h`;
  else label = `${Math.round(seconds / 86400)}d`;
  return { label, seconds };
}

/** Pretty-label for a feed-freshness source key. */
const SOURCE_LABELS: Record<string, string> = {
  yahoo: "Yahoo",
  polymarket: "Polymarket",
  derived: "Derived",
  fred: "FRED",
  econ: "Calendar",
};

/**
 * Per-source freshness strip (cockpit Unit 5).
 *
 * Renders one pill per entry in `feedFreshness`. Amber if
 * `now - fetchedAt > ttlSeconds`, otherwise muted/teal. The `tickNow` prop
 * is how we stay live without refetching — ThesisViewer already bumps it
 * once a minute.
 */
function FeedFreshnessStrip({
  freshness,
  tickNow,
}: {
  freshness: ThesisState["feedFreshness"];
  tickNow: number;
}) {
  const entries = freshness ? Object.values(freshness) : [];
  if (!entries.length) return null;
  // `tickNow` is implicitly read so this component re-renders on tick.
  void tickNow;
  const now = Date.now();

  return (
    <div
      className="card py-1 px-2"
      aria-label="Live data freshness per source"
      role="group"
    >
      <div className="flex items-center justify-between mb-0.5">
        <span className="text-[9px] text-text-dim uppercase tracking-widest">
          Feeds
        </span>
        <span className="text-[9px] text-text-dim font-mono">
          stale &gt; ttl
        </span>
      </div>
      <div className="flex flex-wrap gap-1">
        {entries.map((f) => {
          const parsed = Date.parse(f.fetchedAt);
          const ageMs = Number.isNaN(parsed) ? Infinity : now - parsed;
          const stale = ageMs > f.ttlSeconds * 1000;
          const age = relativeAge(f.fetchedAt);
          const label = SOURCE_LABELS[f.source] ?? f.source;
          const pillCls = stale
            ? "bg-amber/20 text-amber border-amber/40"
            : "bg-teal/10 text-teal border-teal/30";
          return (
            <span
              key={f.source}
              className={`inline-flex items-center gap-1 text-[9px] font-mono px-1.5 py-px rounded border ${pillCls}`}
              title={
                f.detail
                  ? `${label} · ${f.detail} · ttl ${f.ttlSeconds}s · fetched ${f.fetchedAt}`
                  : `${label} · ttl ${f.ttlSeconds}s · fetched ${f.fetchedAt}`
              }
            >
              <span className="uppercase tracking-wide">{label}</span>
              <span className={stale ? "opacity-90" : "opacity-70"}>
                {age ? age.label : "—"}
              </span>
              {stale && (
                <span className="text-[8px] uppercase tracking-wider">stale</span>
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** Live-region polite announcer: builds a one-line summary of state changes. */
function diffNodeStates(
  prev: Record<string, string>,
  next: Record<string, string>,
): string[] {
  const changes: string[] = [];
  for (const id of Object.keys(next)) {
    const before = prev[id];
    const after = next[id];
    if (before && before !== after) {
      changes.push(`${id} ${before} → ${after}`);
    }
  }
  return changes;
}

// ── Component ────────────────────────────────────────────────────────────

export default function ThesisViewer({ bookId, books }: Props) {
  const [selectedBook, setSelectedBook] = useState(bookId || "");
  const [state, setState] = useState<ThesisState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tvIndicators, setTVIndicators] = useState<Record<string, TVIndicatorReading>>({});
  const [filter, setFilter] = useState<NodeFilter>("all");
  const [hideStable, setHideStable] = useState(false);
  const [expandedNode, setExpandedNode] = useState<string | null>(null);
  const [tickNow, setTickNow] = useState(() => Date.now());
  const prevStatesRef = useRef<Record<string, string>>({});
  const [announce, setAnnounce] = useState<string>("");

  useEffect(() => {
    // Sync prop -> local picker when bookId arrives after mount; not derivable.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (bookId && !selectedBook) setSelectedBook(bookId);
  }, [bookId, selectedBook]);

  const fetchState = useCallback(async (book: string) => {
    setError(null);
    try {
      const data = await apiFetch<ThesisState>(`/api/thesis/${book}/state`);
      setState((prev) => {
        // Diff for live-region announcement
        if (prev) {
          const changes = diffNodeStates(prev.nodeStates || {}, data.nodeStates || {});
          if (changes.length > 0) {
            setAnnounce(`${changes.length} node state change${changes.length > 1 ? "s" : ""}: ${changes.slice(0, 3).join(", ")}`);
          }
        }
        return data;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load thesis state");
    }
  }, []);

  useEffect(() => {
    if (!selectedBook) return;
    // Standard fetch-on-effect pattern: set loading flag, kick async, clear on settle.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    fetchState(selectedBook).finally(() => setLoading(false));
    getTVIndicators(selectedBook)
      .then(setTVIndicators)
      .catch(() => setTVIndicators({}));

    // WHY: 5-min poll catches state changes from pipeline runs.
    const interval = setInterval(() => {
      fetchState(selectedBook);
      getTVIndicators(selectedBook).then(setTVIndicators).catch(() => {});
    }, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [selectedBook, fetchState]);

  // Tick once a minute so the snapshot-age chip stays accurate without re-fetching.
  useEffect(() => {
    const t = setInterval(() => setTickNow(Date.now()), 60 * 1000);
    return () => clearInterval(t);
  }, []);

  // Track previous snapshot for next diff
  useEffect(() => {
    if (state) prevStatesRef.current = state.nodeStates || {};
  }, [state]);

  // ── Derived data ──────────────────────────────────────────────────────

  const phase = state?.cascadePhase;
  const nodeStates = useMemo(() => state?.nodeStates || {}, [state]);
  const confluence = useMemo(() => state?.confluenceScores || {}, [state]);
  const countdowns = useMemo(() => state?.countdowns || [], [state]);
  const scenarios = useMemo(() => state?.scenarioImpacts || {}, [state]);
  const marketSnapshot = useMemo(() => state?.marketSnapshot || {}, [state]);

  // Sort countdowns by urgency (closest first).
  const sortedCountdowns = useMemo(
    () => [...countdowns].sort((a, b) => a.daysRemaining - b.daysRemaining),
    [countdowns],
  );

  // Sort scenarios by expected value (probability * |impact|), highest first.
  const sortedScenarios = useMemo(() => {
    const entries = Object.entries(scenarios);
    return entries
      .map(([id, s]) => ({
        id,
        prob: s.probability || 0,
        impact: s.netImpact || 0,
        ev: (s.probability || 0) * (s.netImpact || 0),
      }))
      .sort((a, b) => Math.abs(b.ev) - Math.abs(a.ev));
  }, [scenarios]);

  const maxScenarioImpact = useMemo(() => {
    const all = sortedScenarios.map((s) => Math.abs(s.impact));
    return Math.max(...all, 1);
  }, [sortedScenarios]);

  // Counts for filter pills.
  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const st of Object.values(nodeStates)) counts[st] = (counts[st] || 0) + 1;
    return counts;
  }, [nodeStates]);

  // Apply filter + hideStable + sort by state priority.
  const visibleNodes = useMemo(() => {
    let entries = Object.entries(nodeStates);
    if (hideStable) {
      entries = entries.filter(([, s]) => s !== "stable");
    }
    if (filter !== "all") {
      if (filter === "moving") {
        entries = entries.filter(([, s]) => s === "fired" || s === "approaching");
      } else {
        entries = entries.filter(([, s]) => s === filter);
      }
    }
    entries.sort(([aId, aS], [bId, bS]) => {
      const oa = STATE_ORDER[aS] ?? 9;
      const ob = STATE_ORDER[bS] ?? 9;
      if (oa !== ob) return oa - ob;
      // Within state, nodes with confluence rank higher.
      const ca = confluence[aId] ?? 0;
      const cb = confluence[bId] ?? 0;
      if (ca !== cb) return cb - ca;
      return aId.localeCompare(bId);
    });
    return entries;
  }, [nodeStates, filter, hideStable, confluence]);

  const maxConf = useMemo(
    () => Math.max(...Object.values(confluence), 1),
    [confluence],
  );

  // Snapshot freshness.
  const snapshotAge = useMemo(() => {
    void tickNow; // recompute on tick
    return relativeAge(state?.timestamp);
  }, [state?.timestamp, tickNow]);

  const isStale = snapshotAge !== null && snapshotAge.seconds >= STALE_AFTER;
  const isVeryStale = snapshotAge !== null && snapshotAge.seconds >= VERY_STALE_AFTER;

  // ── Render helpers ────────────────────────────────────────────────────

  const refresh = useCallback(() => {
    if (!selectedBook) return;
    setLoading(true);
    Promise.all([
      fetchState(selectedBook),
      getTVIndicators(selectedBook).then(setTVIndicators).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, [selectedBook, fetchState]);

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <section className="space-y-2" aria-label="Thesis viewer">
      {/* Live region for state-change announcements (screen readers) */}
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announce}
      </div>

      {/* Header: title + freshness + refresh */}
      <header className="flex items-center justify-between gap-1">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
            Thesis
          </span>
          {snapshotAge && (
            <span
              className={`inline-flex items-center gap-0.5 text-[9px] font-mono px-1 rounded ${
                isVeryStale
                  ? "bg-danger/20 text-danger"
                  : isStale
                  ? "bg-amber/20 text-amber"
                  : "text-text-dim"
              }`}
              title={`Snapshot timestamp: ${state?.timestamp ?? "unknown"}`}
            >
              <Clock size={9} aria-hidden />
              {snapshotAge.label}
              {isStale && <AlertTriangle size={9} aria-hidden />}
            </span>
          )}
        </div>
        <button
          onClick={refresh}
          className="text-text-dim hover:text-amber p-0.5 disabled:opacity-50"
          disabled={loading || !selectedBook}
          aria-label="Refresh thesis snapshot"
          title="Refresh"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </header>

      <select
        className="input w-full"
        value={selectedBook}
        onChange={(e) => {
          setSelectedBook(e.target.value);
          setExpandedNode(null);
          setState(null);
        }}
        aria-label="Select thesis book"
      >
        {books.length === 0 && <option value="">No books loaded</option>}
        {books.map((b) => (
          <option key={b.id} value={b.id}>
            {b.title}
          </option>
        ))}
      </select>

      {/* Loading shimmer (only when no prior state shown) */}
      {loading && !state && (
        <div className="card animate-pulse">
          <div className="h-2 bg-elevated rounded w-3/4 mb-2" />
          <div className="h-1 bg-elevated rounded w-full mb-2" />
          <div className="h-2 bg-elevated rounded w-1/2" />
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div
          className="card border-danger/40 bg-danger/10"
          role="alert"
          aria-live="assertive"
        >
          <div className="flex items-start gap-1.5">
            <AlertTriangle size={12} className="text-danger mt-0.5 shrink-0" aria-hidden />
            <div className="min-w-0">
              <div className="text-[10px] text-danger font-medium uppercase tracking-wide">
                Snapshot fetch failed
              </div>
              <div className="text-[10px] text-text-muted font-mono break-words mt-0.5">
                {error}
              </div>
              <button onClick={refresh} className="btn-secondary mt-1 text-[10px]">
                Retry
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Empty state — no book selected */}
      {!selectedBook && !loading && !error && (
        <div className="card text-center py-3">
          <span className="text-[10px] text-text-dim">Select a thesis to view state.</span>
        </div>
      )}

      {/* Empty state — book has no nodes */}
      {state && Object.keys(nodeStates).length === 0 && (
        <div className="card text-center py-3">
          <span className="text-[10px] text-text-dim">
            Snapshot loaded but no nodes — check book config.
          </span>
        </div>
      )}

      {state && Object.keys(nodeStates).length > 0 && (
        <>
          {/* ── Cascade Phase: WE ARE HERE ───────────────────────────── */}
          <div
            className={`card ${
              isVeryStale ? "opacity-60" : ""
            } ${(phase?.number || 0) >= 3 ? "border-danger/30" : "border-amber/30"}`}
            aria-label="Cascade phase tracker"
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-[9px] text-text-dim uppercase tracking-widest">
                Cascade
              </span>
              <span
                className={`text-[9px] font-mono font-bold uppercase tracking-wide px-1 rounded ${
                  (phase?.number || 0) >= 3
                    ? "bg-danger/20 text-danger"
                    : "bg-amber/20 text-amber"
                }`}
              >
                {phase?.status ?? "—"}
              </span>
            </div>

            {/* 5-segment ribbon with WE ARE HERE marker */}
            <div className="relative my-1.5" role="progressbar" aria-valuemin={1} aria-valuemax={5} aria-valuenow={phase?.number || 0}>
              <div className="flex items-center gap-0.5">
                {[1, 2, 3, 4, 5].map((n) => {
                  const reached = n <= (phase?.number || 0);
                  const current = n === (phase?.number || 0);
                  return (
                    <div
                      key={n}
                      className={`h-1.5 flex-1 rounded-sm transition-colors ${
                        reached ? phaseColor(n) : "bg-elevated"
                      } ${current ? "ring-1 ring-text-primary/40" : ""}`}
                      title={`${n}. ${PHASE_NAMES[n]}`}
                    />
                  );
                })}
              </div>
              {/* WE ARE HERE chevron, positioned over the current segment */}
              {phase?.number && phase.number >= 1 && phase.number <= 5 && (
                <div
                  className="absolute -top-2 text-[8px] font-mono uppercase tracking-wider text-text-primary/80 whitespace-nowrap pointer-events-none"
                  style={{
                    left: `calc(${((phase.number - 0.5) / 5) * 100}% - 18px)`,
                  }}
                  aria-hidden
                >
                  ▼ here
                </div>
              )}
            </div>

            <div className="flex items-baseline justify-between gap-2 mt-2">
              <span className="text-sm font-mono font-bold text-text-primary">
                {phase?.number}. {PHASE_NAMES[phase?.number || 0] || "—"}
              </span>
              <span className="text-[9px] text-text-dim font-mono">
                {phase?.number ? `${5 - phase.number} phase${5 - phase.number === 1 ? "" : "s"} ahead` : ""}
              </span>
            </div>

            {phase?.number && PHASE_NEXT_HINT[phase.number] && (
              <div className="text-[10px] text-text-muted mt-1 leading-snug border-t border-border/50 pt-1">
                <span className="text-text-dim mr-1">→</span>
                {PHASE_NEXT_HINT[phase.number]}
              </div>
            )}
          </div>

          {/* ── Feed freshness strip (cockpit Unit 5) ─────────────────── */}
          <FeedFreshnessStrip freshness={state.feedFreshness} tickNow={tickNow} />

          {/* ── Nodes ─────────────────────────────────────────────────── */}
          <div>
            <div className="flex items-center justify-between mb-1 gap-1">
              <span className="text-[10px] text-text-dim uppercase tracking-widest">
                Nodes <span className="text-text-muted">({visibleNodes.length}/{Object.keys(nodeStates).length})</span>
              </span>
              <button
                onClick={() => setHideStable((v) => !v)}
                className={`inline-flex items-center gap-0.5 text-[9px] font-mono px-1 rounded ${
                  hideStable ? "bg-amber/20 text-amber" : "text-text-dim hover:text-text-muted"
                }`}
                title={hideStable ? "Show stable nodes" : "Hide stable nodes"}
                aria-pressed={hideStable}
              >
                <FilterIcon size={9} aria-hidden />
                {hideStable ? "stable hidden" : "all states"}
              </button>
            </div>

            {/* Filter pills — counts give a glanceable distribution. */}
            <div className="flex flex-wrap gap-0.5 mb-1" role="tablist" aria-label="Filter nodes by state">
              {(["all", "moving", "fired", "approaching", "stable"] as NodeFilter[]).map((f) => {
                const count =
                  f === "all"
                    ? Object.keys(nodeStates).length
                    : f === "moving"
                    ? (stateCounts.fired || 0) + (stateCounts.approaching || 0)
                    : stateCounts[f] || 0;
                const active = filter === f;
                return (
                  <button
                    key={f}
                    role="tab"
                    aria-selected={active}
                    onClick={() => setFilter(f)}
                    className={`text-[9px] font-mono uppercase tracking-wide px-1 py-px rounded transition-colors ${
                      active
                        ? f === "fired"
                          ? "bg-danger/30 text-danger"
                          : f === "approaching"
                          ? "bg-amber/30 text-amber"
                          : f === "stable"
                          ? "bg-teal/30 text-teal"
                          : "bg-elevated text-text-primary"
                        : "text-text-dim hover:text-text-muted hover:bg-elevated/50"
                    }`}
                  >
                    {f}
                    <span className="text-text-dim/80 ml-0.5">{count}</span>
                  </button>
                );
              })}
            </div>

            <ul
              className="space-y-px"
              role="list"
              aria-label="Node state list"
            >
              {visibleNodes.length === 0 && (
                <li className="text-[10px] text-text-dim italic px-1 py-1">
                  No nodes match this filter.
                </li>
              )}
              {visibleNodes.map(([id, st]) => {
                const conf = confluence[id];
                const ind = tvIndicators[id];
                const isExpanded = expandedNode === id;
                const isFired = st === "fired";
                const isApproaching = st === "approaching";
                return (
                  <li key={id}>
                    <button
                      onClick={() => setExpandedNode(isExpanded ? null : id)}
                      className={`w-full flex items-center justify-between py-px px-1 rounded-sm text-left hover:bg-elevated/50 focus:bg-elevated focus:outline-none transition-colors ${
                        isFired ? "bg-danger/[.04]" : isApproaching ? "bg-amber/[.04]" : ""
                      }`}
                      aria-expanded={isExpanded}
                      aria-controls={`node-detail-${id}`}
                    >
                      <span className="flex items-center min-w-0 mr-2 flex-1">
                        {isExpanded ? (
                          <ChevronDown size={9} className="text-text-dim mr-0.5 shrink-0" aria-hidden />
                        ) : (
                          <ChevronRight size={9} className="text-text-dim mr-0.5 shrink-0" aria-hidden />
                        )}
                        <span
                          className={`text-[11px] font-mono truncate ${
                            isFired
                              ? "text-text-primary font-medium"
                              : isApproaching
                              ? "text-text-primary"
                              : st === "stable"
                              ? "text-text-muted"
                              : "text-text-primary"
                          }`}
                        >
                          {id}
                        </span>
                        {conf !== undefined && conf > 1 && (
                          <span
                            className="ml-1 text-[8px] font-mono text-amber/80 inline-flex items-center"
                            title={`Confluence score ${conf.toFixed(2)} — multiple paths converge here`}
                          >
                            <Activity size={8} aria-hidden className="mr-px" />
                            ×{conf.toFixed(1)}
                          </span>
                        )}
                        <TVIndicatorBadge reading={ind} />
                      </span>
                      <span className={stateBadgeClass(st)}>{st}</span>
                    </button>

                    {/* Inline detail accordion: raw signals for this node. */}
                    {isExpanded && (
                      <div
                        id={`node-detail-${id}`}
                        className="ml-3 mt-0.5 mb-1 px-1.5 py-1 bg-elevated/40 border-l border-border rounded-sm space-y-0.5"
                      >
                        {marketSnapshot[id] !== undefined && (
                          <div className="flex items-baseline justify-between text-[10px] font-mono">
                            <span className="text-text-dim">current</span>
                            <span className="text-text-primary">
                              {typeof marketSnapshot[id] === "number"
                                ? (marketSnapshot[id] as number).toLocaleString(undefined, {
                                    maximumFractionDigits: 2,
                                  })
                                : String(marketSnapshot[id])}
                            </span>
                          </div>
                        )}
                        {conf !== undefined && (
                          <div className="flex items-baseline justify-between text-[10px] font-mono">
                            <span className="text-text-dim">confluence</span>
                            <span className="text-amber">{conf.toFixed(2)}</span>
                          </div>
                        )}
                        {ind && (
                          <div className="flex items-center justify-between text-[10px] font-mono">
                            <span className="text-text-dim">overlays</span>
                            <TVIndicatorBadge reading={ind} expanded />
                          </div>
                        )}
                        {ind?.source && (
                          <div className="flex items-baseline justify-between text-[10px] font-mono">
                            <span className="text-text-dim">source</span>
                            <span className="text-text-muted truncate ml-1">{ind.source}</span>
                          </div>
                        )}
                        {!marketSnapshot[id] && !conf && !ind && (
                          <div className="text-[10px] text-text-dim italic">
                            No additional signals for this node.
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          {/* ── Confluence ────────────────────────────────────────────── */}
          {Object.keys(confluence).length > 0 && (
            <div>
              <span className="text-[10px] text-text-dim uppercase tracking-widest block mb-0.5">
                Confluence
              </span>
              {Object.entries(confluence)
                .sort(([, a], [, b]) => b - a)
                .map(([id, score]) => (
                  <div key={id} className="flex items-center gap-1.5 py-px">
                    <span className="text-[11px] font-mono w-24 truncate" title={id}>
                      {id}
                    </span>
                    <div
                      className="flex-1 h-1 bg-elevated rounded-sm overflow-hidden"
                      role="meter"
                      aria-valuenow={score}
                      aria-valuemin={0}
                      aria-valuemax={maxConf}
                      aria-label={`Confluence ${score.toFixed(2)} for ${id}`}
                    >
                      <div
                        className={`h-full rounded-sm ${
                          score >= 2 ? "bg-danger" : score >= 1.5 ? "bg-amber" : "bg-teal"
                        }`}
                        style={{ width: `${(score / maxConf) * 100}%` }}
                      />
                    </div>
                    <span className="text-[11px] font-mono text-amber w-8 text-right tabular-nums">
                      {score.toFixed(2)}
                    </span>
                  </div>
                ))}
            </div>
          )}

          {/* ── Countdowns / Deadlines ───────────────────────────────── */}
          {sortedCountdowns.length > 0 && (
            <div>
              <span className="text-[10px] text-text-dim uppercase tracking-widest block mb-0.5">
                Deadlines
              </span>
              {sortedCountdowns.map((cd) => (
                <div
                  key={cd.nodeId}
                  className="flex items-center justify-between py-px px-1 hover:bg-elevated/50 rounded-sm"
                >
                  <span
                    className="text-[11px] font-mono truncate mr-2"
                    title={cd.nodeId}
                  >
                    {cd.label || cd.nodeId}
                  </span>
                  <span
                    className={`text-[11px] font-mono font-bold tabular-nums ${countdownClass(cd.daysRemaining)}`}
                  >
                    {formatDays(cd.daysRemaining)}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* ── Scenarios (sorted by EV) ─────────────────────────────── */}
          {sortedScenarios.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] text-text-dim uppercase tracking-widest">
                  Scenarios
                </span>
                <span className="text-[8px] text-text-dim font-mono uppercase tracking-wide">
                  prob × impact = ev
                </span>
              </div>
              <div className="space-y-0.5">
                {sortedScenarios.map((s) => {
                  const positive = s.impact >= 0;
                  const widthPct = Math.min(100, (Math.abs(s.impact) / maxScenarioImpact) * 100);
                  return (
                    <div
                      key={s.id}
                      className="px-1 py-0.5 hover:bg-elevated/50 rounded-sm"
                      title={`P=${(s.prob * 100).toFixed(0)}% · impact=${s.impact.toFixed(1)} · EV=${s.ev.toFixed(2)}`}
                    >
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-[11px] font-mono truncate flex-1">
                          {s.id}
                        </span>
                        <span className="text-[9px] font-mono text-text-dim tabular-nums">
                          {(s.prob * 100).toFixed(0)}%
                        </span>
                        <span
                          className={`text-[11px] font-mono font-bold tabular-nums w-10 text-right ${
                            positive ? "text-teal" : "text-danger"
                          }`}
                        >
                          {positive ? "+" : ""}
                          {s.impact.toFixed(1)}
                        </span>
                      </div>
                      {/* Mini impact bar — width = |impact|/max, color = sign. */}
                      <div className="h-0.5 bg-elevated/60 rounded-sm overflow-hidden mt-0.5">
                        <div
                          className={`h-full ${positive ? "bg-teal/70" : "bg-danger/70"}`}
                          style={{ width: `${widthPct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
