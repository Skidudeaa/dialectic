// TradingView integration panel.
//
// Three sections:
//   1. Webhook status — URL, secret presence, rate limit, nonce stats
//   2. Bindings — per-book list with fire count and delete, plus create form
//   3. Recent alerts — last 20 webhook events for the active book
//
// WHY a single panel (not three): operators need to see the webhook URL,
// the bindings that use it, and the audit trail in one place when
// debugging "why didn't my Pine alert fire?". Separating them across tabs
// would multiply navigation overhead.

import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, Check, Copy, Plus, RefreshCw, Trash2, X } from "lucide-react";
import {
  createTVBinding,
  deleteTVBinding,
  getTVStatus,
  listTVBindings,
  listTVEvents,
} from "../lib/api";
import type {
  ThesisBook,
  TVAlertEvent,
  TVBinding,
  TVBindingCreate,
  TVNodeState,
  TVOp,
  TVStatus,
} from "../lib/types";
import { useToast } from "./Toast";

interface Props {
  bookId: string | null;
  books: ThesisBook[];
}

const OP_DESCRIPTIONS: Record<TVOp, string> = {
  incrementClosesObserved: "Bump closesObserved counter (price / reversal)",
  setNodeState: "Set event node state",
  setProbability: "Set event probability (0.0 – 1.0)",
  setCurrent: "Set node current value (price / reversal / constraint)",
};

const ALLOWED_STATES: TVNodeState[] = [
  "active",
  "resolved",
  "partial",
  "monitoring",
  "fired",
];

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Date.now() - t;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  return `${Math.round(diff / 86_400_000)}d ago`;
}

function resultBadge(result: string): string {
  if (result === "ok") return "text-teal";
  if (result.includes("signature") || result.includes("timestamp") || result.includes("nonce")) {
    return "text-danger";
  }
  if (result.includes("rate") || result.includes("not_found")) {
    return "text-amber";
  }
  return "text-text-dim";
}

