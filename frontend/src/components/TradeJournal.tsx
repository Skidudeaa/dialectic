import { useState, useEffect, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { apiFetch } from "../lib/api";
import type { JournalEntry } from "../lib/types";

export default function TradeJournal() {
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ thesis: "", instrument: "", direction: "long", entry_price: "", exit_price: "", notes: "" });

  useEffect(() => { load(); }, []);

  async function load() {
    try { setEntries(await apiFetch<JournalEntry[]>("/api/journal")); } catch {
      console.error("Failed to load journal");
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!form.instrument || !form.entry_price) return;
    await apiFetch("/api/journal", {
      method: "POST",
      body: JSON.stringify({
        thesis: form.thesis, instrument: form.instrument, direction: form.direction,
        entry_price: parseFloat(form.entry_price),
        exit_price: form.exit_price ? parseFloat(form.exit_price) : null,
        notes: form.notes,
      }),
    });
    setShowForm(false);
    setForm({ thesis: "", instrument: "", direction: "long", entry_price: "", exit_price: "", notes: "" });
    load();
  }

  const sorted = [...entries].sort((a, b) => b.created_at.localeCompare(a.created_at));

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">Journal</span>
        <button onClick={() => setShowForm(!showForm)} className="text-text-dim hover:text-amber">
          <Plus size={12} />
        </button>
      </div>

      {showForm && (
        <form onSubmit={create} className="card mb-1.5 space-y-1">
          <div className="flex gap-1">
            <input className="input flex-1" placeholder="Ticker" value={form.instrument} onChange={(e) => setForm({ ...form, instrument: e.target.value })} autoFocus />
            <select className="input w-16" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })}>
              <option value="long">Long</option>
              <option value="short">Short</option>
            </select>
          </div>
          <div className="flex gap-1">
            <input className="input flex-1" type="number" step="0.01" placeholder="Entry $" value={form.entry_price} onChange={(e) => setForm({ ...form, entry_price: e.target.value })} />
            <input className="input flex-1" type="number" step="0.01" placeholder="Exit $" value={form.exit_price} onChange={(e) => setForm({ ...form, exit_price: e.target.value })} />
          </div>
          <input className="input w-full" placeholder="Thesis" value={form.thesis} onChange={(e) => setForm({ ...form, thesis: e.target.value })} />
          <textarea className="input w-full" rows={2} placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <button className="btn-primary w-full" type="submit">Add Entry</button>
        </form>
      )}

      {sorted.length === 0 && !showForm && (
        <span className="text-[10px] text-text-dim font-mono">No entries. Click + to add.</span>
      )}

      {/* Table-style layout */}
      {sorted.length > 0 && (
        <div className="space-y-0.5">
          <div className="flex items-center gap-2 px-1 text-[9px] font-mono text-text-dim uppercase">
            <span className="w-12">Ticker</span>
            <span className="w-10">Dir</span>
            <span className="w-14 text-right">Entry</span>
            <span className="w-14 text-right">Exit</span>
            <span className="flex-1">Notes</span>
          </div>
          {sorted.map((entry) => (
            <div key={entry.id} className="flex items-center gap-2 px-1 py-0.5 hover:bg-elevated/50 rounded-sm text-[11px] font-mono">
              <span className="w-12 text-amber font-medium truncate">{entry.instrument}</span>
              <span className={`w-10 ${entry.direction === "long" ? "text-teal" : "text-danger"}`}>{entry.direction}</span>
              <span className="w-14 text-right text-text-primary">{entry.entry_price}</span>
              <span className="w-14 text-right text-text-muted">{entry.exit_price ?? "--"}</span>
              <span className="flex-1 text-text-dim truncate text-[10px]">{entry.notes || entry.thesis}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
