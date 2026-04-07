import { useState, useEffect, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { JournalEntry } from "../lib/types";

export default function TradeJournal() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    thesis: "", instrument: "", direction: "long", entry_price: "",
    exit_price: "", notes: "",
  });

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      const data = await apiFetch<JournalEntry[]>("/api/journal");
      setEntries(data);
    } catch { /* ignore */ }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!form.instrument || !form.entry_price) return;
    try {
      await apiFetch("/api/journal", {
        method: "POST",
        body: JSON.stringify({
          thesis: form.thesis,
          instrument: form.instrument,
          direction: form.direction,
          entry_price: parseFloat(form.entry_price),
          exit_price: form.exit_price ? parseFloat(form.exit_price) : null,
          notes: form.notes,
        }),
      });
      setShowForm(false);
      setForm({ thesis: "", instrument: "", direction: "long", entry_price: "", exit_price: "", notes: "" });
      load();
    } catch { /* ignore */ }
  }

  const sorted = [...entries].sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs text-text-dim font-medium uppercase tracking-wider">Trade Journal</h3>
        <button onClick={() => setShowForm(!showForm)} className="text-text-muted hover:text-amber">
          <Plus size={14} />
        </button>
      </div>

      {showForm && (
        <form onSubmit={create} className="card mb-2 space-y-2">
          <input className="input w-full text-xs" placeholder="Instrument (e.g. XOP)" value={form.instrument} onChange={(e) => setForm({ ...form, instrument: e.target.value })} autoFocus />
          <input className="input w-full text-xs" placeholder="Thesis" value={form.thesis} onChange={(e) => setForm({ ...form, thesis: e.target.value })} />
          <div className="flex gap-2">
            <select className="input text-xs" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
            <input className="input flex-1 text-xs" type="number" step="0.01" placeholder="Entry" value={form.entry_price} onChange={(e) => setForm({ ...form, entry_price: e.target.value })} />
            <input className="input flex-1 text-xs" type="number" step="0.01" placeholder="Exit" value={form.exit_price} onChange={(e) => setForm({ ...form, exit_price: e.target.value })} />
          </div>
          <textarea className="input w-full text-xs" rows={2} placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button className="btn-primary text-xs w-full" type="submit">Add Entry</button>
        </form>
      )}

      <div className="space-y-1">
        {sorted.map((entry) => (
          <div key={entry.id} className="card">
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-xs font-mono font-medium">{entry.instrument}</span>
              <span className={`badge text-xs ${entry.direction === "long" ? "badge-stable" : "badge-fired"}`}>
                {entry.direction}
              </span>
            </div>
            <div className="flex gap-3 text-xs font-mono text-text-muted">
              <span>Entry: {entry.entry_price}</span>
              {entry.exit_price && <span>Exit: {entry.exit_price}</span>}
              {entry.pnl !== null && entry.pnl !== undefined && (
                <span className={entry.pnl >= 0 ? "text-teal" : "text-danger"}>
                  P&L: {entry.pnl >= 0 ? "+" : ""}{entry.pnl}
                </span>
              )}
            </div>
            {entry.notes && <p className="text-xs text-text-dim mt-0.5">{entry.notes}</p>}
            <p className="text-xs text-text-dim mt-0.5">{new Date(entry.created_at).toLocaleDateString()}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
