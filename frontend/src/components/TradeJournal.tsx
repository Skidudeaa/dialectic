import { useState, useEffect, useMemo, type FormEvent } from "react";
import { Plus, NotebookPen, X, Link2 } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { JournalEntry } from "../lib/types";

const EMPTY_FORM = {
  thesis: "",
  instrument: "",
  direction: "long",
  entry_price: "",
  exit_price: "",
  notes: "",
};

function pnlPct(entry: number, exit: number, direction: string): number {
  if (!entry) return 0;
  const raw = (exit - entry) / entry;
  return direction === "short" ? -raw * 100 : raw * 100;
}

export default function TradeJournal() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [showOptional, setShowOptional] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setError(null);
      const data = await apiFetch<JournalEntry[]>("/api/journal");
      setEntries(data);
      setLastUpdated(new Date());
    } catch {
      setError("Failed to load journal");
    } finally {
      setLoading(false);
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!form.instrument.trim() || !form.entry_price) return;
    setSubmitting(true);
    try {
      await apiFetch("/api/journal", {
        method: "POST",
        body: JSON.stringify({
          thesis: form.thesis.trim(),
          instrument: form.instrument.trim().toUpperCase(),
          direction: form.direction,
          entry_price: parseFloat(form.entry_price),
          exit_price: form.exit_price ? parseFloat(form.exit_price) : null,
          notes: form.notes,
        }),
      });
      setShowForm(false);
      setShowOptional(false);
      setForm(EMPTY_FORM);
      await load();
    } catch {
      setError("Failed to create entry");
    } finally {
      setSubmitting(false);
    }
  }

  const { open, closed, totalPnl, winRate } = useMemo(() => {
    const sorted = [...entries].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    );
    const o = sorted.filter((e) => e.exit_price === null);
    const c = sorted.filter((e) => e.exit_price !== null);
    const tot = c.reduce((s, e) => s + (e.pnl ?? 0), 0);
    const wins = c.filter((e) => (e.pnl ?? 0) > 0).length;
    const wr = c.length > 0 ? (wins / c.length) * 100 : 0;
    return { open: o, closed: c, totalPnl: tot, winRate: wr };
  }, [entries]);

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          Journal
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
            title="Log entry"
            aria-label="Log entry"
          >
            <Plus size={12} />
          </button>
        </div>
      </div>

      {closed.length > 0 && (
        <div className="flex items-center gap-2 mb-1 text-[10px] font-mono">
          <span className="text-text-dim">PnL:</span>
          <span
            className={`font-bold ${totalPnl > 0 ? "text-teal" : totalPnl < 0 ? "text-danger" : "text-text-muted"}`}
          >
            {totalPnl > 0 ? "+" : ""}
            {totalPnl.toFixed(0)}
          </span>
          <span className="text-text-dim">·</span>
          <span className="text-text-dim">win:</span>
          <span className="text-amber">{winRate.toFixed(0)}%</span>
          <span className="text-text-dim">
            ({closed.length} closed, {open.length} open)
          </span>
        </div>
      )}

      {error && (
        <div className="text-[10px] text-danger font-mono mb-1 px-1">{error}</div>
      )}

      {showForm && (
        <form onSubmit={create} className="card mb-1.5 space-y-1">
          <div className="flex gap-1">
            <input
              className="input flex-1 uppercase"
              placeholder="TICKER"
              value={form.instrument}
              onChange={(e) => setForm({ ...form, instrument: e.target.value })}
              autoFocus
              required
            />
            <select
              className="input w-16"
              value={form.direction}
              onChange={(e) => setForm({ ...form, direction: e.target.value })}
            >
              <option value="long">long</option>
              <option value="short">short</option>
            </select>
          </div>
          <div className="flex gap-1">
            <input
              className="input flex-1"
              type="number"
              step="0.01"
              placeholder="Entry $"
              value={form.entry_price}
              onChange={(e) => setForm({ ...form, entry_price: e.target.value })}
              required
            />
            <input
              className="input flex-1"
              type="number"
              step="0.01"
              placeholder="Exit $ (optional)"
              value={form.exit_price}
              onChange={(e) => setForm({ ...form, exit_price: e.target.value })}
            />
          </div>
          <button
            type="button"
            onClick={() => setShowOptional((v) => !v)}
            className="text-[10px] text-text-dim font-mono hover:text-amber"
          >
            {showOptional ? "− hide" : "+ thesis link / notes"}
          </button>
          {showOptional && (
            <>
              <input
                className="input w-full"
                placeholder="Thesis node (e.g. brent, hormuz)"
                value={form.thesis}
                onChange={(e) => setForm({ ...form, thesis: e.target.value })}
              />
              <textarea
                className="input w-full"
                rows={2}
                placeholder="Notes / setup / risk"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
              />
            </>
          )}
          <div className="flex gap-1">
            <button className="btn-primary flex-1" type="submit" disabled={submitting}>
              {submitting ? "..." : "Log entry"}
            </button>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => {
                setShowForm(false);
                setShowOptional(false);
              }}
            >
              <X size={11} />
            </button>
          </div>
        </form>
      )}

      {loading && (
        <div className="space-y-0.5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card animate-pulse h-6 bg-elevated/30" />
          ))}
        </div>
      )}

      {!loading && entries.length === 0 && !showForm && (
        <div className="card flex flex-col items-center text-center py-3 gap-1">
          <NotebookPen size={18} className="text-text-dim" />
          <p className="text-[11px] text-text-primary leading-tight">
            Log every entry, link the cause.
          </p>
          <p className="text-[10px] text-text-dim leading-tight max-w-[200px]">
            Each trade ties back to a thesis node. Months from now you can see which
            transmission chains actually paid.
          </p>
          <button onClick={() => setShowForm(true)} className="btn-primary mt-1 text-[10px]">
            Log first trade
          </button>
        </div>
      )}

      {open.length > 0 && (
        <>
          <div className="text-[9px] font-mono text-text-dim uppercase tracking-widest mt-1 mb-0.5 px-1">
            open · {open.length}
          </div>
          <div className="space-y-0.5">
            {open.map((entry) => (
              <Row key={entry.id} entry={entry} open />
            ))}
          </div>
        </>
      )}

      {closed.length > 0 && (
        <div className="mt-1.5">
          <button
            onClick={() => setShowClosed((v) => !v)}
            className="text-[9px] text-text-dim font-mono uppercase tracking-widest hover:text-amber px-1"
          >
            {showClosed ? "−" : "+"} closed · {closed.length}
          </button>
          {showClosed && (
            <div className="space-y-0.5 mt-0.5">
              {closed.slice(0, 30).map((entry) => (
                <Row key={entry.id} entry={entry} open={false} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ entry, open }: { entry: JournalEntry; open: boolean }) {
  const pnl = entry.pnl;
  const pct =
    entry.exit_price !== null
      ? pnlPct(entry.entry_price, entry.exit_price, entry.direction)
      : null;
  const pnlColor =
    pnl === null
      ? "text-text-muted"
      : pnl > 0
        ? "text-teal"
        : pnl < 0
          ? "text-danger"
          : "text-text-muted";

  return (
    <div
      className={`px-1 py-0.5 hover:bg-elevated/50 rounded-sm text-[11px] font-mono ${
        open ? "border-l border-amber/30" : ""
      }`}
      title={entry.notes || entry.thesis || ""}
    >
      <div className="flex items-center gap-2">
        <span className="w-12 text-amber font-medium truncate">{entry.instrument}</span>
        <span
          className={`w-10 ${entry.direction === "long" ? "text-teal" : "text-danger"}`}
        >
          {entry.direction === "long" ? "long" : "short"}
        </span>
        <span className="w-12 text-right text-text-primary">
          {entry.entry_price.toFixed(2)}
        </span>
        <span className="w-12 text-right text-text-muted">
          {entry.exit_price !== null ? entry.exit_price.toFixed(2) : "—"}
        </span>
        <span className={`w-14 text-right ${pnlColor}`}>
          {pct === null
            ? "open"
            : `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`}
        </span>
      </div>
      {entry.thesis && (
        <div className="flex items-center gap-1 px-0.5 mt-0.5">
          <Link2 size={9} className="text-purple shrink-0" />
          <span className="text-[10px] text-purple/90 truncate">{entry.thesis}</span>
          {entry.notes && (
            <span className="text-[10px] text-text-dim truncate ml-1">
              · {entry.notes}
            </span>
          )}
        </div>
      )}
      {!entry.thesis && entry.notes && (
        <div className="text-[10px] text-text-dim truncate px-0.5 mt-0.5">
          {entry.notes}
        </div>
      )}
    </div>
  );
}
