import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { ThesisBook, ThesisState } from "../lib/types";

interface Props {
  bookId: string | null;
  books: ThesisBook[];
}

const PHASE_NAMES: Record<number, string> = {
  1: "Shock",
  2: "Transmission",
  3: "Amplification",
  4: "Policy Response",
  5: "Resolution",
};

function stateBadgeClass(state: string): string {
  switch (state) {
    case "fired": return "badge-fired";
    case "approaching": return "badge-approaching";
    case "stable": return "badge-stable";
    default: return "badge-monitoring";
  }
}

export default function ThesisViewer({ bookId, books }: Props) {
  const [selectedBook, setSelectedBook] = useState(bookId || "");
  const [state, setState] = useState<ThesisState | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (bookId && !selectedBook) setSelectedBook(bookId);
  }, [bookId, selectedBook]);

  useEffect(() => {
    if (!selectedBook) return;
    setLoading(true);
    apiFetch<ThesisState>(`/api/thesis/${selectedBook}/state`)
      .then(setState)
      .catch(() => setState(null))
      .finally(() => setLoading(false));
  }, [selectedBook]);

  function refresh() {
    if (!selectedBook) return;
    setLoading(true);
    apiFetch<ThesisState>(`/api/thesis/${selectedBook}/state`)
      .then(setState)
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  if (!state && !loading) {
    return (
      <div>
        <h3 className="text-xs text-text-dim font-medium uppercase tracking-wider mb-2">Thesis State</h3>
        <select
          className="input w-full text-xs mb-2"
          value={selectedBook}
          onChange={(e) => setSelectedBook(e.target.value)}
        >
          <option value="">Select book</option>
          {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
        </select>
        <p className="text-text-dim text-xs">No data</p>
      </div>
    );
  }

  const phase = state?.cascadePhase;
  const nodeStates = state?.nodeStates || {};
  const confluence = state?.confluenceScores || {};
  const countdowns = state?.countdowns || [];
  const scenarios = state?.scenarioImpacts || {};

  // Sort nodes: fired first, then approaching, then rest
  const sortedNodes = Object.entries(nodeStates).sort(([, a], [, b]) => {
    const order: Record<string, number> = { fired: 0, approaching: 1, stable: 2, monitoring: 3 };
    return (order[a] ?? 4) - (order[b] ?? 4);
  });

  const maxConf = Math.max(...Object.values(confluence), 1);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs text-text-dim font-medium uppercase tracking-wider">Thesis State</h3>
        <button onClick={refresh} className="text-text-dim hover:text-amber p-1" disabled={loading}>
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <select
        className="input w-full text-xs"
        value={selectedBook}
        onChange={(e) => setSelectedBook(e.target.value)}
      >
        {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
      </select>

      {state && (
        <>
          {/* Phase indicator */}
          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs text-text-muted">Phase</span>
              <span className={`text-xs font-mono ${phase?.status === "ACTIVE" ? "text-danger" : "text-amber"}`}>
                {phase?.status}
              </span>
            </div>
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <div
                  key={n}
                  className={`h-1.5 flex-1 rounded-full ${
                    n <= (phase?.number || 0)
                      ? n <= 2 ? "bg-amber" : n <= 3 ? "bg-danger" : "bg-teal"
                      : "bg-elevated"
                  }`}
                />
              ))}
            </div>
            <p className="text-sm font-medium mt-1">
              Phase {phase?.number}: {PHASE_NAMES[phase?.number || 0] || "?"}
            </p>
          </div>

          {/* Node states */}
          <div>
            <h4 className="text-xs text-text-dim mb-1">Nodes ({sortedNodes.length})</h4>
            <div className="space-y-0.5">
              {sortedNodes.map(([id, st]) => (
                <div key={id} className="flex items-center justify-between py-0.5">
                  <span className="text-xs font-mono truncate mr-2">{id}</span>
                  <span className={stateBadgeClass(st)}>{st}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Confluence scores */}
          {Object.keys(confluence).length > 0 && (
            <div>
              <h4 className="text-xs text-text-dim mb-1">Confluence</h4>
              {Object.entries(confluence)
                .sort(([, a], [, b]) => b - a)
                .map(([id, score]) => (
                  <div key={id} className="flex items-center gap-2 py-0.5">
                    <span className="text-xs font-mono w-28 truncate">{id}</span>
                    <div className="flex-1 h-1.5 bg-elevated rounded-full overflow-hidden">
                      <div
                        className="h-full bg-amber rounded-full"
                        style={{ width: `${(score / maxConf) * 100}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono text-amber w-8 text-right">{score.toFixed(1)}</span>
                  </div>
                ))}
            </div>
          )}

          {/* Countdowns */}
          {countdowns.length > 0 && (
            <div>
              <h4 className="text-xs text-text-dim mb-1">Deadlines</h4>
              {countdowns.map((cd) => (
                <div key={cd.nodeId} className="flex items-center justify-between py-0.5">
                  <span className="text-xs font-mono">{cd.label || cd.nodeId}</span>
                  <span className={`text-xs font-mono font-medium ${
                    cd.daysRemaining <= 7 ? "text-danger" : cd.daysRemaining <= 14 ? "text-amber" : "text-text-muted"
                  }`}>
                    {cd.daysRemaining}d
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Scenarios */}
          {Object.keys(scenarios).length > 0 && (
            <div>
              <h4 className="text-xs text-text-dim mb-1">Scenarios</h4>
              {Object.entries(scenarios).map(([id, s]) => (
                <div key={id} className="card mb-1">
                  <div className="flex justify-between items-baseline">
                    <span className="text-xs font-mono">{id}</span>
                    <span className={`text-xs font-mono font-medium ${
                      (s.netImpact || 0) >= 0 ? "text-teal" : "text-danger"
                    }`}>
                      {(s.netImpact || 0) >= 0 ? "+" : ""}{s.netImpact?.toFixed(1)}
                    </span>
                  </div>
                  <div className="text-xs text-text-dim">
                    P={((s.probability || 0) * 100).toFixed(0)}%
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
