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
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs text-text-dim font-medium uppercase tracking-wider">Morning Brief</h3>
        <button onClick={loadBrief} className="text-text-dim hover:text-amber p-1" disabled={loading}>
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
        </button>
      </div>
      <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap bg-elevated rounded p-3 overflow-y-auto max-h-[calc(100vh-160px)]">
        {loading ? "Loading..." : brief}
      </pre>
    </div>
  );
}
