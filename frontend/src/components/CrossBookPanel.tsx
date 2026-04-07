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
    } catch { setResult(null); } finally { setLoading(false); }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">Cross-Book</span>
        <button onClick={load} className="text-text-dim hover:text-amber p-0.5" disabled={loading}>
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {result && (
        <span className="text-[10px] text-text-dim font-mono block mb-1">
          {result.books_analyzed.length} books / {result.flags.length} flags
        </span>
      )}

      {result?.flags.length === 0 && (
        <span className="text-[10px] text-text-dim font-mono">No flags.</span>
      )}

      <div className="space-y-1">
        {result?.flags.map((flag: CrossBookFlag, i: number) => (
          <div key={i} className="card">
            <div className="flex items-start gap-1.5">
              <AlertTriangle size={11} className={`shrink-0 mt-0.5 ${
                flag.severity === "HIGH" ? "text-danger" : flag.severity === "MEDIUM" ? "text-amber" : "text-teal"
              }`} />
              <div className="min-w-0">
                <div className="flex items-center gap-1 mb-0.5">
                  <span className={severityBadge(flag.severity)}>{flag.severity}</span>
                  <span className="text-[10px] font-mono text-text-dim">{flag.flag_type}</span>
                </div>
                <p className="text-[11px] text-text-primary leading-tight">{flag.detail}</p>
                <p className="text-[10px] text-text-dim font-mono mt-0.5">{flag.books.join(", ")}</p>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
