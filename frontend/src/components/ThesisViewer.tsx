import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { ThesisBook, ThesisState } from "../lib/types";

interface Props {
  bookId: string | null;
  books: ThesisBook[];
}

const PHASE_NAMES: Record<number, string> = {
  1: "Shock", 2: "Transmission", 3: "Amplification", 4: "Policy Response", 5: "Resolution",
};

function stateBadgeClass(state: string): string {
  switch (state) {
    case "fired": return "badge-fired";
    case "approaching": return "badge-approaching";
    case "stable": return "badge-stable";
    case "gated": return "badge-gated";
    default: return "badge-monitoring";
  }
}

export default function ThesisViewer({ bookId, books }: Props) {
  const [selectedBook, setSelectedBook] = useState(bookId || "");
  const [state, setState] = useState<ThesisState | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { if (bookId && !selectedBook) setSelectedBook(bookId); }, [bookId, selectedBook]);

  useEffect(() => {
    if (!selectedBook) return;
    setLoading(true);
    apiFetch<ThesisState>(`/api/thesis/${selectedBook}/state`)
      .then(setState).catch(() => setState(null)).finally(() => setLoading(false));
    // WHY: Auto-refresh every 5 minutes to catch state changes from pipeline runs.
    const interval = setInterval(() => {
      apiFetch<ThesisState>(`/api/thesis/${selectedBook}/state`)
        .then(setState).catch(() => {});
    }, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [selectedBook]);

  const phase = state?.cascadePhase;
  const nodeStates = state?.nodeStates || {};
  const confluence = state?.confluenceScores || {};
  const countdowns = state?.countdowns || [];
  const scenarios = state?.scenarioImpacts || {};

  const sortedNodes = Object.entries(nodeStates).sort(([, a], [, b]) => {
    const order: Record<string, number> = { fired: 0, approaching: 1, stable: 2, gated: 3, monitoring: 4 };
    return (order[a] ?? 5) - (order[b] ?? 5);
  });

  const maxConf = Math.max(...Object.values(confluence), 1);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">Thesis</span>
        <button onClick={() => { if (selectedBook) { setLoading(true); apiFetch(`/api/thesis/${selectedBook}/state`).then(setState as any).catch(() => {}).finally(() => setLoading(false)); }}} className="text-text-dim hover:text-amber p-0.5" disabled={loading}>
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <select className="input w-full" value={selectedBook} onChange={(e) => setSelectedBook(e.target.value)}>
        {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
      </select>

      {state && (
        <>
          {/* Phase */}
          <div className="card">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-text-dim">CASCADE</span>
              <span className={`text-[10px] font-mono font-bold ${(phase?.number || 0) >= 3 ? "text-danger" : "text-amber"}`}>
                {phase?.status}
              </span>
            </div>
            <div className="flex items-center gap-0.5 my-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <div key={n} className={`h-1 flex-1 rounded-sm ${
                  n <= (phase?.number || 0) ? n <= 2 ? "bg-amber" : n <= 3 ? "bg-danger" : "bg-teal" : "bg-elevated"
                }`} />
              ))}
            </div>
            <span className="text-xs font-mono font-medium">
              {phase?.number}. {PHASE_NAMES[phase?.number || 0]}
            </span>
          </div>

          {/* Nodes */}
          <div>
            <span className="text-[10px] text-text-dim block mb-0.5">NODES ({sortedNodes.length})</span>
            <div className="space-y-px">
              {sortedNodes.map(([id, st]) => (
                <div key={id} className="flex items-center justify-between py-px hover:bg-elevated/50 px-1 rounded-sm">
                  <span className="text-[11px] font-mono truncate mr-2">{id}</span>
                  <span className={stateBadgeClass(st)}>{st}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Confluence */}
          {Object.keys(confluence).length > 0 && (
            <div>
              <span className="text-[10px] text-text-dim block mb-0.5">CONFLUENCE</span>
              {Object.entries(confluence).sort(([, a], [, b]) => b - a).map(([id, score]) => (
                <div key={id} className="flex items-center gap-1.5 py-px">
                  <span className="text-[11px] font-mono w-24 truncate">{id}</span>
                  <div className="flex-1 h-1 bg-elevated rounded-sm overflow-hidden">
                    <div className={`h-full rounded-sm ${score >= 2 ? "bg-danger" : score >= 1.5 ? "bg-amber" : "bg-teal"}`} style={{ width: `${(score / maxConf) * 100}%` }} />
                  </div>
                  <span className="text-[11px] font-mono text-amber w-6 text-right">{score.toFixed(1)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Countdowns */}
          {countdowns.length > 0 && (
            <div>
              <span className="text-[10px] text-text-dim block mb-0.5">DEADLINES</span>
              {countdowns.map((cd) => (
                <div key={cd.nodeId} className="flex items-center justify-between py-px">
                  <span className="text-[11px] font-mono">{cd.label || cd.nodeId}</span>
                  <span className={`text-[11px] font-mono font-bold ${cd.daysRemaining <= 7 ? "text-danger" : cd.daysRemaining <= 14 ? "text-amber" : "text-text-muted"}`}>
                    {cd.daysRemaining}d
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Scenarios */}
          {Object.keys(scenarios).length > 0 && (
            <div>
              <span className="text-[10px] text-text-dim block mb-0.5">SCENARIOS</span>
              <div className="space-y-0.5">
                {Object.entries(scenarios).map(([id, s]) => (
                  <div key={id} className="flex items-center justify-between py-px px-1 hover:bg-elevated/50 rounded-sm">
                    <span className="text-[11px] font-mono truncate mr-1">{id}</span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-[10px] font-mono text-text-dim">{((s.probability || 0) * 100).toFixed(0)}%</span>
                      <span className={`text-[11px] font-mono font-bold ${(s.netImpact || 0) >= 0 ? "text-teal" : "text-danger"}`}>
                        {(s.netImpact || 0) >= 0 ? "+" : ""}{(s.netImpact || 0).toFixed(1)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
