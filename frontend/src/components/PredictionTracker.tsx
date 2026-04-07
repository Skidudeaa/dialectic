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
    try {
      const data = await apiFetch<Prediction[]>("/api/predictions");
      setPredictions(data);
    } catch { /* ignore */ }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!statement.trim() || !deadline) return;
    try {
      await apiFetch("/api/predictions", {
        method: "POST",
        body: JSON.stringify({
          statement: statement.trim(),
          confidence: parseFloat(confidence),
          deadline,
        }),
      });
      setShowForm(false);
      setStatement("");
      setConfidence("0.7");
      setDeadline("");
      load();
    } catch { /* ignore */ }
  }

  async function resolve(id: string, resolution: "correct" | "incorrect") {
    try {
      await apiFetch(`/api/predictions/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ resolution }),
      });
      load();
    } catch { /* ignore */ }
  }

  const open = predictions.filter((p) => !p.resolution);
  const resolved = predictions.filter((p) => p.resolution);
  const accuracy = resolved.length > 0
    ? (resolved.filter((p) => p.resolution === "correct").length / resolved.length * 100)
    : 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs text-text-dim font-medium uppercase tracking-wider">Predictions</h3>
        <button onClick={() => setShowForm(!showForm)} className="text-text-muted hover:text-amber">
          <Plus size={14} />
        </button>
      </div>

      {resolved.length > 0 && (
        <div className="card mb-2">
          <span className="text-xs text-text-dim">Accuracy:</span>
          <span className="text-sm font-mono text-amber ml-1">{accuracy.toFixed(0)}%</span>
          <span className="text-xs text-text-dim ml-1">({resolved.length} resolved)</span>
        </div>
      )}

      {showForm && (
        <form onSubmit={create} className="card mb-2 space-y-2">
          <input className="input w-full text-xs" placeholder="Prediction statement" value={statement} onChange={(e) => setStatement(e.target.value)} autoFocus />
          <div className="flex gap-2">
            <input className="input w-20 text-xs" type="number" min="0" max="1" step="0.05" value={confidence} onChange={(e) => setConfidence(e.target.value)} />
            <input className="input flex-1 text-xs" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
          </div>
          <button className="btn-primary text-xs w-full" type="submit">Add</button>
        </form>
      )}

      <div className="space-y-1">
        {open.map((p) => (
          <div key={p.id} className="card">
            <p className="text-xs text-text-primary mb-1">{p.statement}</p>
            <div className="flex items-center justify-between">
              <div className="flex gap-2 text-xs text-text-dim">
                <span className="font-mono">{(p.confidence * 100).toFixed(0)}%</span>
                <span>by {p.deadline}</span>
              </div>
              <div className="flex gap-1">
                <button onClick={() => resolve(p.id, "correct")} className="p-0.5 text-teal hover:text-teal-dim" title="Correct">
                  <Check size={13} />
                </button>
                <button onClick={() => resolve(p.id, "incorrect")} className="p-0.5 text-danger hover:text-red-300" title="Incorrect">
                  <X size={13} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