export default function TradingViewPanel({ bookId, books }: Props) {
  const { toast } = useToast();
  const [selectedBook, setSelectedBook] = useState(bookId || "");
  const [status, setStatus] = useState<TVStatus | null>(null);
  const [bindings, setBindings] = useState<TVBinding[]>([]);
  const [events, setEvents] = useState<TVAlertEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [formBindingId, setFormBindingId] = useState("");
  const [formNodeId, setFormNodeId] = useState("");
  const [formOp, setFormOp] = useState<TVOp>("incrementClosesObserved");
  const [formThreshold, setFormThreshold] = useState("");
  const [formTargetState, setFormTargetState] = useState<TVNodeState>("fired");
  const [formPineName, setFormPineName] = useState("");
  const [formDescription, setFormDescription] = useState("");

  // Sync selected book when parent changes
  useEffect(() => {
    if (bookId && !selectedBook) setSelectedBook(bookId);
  }, [bookId, selectedBook]);

  const loadAll = useCallback(async () => {
    if (!selectedBook) return;
    setLoading(true);
    try {
      const [st, bs, evs] = await Promise.all([
        getTVStatus(),
        listTVBindings(selectedBook),
        listTVEvents(selectedBook, 20),
      ]);
      setStatus(st);
      setBindings(bs);
      setEvents(evs);
    } catch {
      toast("Failed to load TradingView data", "error");
    } finally {
      setLoading(false);
    }
  }, [selectedBook, toast]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  function copyWebhook() {
    if (!status?.webhookUrl) return;
    navigator.clipboard.writeText(status.webhookUrl).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => toast("Copy failed", "error"),
    );
  }

  function resetForm() {
    setFormBindingId("");
    setFormNodeId("");
    setFormOp("incrementClosesObserved");
    setFormThreshold("");
    setFormTargetState("fired");
    setFormPineName("");
    setFormDescription("");
    setShowForm(false);
  }

  async function submitForm() {
    if (!selectedBook || !formBindingId.trim() || !formNodeId.trim()) {
      toast("bindingId and nodeId are required", "error");
      return;
    }
    const payload: TVBindingCreate = {
      bindingId: formBindingId.trim(),
      nodeId: formNodeId.trim(),
      op: formOp,
      description: formDescription.trim() || undefined,
      expectedPineAlertName: formPineName.trim() || undefined,
    };
    if (formOp === "incrementClosesObserved") {
      const n = parseFloat(formThreshold);
      if (Number.isNaN(n)) {
        toast("thresholdLevel must be numeric", "error");
        return;
      }
      payload.thresholdLevel = n;
    }
    if (formOp === "setNodeState") {
      payload.targetState = formTargetState;
    }

    try {
      await createTVBinding(selectedBook, payload);
      toast("Binding created", "success");
      resetForm();
      loadAll();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Create failed";
      toast(msg, "error");
    }
  }

  async function removeBinding(bindingId: string) {
    if (!selectedBook) return;
    if (!confirm(`Delete binding "${bindingId}"?`)) return;
    try {
      await deleteTVBinding(selectedBook, bindingId);
      toast("Binding deleted", "success");
      loadAll();
    } catch {
      toast("Delete failed", "error");
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          TradingView
        </span>
        <button
          onClick={loadAll}
          className="text-text-dim hover:text-amber p-0.5"
          disabled={loading}
          title="Refresh"
        >
          <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      <select
        className="input w-full"
        value={selectedBook}
        onChange={(e) => setSelectedBook(e.target.value)}
      >
        <option value="">Select a book…</option>
        {books.map((b) => (
          <option key={b.id} value={b.id}>
            {b.title}
          </option>
        ))}
      </select>

      {!selectedBook && (
        <div className="card text-[11px] text-text-dim font-mono text-center py-3">
          Pick a book to manage its TradingView bindings.
        </div>
      )}

      {selectedBook && status && (
        <>
          {/* Webhook status */}
          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-text-dim">WEBHOOK</span>
              {status.secretConfigured ? (
                <span className="text-[10px] font-mono text-teal flex items-center gap-0.5">
                  <Check size={10} /> SECURED
                </span>
              ) : (
                <span className="text-[10px] font-mono text-danger flex items-center gap-0.5">
                  <AlertTriangle size={10} /> NO SECRET
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              <code className="text-[10px] font-mono text-text-muted bg-elevated px-1 py-0.5 rounded-sm truncate flex-1">
                {status.webhookUrl}
              </code>
              <button
                onClick={copyWebhook}
                className="text-text-dim hover:text-amber p-0.5"
                title="Copy URL"
              >
                {copied ? <Check size={11} /> : <Copy size={11} />}
              </button>
            </div>
            <div className="grid grid-cols-3 gap-1 mt-1 text-[9px] font-mono text-text-dim">
              <div>rate: <span className="text-text-muted">{status.rateLimitPerMin}/min</span></div>
              <div>skew: <span className="text-text-muted">±{status.clockSkewSeconds}s</span></div>
              <div>nonces: <span className="text-text-muted">{status.activeNonces}</span></div>
            </div>
          </div>

          {/* Bindings */}
          <div>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[10px] text-text-dim">
                BINDINGS ({bindings.length})
              </span>
              <button
                onClick={() => setShowForm(!showForm)}
                className="text-text-dim hover:text-amber"
                title="New binding"
              >
                {showForm ? <X size={11} /> : <Plus size={11} />}
              </button>
            </div>

            {showForm && (
              <div className="card space-y-1 mb-1">
                <input
                  className="input w-full"
                  placeholder="bindingId (kebab-case)"
                  value={formBindingId}
                  onChange={(e) => setFormBindingId(e.target.value)}
                />
                <input
                  className="input w-full"
                  placeholder="nodeId"
                  value={formNodeId}
                  onChange={(e) => setFormNodeId(e.target.value)}
                />
                <select
                  className="input w-full"
                  value={formOp}
                  onChange={(e) => setFormOp(e.target.value as TVOp)}
                >
                  {(Object.keys(OP_DESCRIPTIONS) as TVOp[]).map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                <p className="text-[9px] text-text-dim font-mono">
                  {OP_DESCRIPTIONS[formOp]}
                </p>
                {formOp === "incrementClosesObserved" && (
                  <input
                    className="input w-full"
                    type="number"
                    step="any"
                    placeholder="thresholdLevel"
                    value={formThreshold}
                    onChange={(e) => setFormThreshold(e.target.value)}
                  />
                )}
                {formOp === "setNodeState" && (
                  <select
                    className="input w-full"
                    value={formTargetState}
                    onChange={(e) => setFormTargetState(e.target.value as TVNodeState)}
                  >
                    {ALLOWED_STATES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                )}
                <input
                  className="input w-full"
                  placeholder="pine alert name (optional)"
                  value={formPineName}
                  onChange={(e) => setFormPineName(e.target.value)}
                />
                <input
                  className="input w-full"
                  placeholder="description (optional)"
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                />
                <div className="flex gap-1">
                  <button className="btn-primary flex-1" onClick={submitForm}>
                    Create
                  </button>
                  <button
                    className="text-[10px] text-text-dim hover:text-text-primary px-2"
                    onClick={resetForm}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {bindings.length === 0 && !showForm && (
              <p className="text-[10px] text-text-dim font-mono px-1 py-1">
                No bindings yet. Click + to add one.
              </p>
            )}

            <div className="space-y-1">
              {bindings.map((b) => (
                <div
                  key={b.bindingId}
                  className="card py-1 px-1.5 hover:bg-elevated/50"
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[11px] font-mono font-medium text-amber truncate">
                      {b.bindingId}
                    </span>
                    <button
                      onClick={() => removeBinding(b.bindingId)}
                      className="text-text-dim hover:text-danger shrink-0"
                      title="Delete"
                    >
                      <Trash2 size={10} />
                    </button>
                  </div>
                  <div className="text-[9px] font-mono text-text-dim">
                    {b.nodeId} · {b.op}
                    {b.thresholdLevel != null && <> · lvl {b.thresholdLevel}</>}
                    {b.targetState && <> → {b.targetState}</>}
                  </div>
                  <div className="text-[9px] font-mono text-text-dim">
                    fires: <span className="text-text-muted">{b.fireCount ?? 0}</span>
                    {" · "}
                    last: <span className="text-text-muted">{relativeTime(b.lastFiredAt)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Recent alerts */}
          <div>
            <span className="text-[10px] text-text-dim block mb-0.5">
              RECENT ALERTS ({events.length})
            </span>
            {events.length === 0 && (
              <p className="text-[10px] text-text-dim font-mono px-1 py-1">
                No events yet. Fire a Pine alert to see it here.
              </p>
            )}
            <div className="space-y-px">
              {events.map((e, i) => (
                <div
                  key={`${e.ts}-${i}`}
                  className="flex items-center gap-1 py-px hover:bg-elevated/50 px-1 rounded-sm"
                >
                  <span className="text-[9px] font-mono text-text-dim shrink-0">
                    {e.ts.slice(11, 19)}
                  </span>
                  <span
                    className={`text-[9px] font-mono shrink-0 ${resultBadge(e.result)}`}
                  >
                    {e.result}
                  </span>
                  <span className="text-[10px] font-mono truncate text-text-muted">
                    {e.bindingId || e.detail || "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
