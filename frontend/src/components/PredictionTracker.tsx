import { useState, useEffect, useMemo, type FormEvent } from "react";
import { Plus, Check, X, Minus, Target } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { Prediction } from "../lib/types";

type Resolution = "correct" | "incorrect" | "partial";

const MS_PER_DAY = 86_400_000;

function daysUntil(deadline: string): number {
  const d = new Date(deadline);
  if (Number.isNaN(d.getTime())) return Number.POSITIVE_INFINITY;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((d.getTime() - today.getTime()) / MS_PER_DAY);
}

function deadlineColor(days: number): string {
  if (days < 0) return "text-danger";
  if (days <= 1) return "text-danger";
  if (days <= 3) return "text-amber";
  return "text-text-dim";
}

function resolutionBadge(res: string | null): string {
  if (res === "correct") return "bg-teal/20 text-teal";
  if (res === "incorrect") return "bg-danger/20 text-danger";
  if (res === "partial") return "bg-amber/20 text-amber";
  return "bg-elevated text-text-dim";
}

export default function PredictionTracker() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [statement, setStatement] = useState("");
  const [confidence, setConfidence] = useState("0.7");
  const [deadline, setDeadline] = useState("");
  const [showOptional, setShowOptional] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showResolved, setShowResolved] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setError(null);
      const data = await apiFetch<Prediction[]>("/api/predictions");
      setPredictions(data);
      setLastUpdated(new Date());
    } catch {
      setError("Failed to load predictions");
    } finally {
      setLoading(false);
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!statement.trim() || !deadline) return;
    setSubmitting(true);
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
      setShowOptional(false);
      await load();
    } catch {
      setError("Failed to create prediction");
    } finally {
      setSubmitting(false);
    }
  }

  async function resolve(id: string, resolution: Resolution) {
    try {
      await apiFetch(`/api/predictions/${id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ resolution }),
      });
      await load();
    } catch {
      setError("Resolve failed");
    }
  }

  const { open, resolved, accuracy, brierLike } = useMemo(() => {
    const o = predictions
      .filter((p) => !p.resolution)
      .sort((a, b) => daysUntil(a.deadline) - daysUntil(b.deadline));
    const r = predictions
      .filter((p) => p.resolution)
      .sort((a, b) => (b.resolved_at ?? "").localeCompare(a.resolved_at ?? ""));
    const correct = r.filter((p) => p.resolution === "correct").length;
    const partial = r.filter((p) => p.resolution === "partial").length;
    const acc = r.length > 0 ? ((correct + 0.5 * partial) / r.length) * 100 : 0;
    // Brier-like calibration sample: avg |confidence - outcome|
    const cal =
      r.length > 0
        ? r.reduce((sum, p) => {
            const outcome =
              p.resolution === "correct" ? 1 : p.resolution === "partial" ? 0.5 : 0;
            return sum + Math.abs((p.confidence ?? 0.5) - outcome);
          }, 0) / r.length
        : null;
    return { open: o, resolved: r, accuracy: acc, brierLike: cal };
  }, [predictions]);

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          Predictions
        </span>
        <div className="flex items-center gap-1">
          {lastUpdated && (
            <span
              className="text-[9px] text-text-dim font-mono"
              title={lastUpdated.toLocaleString()}
            >
              {lastUpdated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <button
            onClick={() => {
              setShowForm((v) => !v);
              setShowOptional(false);
            }}
            className="text-text-dim hover:text-amber"
            title="Add prediction"
            aria-label="Add prediction"
          >
            <Plus size={12} />
          </button>
        </div>
      </div>

      {(resolved.length > 0 || open.length > 0) && (
        <div className="flex items-center gap-2 mb-1 text-[10px] font-mono">
          <span className="text-text-dim">acc:</span>
          <span className="text-amber font-bold">
            {resolved.length > 0 ? `${accuracy.toFixed(0)}%` : "--"}
          </span>
          <span className="text-text-dim">
            ({resolved.filter((p) => p.resolution === "correct").length}/{resolved.length})
          </span>
          {brierLike !== null && (
            <span className="text-text-dim ml-auto" title="Mean |confidence - outcome|">
              cal {brierLike.toFixed(2)}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="text-[10px] text-danger font-mono mb-1 px-1">{error}</div>
      )}

      {showForm && (
        <form onSubmit={create} className="card mb-1.5 space-y-1">
          <input
            className="input w-full"
            placeholder="USD/JPY breaks 152 by Friday"
            value={statement}
            onChange={(e) => setStatement(e.target.value)}
            autoFocus
            required
          />
          <div className="flex gap-1">
            <input
              className="input flex-1"
              type="date"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
              required
              title="Deadline"
            />
            <button
              type="button"
              onClick={() => setShowOptional((v) => !v)}
              className="btn-secondary text-[10px]"
              title="Optional fields"
            >
              {showOptional ? "less" : "more"}
            </button>
          </div>
          {showOptional && (
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-text-dim font-mono w-16">conf</span>
              <input
                className="input w-16"
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={confidence}
                onChange={(e) => setConfidence(e.target.value)}
              />
              <input
                className="input flex-1"
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={confidence}
                onChange={(e) => setConfidence(e.target.value)}
              />
            </div>
          )}
          <div className="flex gap-1">
            <button className="btn-primary flex-1" type="submit" disabled={submitting}>
              {submitting ? "..." : "Add"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setShowForm(false);
                setShowOptional(false);
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {loading && (
        <div className="space-y-0.5">
          {[0, 1].map((i) => (
            <div key={i} className="card animate-pulse h-10 bg-elevated/30" />
          ))}
        </div>
      )}

      {!loading && open.length === 0 && resolved.length === 0 && !showForm && (
        <div className="card flex flex-col items-center text-center py-3 gap-1">
          <Target size={18} className="text-text-dim" />
          <p className="text-[11px] text-text-primary leading-tight">
            Track your forecasts.
          </p>
          <p className="text-[10px] text-text-dim leading-tight max-w-[200px]">
            Calibration compounds. Log a call, set a deadline, resolve it later — see where
            you're sharp and where you're not.
          </p>
          <button
            onClick={() => setShowForm(true)}
            className="btn-primary mt-1 text-[10px]"
          >
            First prediction
          </button>
        </div>
      )}

      {open.length > 0 && (
        <div className="space-y-0.5">
          {open.map((p) => {
            const days = daysUntil(p.deadline);
            const overdue = days < 0;
            const urgent = days >= 0 && days <= 1;
            return (
              <div
                key={p.id}
                className={`card ${urgent ? "ring-1 ring-amber/40 animate-pulse" : ""} ${
                  overdue ? "ring-1 ring-danger/40" : ""
                }`}
              >
                <p className="text-[11px] text-text-primary leading-tight mb-0.5">
                  {p.statement}
                </p>
                <div className="flex items-center justify-between gap-1">
                  <div className="flex gap-2 text-[10px] font-mono text-text-dim min-w-0">
                    <span className="text-amber shrink-0">
                      {(p.confidence * 100).toFixed(0)}%
                    </span>
                    <span className={`${deadlineColor(days)} truncate`}>
                      {overdue
                        ? `OVERDUE ${Math.abs(days)}d`
                        : days === 0
                          ? "TODAY"
                          : `${days}d · ${p.deadline}`}
                    </span>
                  </div>
                  <div className="flex gap-0.5 shrink-0">
                    <button
                      onClick={() => resolve(p.id, "correct")}
                      className="p-0.5 text-teal hover:bg-teal/10 rounded"
                      title="Correct"
                      aria-label="Mark correct"
                    >
                      <Check size={11} />
                    </button>
                    <button
                      onClick={() => resolve(p.id, "partial")}
                      className="p-0.5 text-amber hover:bg-amber/10 rounded"
                      title="Partial"
                      aria-label="Mark partial"
                    >
                      <Minus size={11} />
                    </button>
                    <button
                      onClick={() => resolve(p.id, "incorrect")}
                      className="p-0.5 text-danger hover:bg-danger/10 rounded"
                      title="Incorrect"
                      aria-label="Mark incorrect"
                    >
                      <X size={11} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {resolved.length > 0 && (
        <div className="mt-1.5">
          <button
            onClick={() => setShowResolved((v) => !v)}
            className="text-[9px] text-text-dim font-mono uppercase tracking-widest hover:text-amber"
          >
            {showResolved ? "− hide" : "+ show"} resolved ({resolved.length})
          </button>
          {showResolved && (
            <div className="space-y-0.5 mt-0.5 opacity-80">
              {resolved.slice(0, 25).map((p) => (
                <div key={p.id} className="card py-1">
                  <div className="flex items-start gap-1">
                    <span
                      className={`badge shrink-0 ${resolutionBadge(p.resolution)}`}
                      title={p.resolution ?? ""}
                    >
                      {p.resolution?.[0]?.toUpperCase() ?? "?"}
                    </span>
                    <p className="text-[10px] text-text-muted leading-tight flex-1 line-through decoration-text-dim/50">
                      {p.statement}
                    </p>
                    <span className="text-[9px] text-text-dim font-mono shrink-0">
                      {(p.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
