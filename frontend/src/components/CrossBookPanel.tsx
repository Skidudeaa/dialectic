import { useState, useEffect, useMemo } from "react";
import { RefreshCw, AlertTriangle, ShieldCheck, ChevronDown, ChevronRight } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { CrossBookResult, CrossBookFlag } from "../lib/types";

const SEVERITY_RANK: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };

// flag_type heuristics — recession-aligned & shared market signals are highest value
const RECESSION_TYPES = /recession|contraction|drawdown|unemployment|rate-cut/i;
const SHARED_MARKET_TYPES = /shared-market|correlated|confluence|phase-align/i;

function severityClass(sev: string, type: string): string {
  if (sev === "HIGH" || RECESSION_TYPES.test(type)) return "badge-high";
  if (sev === "MEDIUM" || SHARED_MARKET_TYPES.test(type)) return "badge-medium";
  if (sev === "LOW") return "badge-low";
  return "badge-monitoring";
}

function flagAccent(sev: string, type: string): string {
  if (sev === "HIGH" || RECESSION_TYPES.test(type)) return "border-l-2 border-danger";
  if (sev === "MEDIUM") return "border-l-2 border-amber";
  if (sev === "LOW") return "border-l-2 border-teal";
  return "border-l-2 border-border";
}

function iconColor(sev: string, type: string): string {
  if (sev === "HIGH" || RECESSION_TYPES.test(type)) return "text-danger";
  if (sev === "MEDIUM") return "text-amber";
  if (sev === "LOW") return "text-teal";
  return "text-text-dim";
}

function bookShort(id: string): string {
  // iran-hormuz-graph -> hormuz; trump-tariffs-graph -> tariffs
  return id
    .replace(/-graph$/, "")
    .split("-")
    .slice(-1)[0];
}

function freshness(ts: string | null): string {
  if (!ts) return "";
  const when = new Date(ts);
  if (Number.isNaN(when.getTime())) return "";
  const sec = Math.floor((Date.now() - when.getTime()) / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

export default function CrossBookPanel() {
  const [result, setResult] = useState<CrossBookResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<CrossBookResult>("/api/outcomes/cross-book");
      setResult(data);
      setExpanded(new Set());
    } catch {
      setError("Failed to load cross-book scan");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function toggle(i: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  const sortedFlags = useMemo(() => {
    if (!result) return [];
    return [...result.flags].sort((a, b) => {
      const sevA = SEVERITY_RANK[a.severity] ?? 99;
      const sevB = SEVERITY_RANK[b.severity] ?? 99;
      if (sevA !== sevB) return sevA - sevB;
      // Recession-aligned first within severity
      const recA = RECESSION_TYPES.test(a.flag_type) ? 0 : 1;
      const recB = RECESSION_TYPES.test(b.flag_type) ? 0 : 1;
      return recA - recB;
    });
  }, [result]);

  const counts = useMemo(() => {
    if (!result) return { HIGH: 0, MEDIUM: 0, LOW: 0 };
    const c = { HIGH: 0, MEDIUM: 0, LOW: 0 } as Record<string, number>;
    for (const f of result.flags) {
      c[f.severity] = (c[f.severity] ?? 0) + 1;
    }
    return c;
  }, [result]);

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          Cross-Book
        </span>
        <div className="flex items-center gap-1">
          {result && (
            <span
              className="text-[9px] text-text-dim font-mono"
              title={result.timestamp}
            >
              {freshness(result.timestamp)} ago
            </span>
          )}
          <button
            onClick={load}
            className="text-text-dim hover:text-amber p-0.5"
            disabled={loading}
            title="Re-scan"
            aria-label="Re-scan cross-book"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {result && (
        <div className="flex items-center gap-2 mb-1 text-[10px] font-mono text-text-dim px-0.5">
          <span>{result.books_analyzed.length} books</span>
          <span>·</span>
          {counts.HIGH > 0 && (
            <span className="text-danger font-bold">{counts.HIGH} high</span>
          )}
          {counts.MEDIUM > 0 && (
            <span className="text-amber">{counts.MEDIUM} med</span>
          )}
          {counts.LOW > 0 && <span className="text-teal">{counts.LOW} low</span>}
          {result.flags.length === 0 && <span>0 flags</span>}
        </div>
      )}

      {error && (
        <div className="text-[10px] text-danger font-mono mb-1 px-1">
          {error}{" "}
          <button onClick={load} className="underline hover:text-amber">
            retry
          </button>
        </div>
      )}

      {loading && !result && (
        <div className="space-y-1">
          {[0, 1].map((i) => (
            <div key={i} className="card animate-pulse h-12 bg-elevated/30" />
          ))}
        </div>
      )}

      {result && result.flags.length === 0 && !loading && (
        <div className="card flex flex-col items-center text-center py-3 gap-1">
          <ShieldCheck size={18} className="text-teal" />
          <p className="text-[11px] text-text-primary leading-tight">
            No cross-book correlations detected.
          </p>
          <p className="text-[10px] text-text-dim leading-tight max-w-[220px]">
            That's normal. Theses don't usually align — when they do (shared markets,
            simultaneous cascades), it's a signal.
          </p>
        </div>
      )}

      <div className="space-y-1">
        {sortedFlags.map((flag: CrossBookFlag, i: number) => {
          const isOpen = expanded.has(i);
          const hasData = flag.data && Object.keys(flag.data).length > 0;
          return (
            <div key={i} className={`card ${flagAccent(flag.severity, flag.flag_type)}`}>
              <div className="flex items-start gap-1.5">
                <AlertTriangle
                  size={11}
                  className={`shrink-0 mt-0.5 ${iconColor(flag.severity, flag.flag_type)}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1 mb-0.5 flex-wrap">
                    <span className={severityClass(flag.severity, flag.flag_type)}>
                      {flag.severity}
                    </span>
                    <span className="text-[9px] font-mono text-text-dim">
                      {flag.flag_type}
                    </span>
                  </div>
                  <p className="text-[11px] text-text-primary leading-tight">
                    {flag.detail}
                  </p>
                  <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                    {flag.books.map((b) => (
                      <span
                        key={b}
                        className="text-[9px] font-mono text-purple/90 bg-purple/10 px-1 rounded"
                        title={b}
                      >
                        {bookShort(b)}
                      </span>
                    ))}
                  </div>
                  {hasData && (
                    <button
                      onClick={() => toggle(i)}
                      className="flex items-center gap-0.5 text-[9px] text-text-dim hover:text-amber font-mono mt-1"
                    >
                      {isOpen ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
                      {isOpen ? "hide" : "linkage data"}
                    </button>
                  )}
                  {isOpen && hasData && (
                    <pre className="text-[9px] font-mono text-text-muted bg-void/50 rounded p-1 mt-1 overflow-x-auto whitespace-pre-wrap leading-tight max-h-32 overflow-y-auto">
                      {JSON.stringify(flag.data, null, 2)}
                    </pre>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
