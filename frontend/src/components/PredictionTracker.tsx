import { useState, useEffect, type FormEvent } from "react";
import { Plus, Check, X } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { Prediction } from "../lib/types";

export default function PredictionTracker() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [statement, setStatement] = useState("");
  const [confidence, setConfidence] = useState("0.7");
  const [deadline, setDeadline] = useState("");

  useEffect(() => { load(); }, []);

  async function load() {
    try { setPredictions(await apiFetch<Prediction[]>("/api/predictions")); } catch {
      console.error("Failed to load predictions");
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!statement.trim() || !deadline) return;
    await apiFetch("/api/predictions", {
      method: "POST",
      body: JSON.stringify({ statement: statement.trim(), confidence: parseFloat(confidence), deadline }),
    });
    setShowForm(false); setStatement(""); setConfidence("0.7"); setDeadline("");
    load();
  }

  async function resolve(id: string, resolution: "correct" | "incorrect") {
    await apiFetch(`/api/predictions/${id}/resolve`, {
      method: "POST", body: JSON.stringify({ resolution }),
    });
    load();
  }

  const open = predictions.filter((p) => !p.resolution);
  const resolved = predictions.filter((p) => p.resolution);
  const accuracy = resolved.length > 0
    ? (resolved.filter((p) => p.resolution === "correct").length / resolved.length * 100) : 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">Predictions</span>
        <button onClick={() => setShowForm(!showForm)} className="text-text-dim hover:text-amber">
          <Plus size={12} />
        </button>
      </div>

      {resolved.length > 0 && (
        <div className="flex items-center gap-2 mb-1 text-[10px] font-mono">
          <span className="text-text-dim">accuracy:</span>
          <span className="text-amber font-bold">{accuracy.toFixed(0)}%</span>
          <span className="text-text-dim">({resolved.length})</span>
        </div>
      )}

      {showForm && (
        <form onSubmit={create} className="card mb-1.5 space-y-1">
          <input className="input w-full" placeholder="Prediction statement" value={statement} onChange={(e) => setStatement(e.target.value)} autoFocus />
          <div className="flex gap-1">
            <input className="input w-14" type="number" min="0" max="1" step="0.05" value={confidence} onChange={(e) => setConfidence(e.target.value)} />
            <input className="input flex-1" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
          </div>
          <button className="btn-primary w-full" type="submit">Add</button>
        </form>
      )}

      {open.length === 0 && !showForm && (
        <span className="text-[10px] text-text-dim font-mono">No open predictions. Click + to add.</span>
      )}

      <div className="space-y-0.5">
        {open.map((p) => (
          <div key={p.id} className="card">
            <p className="text-[11px] text-text-primary leading-tight mb-0.5">{p.statement}</p>
            <div className="flex items-center justify-between">
              <div className="flex gap-2 text-[10px] font-mono text-text-dim">
                <span className="text-amber">{(p.confidence * 100).toFixed(0)}%</span>
                <span>by {p.deadline}</span>
              </div>
              <div className="flex gap-0.5">
                <button onClick={() => resolve(p.id, "correct")} className="p-0.5 text-teal hover:text-teal-dim" title="Correct"><Check size={11} /></button>
                <button onClick={() => resolve(p.id, "incorrect")} className="p-0.5 text-danger" title="Incorrect"><X size={11} /></button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
