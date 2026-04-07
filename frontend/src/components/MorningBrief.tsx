import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { apiFetch } from "../lib/api";

export default function MorningBrief() {
  const [brief, setBrief] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => { loadBrief(); }, []);

  async function loadBrief() {
    setLoading(true);
    try {
      const data = await apiFetch<{ brief: string }>("/api/outcomes/brief");
      setBrief(data.brief);
    } catch {
      setBrief("Failed to load brief.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">Morning Brief</span>
        <button onClick={loadBrief} className="text-text-dim hover:text-amber p-0.5" disabled={loading}>
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <pre className="text-[11px] font-mono text-text-primary whitespace-pre-wrap bg-elevated rounded p-2 overflow-y-auto max-h-[calc(100vh-120px)] leading-tight">
        {loading ? "loading..." : brief}
      </pre>
    </div>
  );
}
