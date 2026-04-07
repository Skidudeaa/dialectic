import { useState, useEffect } from "react";
import { RefreshCw, AlertTriangle } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { CrossBookResult, CrossBookFlag } from "../lib/types";

function severityBadge(severity: string): string {
  switch (severity) {
    case "HIGH": return "badge-high";
    case "MEDIUM": return "badge-medium";
    case "LOW": return "badge-low";
    default: return "badge-monitoring";
  }
}

export default function CrossBookPanel() {
  const [result, setResult] = useState<CrossBookResult | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const data = await apiFetch<CrossBookResult>("/api/outcomes/cross-book");
      setResult(data);
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs text-text-dim font-medium uppercase tracking-wider">Cross-Book Scan</h3>
        <button onClick={load} className="text-text-dim hover:text-amber p-1" disabled={loading}>
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {result && (
        <p className="text-xs text-text-dim mb-2">
          {result.books_analyzed.length} books analyzed
        </p>
      )}

      {result?.flags.length === 0 && (
        <p className="text-xs text-text-dim">No cross-book flags detected.</p>
      )}

      <div className="space-y-2">
        {result?.flags.map((flag: CrossBookFlag, i: number) => (
          <div key={i} className="card">
            <div className="flex items-start gap-2">
              <AlertTriangle
                size={14}
                className={`shrink-0 mt-0.5 ${
                  flag.severity === "HIGH" ? "text-danger" :
                  flag.severity === "MEDIUM" ? "text-amber" : "text-teal"
                }`}
              />
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={severityBadge(flag.severity)}>{flag.severity}</span>
                  <span className="text-xs font-mono text-text-muted">{flag.flag_type}</span>
                </div>
                <p className="text-xs text-text-primary">{flag.detail}</p>
                <p className="text-xs text-text-dim mt-0.5">
                  Books: {flag.books.join(", ")}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
