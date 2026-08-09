// TradingView integration panel.
//
// Operator console for wiring TradingView Pine alerts into thesis nodes.
// Sections:
//   1. Webhook status — URL (selectable + masked), secret state, rate-limit + nonce telemetry
//   2. Bindings — searchable, op-color-coded, health-tagged, inline-confirm delete
//   3. Recent alerts — color-coded by result, expandable rows for full payload
//   4. Create-binding modal — op-conditional fields, inline validation, live Pine payload preview
//
// WHY a single panel: when an alert misfires the operator needs the URL,
// the binding rule, and the audit row in one place. Splitting across tabs
// adds clicks at the moment friction matters most.

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Filter,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
  Zap,
} from "lucide-react";
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
import { useToast } from "./toast";

interface Props {
  bookId: string | null;
  books: ThesisBook[];
}

const OP_DESCRIPTIONS: Record<TVOp, string> = {
  incrementClosesObserved: "Bump closesObserved counter (price / reversal nodes)",
  setNodeState: "Set event node state directly",
  setProbability: "Set event probability (0.0 – 1.0)",
  setCurrent: "Set node current value (price / reversal / constraint)",
};

const OP_HINTS: Record<TVOp, string> = {
  incrementClosesObserved:
    "Use for persistence gates where N consecutive closes confirm a level (e.g. brent close >= 115).",
  setNodeState:
    "Use for kill-switch / news-driven events. Allowed states are constrained server-side.",
  setProbability:
    "Use when a market signal updates an event probability (Pine sends `value` 0.0 – 1.0).",
  setCurrent:
    "Use when the alert payload carries the new measurement (Pine sends `value` as a number).",
};

const OP_COLORS: Record<TVOp, string> = {
  incrementClosesObserved: "text-amber border-amber/40 bg-amber/10",
  setNodeState: "text-purple border-purple/40 bg-purple/10",
  setProbability: "text-blue border-blue/40 bg-blue/10",
  setCurrent: "text-teal border-teal/40 bg-teal/10",
};

const ALLOWED_STATES: TVNodeState[] = [
  "active",
  "resolved",
  "partial",
  "monitoring",
  "fired",
];

const POLL_INTERVAL_MS = 15_000;

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`;
  return `${Math.round(diff / 86_400_000)}d ago`;
}

function bindingHealth(b: TVBinding): { tone: string; label: string } {
  if (!b.lastFiredAt || (b.fireCount ?? 0) === 0) {
    return { tone: "text-text-dim", label: "never fired" };
  }
  const ageMs = Date.now() - new Date(b.lastFiredAt).getTime();
  if (ageMs < 24 * 3_600_000) return { tone: "text-teal", label: "active" };
  if (ageMs < 14 * 86_400_000) return { tone: "text-text-muted", label: "idle" };
  return { tone: "text-amber", label: "stale" };
}

function resultTone(result: string): string {
  if (result === "ok") return "text-teal";
  if (result.includes("signature") || result.includes("timestamp") || result.includes("nonce") || result.includes("auth")) {
    return "text-danger";
  }
  if (result.includes("rate") || result.includes("not_found") || result.includes("invalid")) {
    return "text-amber";
  }
  return "text-text-dim";
}

function resultDot(result: string): string {
  const tone = resultTone(result);
  if (tone === "text-teal") return "bg-teal";
  if (tone === "text-danger") return "bg-danger";
  if (tone === "text-amber") return "bg-amber";
  return "bg-text-dim";
}

// Build the Pine Script alert message preview for a (still-being-created) binding.
function buildPinePayloadPreview(
  bookId: string,
  bindingId: string,
  op: TVOp,
): string {
  if (!bookId || !bindingId) return "";
  const obj: Record<string, string> = {
    book: bookId,
    bindingId: bindingId,
  };
  if (op === "setProbability" || op === "setCurrent") {
    return JSON.stringify({ ...obj, value: "{{close}}" });
  }
  return JSON.stringify(obj);
}

export default function TradingViewPanel({ bookId, books }: Props) {
  const { toast } = useToast();
  const [selectedBook, setSelectedBook] = useState(bookId || "");
  const [status, setStatus] = useState<TVStatus | null>(null);
  const [bindings, setBindings] = useState<TVBinding[]>([]);
  const [events, setEvents] = useState<TVAlertEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastFetched, setLastFetched] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showForm, setShowForm] = useState(false);

  // List UX
  const [bindingFilter, setBindingFilter] = useState("");
  const [opFilter, setOpFilter] = useState<TVOp | "all">("all");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);
  const [resultFilter, setResultFilter] = useState<"all" | "ok" | "fail">("all");

  // Form state
  const [formBindingId, setFormBindingId] = useState("");
  const [formNodeId, setFormNodeId] = useState("");
  const [formOp, setFormOp] = useState<TVOp>("incrementClosesObserved");
  const [formThreshold, setFormThreshold] = useState("");
  const [formTargetState, setFormTargetState] = useState<TVNodeState>("fired");
  const [formPineName, setFormPineName] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formSubmitting, setFormSubmitting] = useState(false);

  // Modal a11y
  const modalRef = useRef<HTMLDivElement | null>(null);
  const firstFieldRef = useRef<HTMLInputElement | null>(null);

  // Sync selected book when parent changes
  useEffect(() => {
    if (bookId && !selectedBook) setSelectedBook(bookId);
  }, [bookId, selectedBook]);

  const loadAll = useCallback(async () => {
    if (!selectedBook) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [st, bs, evs] = await Promise.all([
        getTVStatus(),
        listTVBindings(selectedBook),
        listTVEvents(selectedBook, 50),
      ]);
      setStatus(st);
      setBindings(bs);
      setEvents(evs);
      setLastFetched(Date.now());
    } catch (e) {
      const msg = e instanceof Error ? e.message : "load failed";
      setLoadError(msg);
      toast("Failed to load TradingView data", "error");
    } finally {
      setLoading(false);
    }
  }, [selectedBook, toast]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  // Poll silently every 15s; only show spinner on user-initiated refresh.
  useEffect(() => {
    if (!selectedBook) return;
    const id = setInterval(() => {
      // Skip silent poll if a modal is open or a delete is being confirmed —
      // refreshing under the user's hands disrupts focus and selection.
      if (showForm || confirmDelete) return;
      Promise.all([
        getTVStatus(),
        listTVBindings(selectedBook),
        listTVEvents(selectedBook, 50),
      ])
        .then(([st, bs, evs]) => {
          setStatus(st);
          setBindings(bs);
          setEvents(evs);
          setLastFetched(Date.now());
          setLoadError(null);
        })
        .catch(() => {
          // Silent — surface only via the staleness indicator.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [selectedBook, showForm, confirmDelete]);

  // Modal: focus first field on open, Escape to close, basic focus trap.
  useEffect(() => {
    if (!showForm) return;
    firstFieldRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        resetForm();
      }
      if (e.key === "Tab" && modalRef.current) {
        const focusable = modalRef.current.querySelectorAll<HTMLElement>(
          'input, select, textarea, button, [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
     
  }, [showForm]);

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
    setFormSubmitting(false);
  }

  // Inline validation for the create form.
  const formErrors = useMemo(() => {
    const errs: Record<string, string> = {};
    if (!showForm) return errs;
    if (formBindingId && !/^[a-z0-9][a-z0-9-]*$/.test(formBindingId)) {
      errs.bindingId = "lowercase letters, digits, dashes only";
    }
    if (
      formBindingId &&
      bindings.some((b) => b.bindingId === formBindingId.trim())
    ) {
      errs.bindingId = "already exists in this book";
    }
    if (formOp === "incrementClosesObserved" && formThreshold) {
      const n = parseFloat(formThreshold);
      if (Number.isNaN(n)) errs.threshold = "must be numeric";
    }
    return errs;
  }, [showForm, formBindingId, formOp, formThreshold, bindings]);

  const formValid =
    !!formBindingId.trim() &&
    !!formNodeId.trim() &&
    Object.keys(formErrors).length === 0 &&
    (formOp !== "incrementClosesObserved" || formThreshold.trim().length > 0);

  async function submitForm() {
    if (!selectedBook || !formValid) {
      toast("bindingId and nodeId are required", "error");
      return;
    }
    setFormSubmitting(true);
    const payload: TVBindingCreate = {
      bindingId: formBindingId.trim(),
      nodeId: formNodeId.trim(),
      op: formOp,
      description: formDescription.trim() || undefined,
      expectedPineAlertName: formPineName.trim() || undefined,
    };
    if (formOp === "incrementClosesObserved") {
      const n = parseFloat(formThreshold);
      if (!Number.isNaN(n)) payload.thresholdLevel = n;
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
      setFormSubmitting(false);
    }
  }

  async function removeBinding(bindingId: string) {
    if (!selectedBook) return;
    try {
      await deleteTVBinding(selectedBook, bindingId);
      toast(`Deleted ${bindingId}`, "success");
      setConfirmDelete(null);
      loadAll();
    } catch {
      toast("Delete failed", "error");
      setConfirmDelete(null);
    }
  }

  // Filtered binding list.
  const filteredBindings = useMemo(() => {
    const q = bindingFilter.trim().toLowerCase();
    return bindings.filter((b) => {
      if (opFilter !== "all" && b.op !== opFilter) return false;
      if (!q) return true;
      return (
        b.bindingId.toLowerCase().includes(q) ||
        b.nodeId.toLowerCase().includes(q) ||
        (b.description ?? "").toLowerCase().includes(q)
      );
    });
  }, [bindings, bindingFilter, opFilter]);

  // Filtered alert feed.
  const filteredEvents = useMemo(() => {
    return events.filter((e) => {
      if (resultFilter === "all") return true;
      if (resultFilter === "ok") return e.result === "ok";
      return e.result !== "ok";
    });
  }, [events, resultFilter]);

  // Surfaced warnings.
  const recentRateLimited = useMemo(
    () => events.some((e) => e.result.includes("rate")),
    [events],
  );
  const recentAuthFails = useMemo(
    () => events.filter((e) => resultTone(e.result) === "text-danger").slice(0, 3),
    [events],
  );

  const pinePreview = useMemo(
    () => buildPinePayloadPreview(selectedBook, formBindingId.trim(), formOp),
    [selectedBook, formBindingId, formOp],
  );

  const polledAgo = lastFetched ? relativeTime(new Date(lastFetched).toISOString()) : "—";

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          TradingView
        </span>
        <div className="flex items-center gap-1.5" aria-live="polite">
          <span
            className="text-[9px] font-mono text-text-dim"
            title={lastFetched ? new Date(lastFetched).toLocaleString() : "never"}
          >
            {loading ? "syncing…" : `synced ${polledAgo}`}
          </span>
          <button
            onClick={loadAll}
            className="text-text-dim hover:text-amber p-0.5"
            disabled={loading}
            aria-label="Refresh TradingView data"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      <select
        className="input w-full"
        value={selectedBook}
        onChange={(e) => setSelectedBook(e.target.value)}
        aria-label="Active book"
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

      {selectedBook && loadError && !status && (
        <div className="card border-danger/40 bg-danger/10">
          <div className="flex items-center gap-1 text-[10px] font-mono text-danger">
            <AlertTriangle size={11} />
            <span>Load failed: {loadError}</span>
          </div>
          <button
            onClick={loadAll}
            className="mt-1 text-[10px] text-text-dim hover:text-amber underline"
          >
            retry
          </button>
        </div>
      )}

      {selectedBook && status && (
        <>
          {/* Warnings rail */}
          {!status.secretConfigured && (
            <div
              className="card border-danger/40 bg-danger/10"
              role="alert"
            >
              <div className="flex items-start gap-1 text-[10px] font-mono text-danger">
                <AlertTriangle size={11} className="shrink-0 mt-0.5" />
                <div>
                  <div className="font-medium">Webhook unsecured</div>
                  <div className="text-text-muted mt-0.5">
                    Set <code className="text-amber">TV_WEBHOOK_SECRET</code> in the
                    webapp environment. Until then, all incoming alerts will be
                    rejected with 401.
                  </div>
                </div>
              </div>
            </div>
          )}
          {recentRateLimited && (
            <div className="card border-amber/30 bg-amber/5" role="alert">
              <div className="flex items-center gap-1 text-[10px] font-mono text-amber">
                <AlertTriangle size={10} />
                <span>
                  Rate-limit hits in recent feed — currently {status.rateLimitPerMin}
                  /min/IP. Check Pine alert frequency.
                </span>
              </div>
            </div>
          )}

          {/* Webhook status */}
          <div className="card">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-text-dim uppercase tracking-wide">
                Webhook
              </span>
              {status.secretConfigured ? (
                <span
                  className="text-[10px] font-mono text-teal flex items-center gap-0.5"
                  title="HMAC secret is configured. Signed POSTs will be accepted."
                >
                  <Check size={10} /> ARMED
                </span>
              ) : (
                <span className="text-[10px] font-mono text-danger flex items-center gap-0.5">
                  <AlertTriangle size={10} /> NO SECRET
                </span>
              )}
            </div>
            <div className="flex items-center gap-1">
              {/* readOnly input gives us select-all-on-focus + reliable selection
                  without leaking via DOM attributes (value is mirrored in state). */}
              <input
                readOnly
                value={status.webhookUrl}
                onFocus={(e) => e.currentTarget.select()}
                onClick={(e) => e.currentTarget.select()}
                aria-label="Webhook URL"
                className="text-[10px] font-mono text-text-muted bg-elevated border border-border px-1 py-0.5 rounded-sm flex-1 min-w-0 truncate focus:outline-none focus:border-amber/50"
              />
              <button
                onClick={copyWebhook}
                className="text-text-dim hover:text-amber p-0.5"
                aria-label={copied ? "Copied" : "Copy webhook URL"}
                title="Copy URL"
              >
                {copied ? <Check size={11} className="text-teal" /> : <Copy size={11} />}
              </button>
            </div>
            <div className="grid grid-cols-3 gap-1 mt-1 text-[9px] font-mono text-text-dim">
              <div title="Per-IP rate limit">
                rate: <span className="text-text-muted">{status.rateLimitPerMin}/min</span>
              </div>
              <div title="Allowed timestamp skew">
                skew: <span className="text-text-muted">±{status.clockSkewSeconds}s</span>
              </div>
              <div title="Active anti-replay nonces in store">
                nonces: <span className="text-text-muted">{status.activeNonces}</span>
              </div>
            </div>
          </div>

          {/* Bindings header */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] text-text-dim uppercase tracking-wide">
                Bindings ({filteredBindings.length}/{bindings.length})
              </span>
              <button
                onClick={() => setShowForm(true)}
                className="text-text-dim hover:text-amber flex items-center gap-0.5 text-[10px]"
                aria-label="Create new binding"
              >
                <Plus size={11} /> new
              </button>
            </div>

            {/* Filters — only useful when there are enough bindings to warrant them */}
            {bindings.length >= 3 && (
              <div className="flex items-center gap-1 mb-1">
                <div className="relative flex-1">
                  <Search
                    size={10}
                    className="absolute left-1.5 top-1/2 -translate-y-1/2 text-text-dim pointer-events-none"
                  />
                  <input
                    type="text"
                    value={bindingFilter}
                    onChange={(e) => setBindingFilter(e.target.value)}
                    placeholder="filter…"
                    aria-label="Filter bindings"
                    className="input w-full pl-5 py-0.5 text-[10px]"
                  />
                </div>
                <select
                  value={opFilter}
                  onChange={(e) => setOpFilter(e.target.value as TVOp | "all")}
                  aria-label="Filter by op"
                  className="input py-0.5 text-[10px]"
                >
                  <option value="all">all ops</option>
                  {(Object.keys(OP_DESCRIPTIONS) as TVOp[]).map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Empty state */}
            {bindings.length === 0 && (
              <div className="card text-[10px] font-mono text-text-dim py-2 px-2 leading-relaxed">
                <div className="text-text-muted mb-0.5">No bindings yet.</div>
                <div>
                  A binding maps a Pine alert to one mutation on one node. Click{" "}
                  <button
                    onClick={() => setShowForm(true)}
                    className="text-amber underline"
                  >
                    new
                  </button>{" "}
                  to create your first.
                </div>
              </div>
            )}

            {/* Filtered-empty state */}
            {bindings.length > 0 && filteredBindings.length === 0 && (
              <div className="text-[10px] font-mono text-text-dim px-1 py-1 flex items-center gap-1">
                <Filter size={10} /> No bindings match this filter.
              </div>
            )}

            <div className="space-y-1">
              {filteredBindings.map((b) => {
                const health = bindingHealth(b);
                const isConfirming = confirmDelete === b.bindingId;
                return (
                  <div
                    key={b.bindingId}
                    className={`card py-1 px-1.5 hover:bg-elevated/50 ${
                      isConfirming ? "border-danger/50" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span
                        className="text-[11px] font-mono font-medium text-amber truncate"
                        title={b.bindingId}
                      >
                        {b.bindingId}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        <span
                          className={`text-[9px] font-mono ${health.tone}`}
                          title={`last fired ${relativeTime(b.lastFiredAt)}`}
                        >
                          {health.label}
                        </span>
                        {!isConfirming ? (
                          <button
                            onClick={() => setConfirmDelete(b.bindingId)}
                            className="text-text-dim hover:text-danger"
                            aria-label={`Delete binding ${b.bindingId}`}
                            title="Delete"
                          >
                            <Trash2 size={10} />
                          </button>
                        ) : null}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 mt-0.5">
                      <span
                        className={`text-[9px] font-mono px-1 rounded-sm border ${OP_COLORS[b.op]}`}
                      >
                        {b.op}
                      </span>
                      <span className="text-[9px] font-mono text-text-muted truncate">
                        → {b.nodeId}
                        {b.thresholdLevel != null && (
                          <span className="text-text-dim"> · lvl {b.thresholdLevel}</span>
                        )}
                        {b.targetState && (
                          <span className="text-text-dim"> · {b.targetState}</span>
                        )}
                      </span>
                    </div>
                    <div className="text-[9px] font-mono text-text-dim mt-0.5">
                      fires <span className="text-text-muted">{b.fireCount ?? 0}</span>
                      {" · last "}
                      <span className="text-text-muted">{relativeTime(b.lastFiredAt)}</span>
                    </div>
                    {b.description && (
                      <div
                        className="text-[9px] font-mono text-text-dim mt-0.5 truncate"
                        title={b.description}
                      >
                        {b.description}
                      </div>
                    )}
                    {isConfirming && (
                      <div className="mt-1 pt-1 border-t border-danger/30 flex items-center justify-between gap-1">
                        <span className="text-[9px] font-mono text-danger">
                          Delete? This stops accepting alerts for this binding.
                        </span>
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            onClick={() => removeBinding(b.bindingId)}
                            className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-danger/20 text-danger border border-danger/40 hover:bg-danger/30"
                          >
                            confirm
                          </button>
                          <button
                            onClick={() => setConfirmDelete(null)}
                            className="text-[9px] font-mono text-text-dim hover:text-text-primary px-1"
                          >
                            cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Recent alerts */}
          <div>
            <div className="flex items-center justify-between mb-0.5">
              <span className="text-[10px] text-text-dim uppercase tracking-wide">
                Recent alerts ({filteredEvents.length})
              </span>
              {events.length > 0 && (
                <div className="flex items-center gap-0.5 text-[9px] font-mono">
                  {(["all", "ok", "fail"] as const).map((f) => (
                    <button
                      key={f}
                      onClick={() => setResultFilter(f)}
                      className={`px-1 py-px rounded ${
                        resultFilter === f
                          ? "text-amber bg-amber/10"
                          : "text-text-dim hover:text-text-primary"
                      }`}
                      aria-pressed={resultFilter === f}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {recentAuthFails.length > 0 && resultFilter === "all" && (
              <div className="text-[9px] font-mono text-danger mb-0.5 px-1">
                {recentAuthFails.length} recent auth failure
                {recentAuthFails.length === 1 ? "" : "s"} — verify the relay's
                clock and shared secret.
              </div>
            )}

            {events.length === 0 && (
              <div className="card text-[10px] font-mono text-text-dim py-2 px-2 leading-relaxed">
                <div className="text-text-muted mb-0.5">Waiting for first webhook hit.</div>
                <div>
                  Test from your relay or run{" "}
                  <code className="text-amber">tools/bridge/sign_tv_alert.py</code>.
                  See the Pine setup runbook for the canonical payload shape.
                </div>
              </div>
            )}

            {events.length > 0 && filteredEvents.length === 0 && (
              <div className="text-[10px] font-mono text-text-dim px-1 py-1">
                No events match this filter.
              </div>
            )}

            <div className="space-y-px">
              {filteredEvents.map((e, i) => {
                const key = `${e.ts}-${i}`;
                const isOpen = expandedEvent === key;
                return (
                  <div
                    key={key}
                    className="rounded-sm border border-transparent hover:border-border"
                  >
                    <button
                      onClick={() => setExpandedEvent(isOpen ? null : key)}
                      className="w-full flex items-center gap-1 py-px px-1 hover:bg-elevated/50 text-left"
                      aria-expanded={isOpen}
                    >
                      <span
                        className={`w-1 h-1 rounded-full shrink-0 ${resultDot(e.result)}`}
                        aria-hidden="true"
                      />
                      {isOpen ? (
                        <ChevronDown size={9} className="text-text-dim shrink-0" />
                      ) : (
                        <ChevronRight size={9} className="text-text-dim shrink-0" />
                      )}
                      <span className="text-[9px] font-mono text-text-dim shrink-0 w-12">
                        {e.ts.slice(11, 19)}
                      </span>
                      <span
                        className={`text-[9px] font-mono shrink-0 ${resultTone(e.result)}`}
                      >
                        {e.result}
                      </span>
                      <span className="text-[10px] font-mono truncate text-text-muted flex-1 min-w-0">
                        {e.bindingId || e.detail || "—"}
                      </span>
                    </button>
                    {isOpen && (
                      <div className="px-2 py-1 bg-elevated/50 text-[9px] font-mono text-text-muted space-y-0.5">
                        <div>
                          <span className="text-text-dim">ts</span> {e.ts}
                        </div>
                        {e.bookId && (
                          <div>
                            <span className="text-text-dim">book</span> {e.bookId}
                          </div>
                        )}
                        {e.bindingId && (
                          <div>
                            <span className="text-text-dim">binding</span> {e.bindingId}
                          </div>
                        )}
                        {e.nodeId && (
                          <div>
                            <span className="text-text-dim">node</span> {e.nodeId}
                          </div>
                        )}
                        {e.op && (
                          <div>
                            <span className="text-text-dim">op</span> {e.op}
                          </div>
                        )}
                        {e.newValue !== undefined && e.newValue !== null && (
                          <div>
                            <span className="text-text-dim">value</span>{" "}
                            {JSON.stringify(e.newValue)}
                          </div>
                        )}
                        {e.detail && (
                          <div>
                            <span className="text-text-dim">detail</span> {e.detail}
                          </div>
                        )}
                        {e.sourceIP && (
                          <div>
                            <span className="text-text-dim">src</span> {e.sourceIP}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {/* Create binding modal — overlay variant gives focus and breathing room
          for a multi-field form that was cramped in the sidebar. */}
      {showForm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-void/80 backdrop-blur-sm p-4"
          onClick={(e) => {
            if (e.target === e.currentTarget) resetForm();
          }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="tv-modal-title"
        >
          <div
            ref={modalRef}
            className="bg-surface border border-border rounded shadow-lg w-full max-w-md max-h-[90vh] overflow-y-auto"
          >
            <div className="flex items-center justify-between px-3 py-2 border-b border-border">
              <h3
                id="tv-modal-title"
                className="text-[11px] font-mono font-medium uppercase tracking-wide text-amber flex items-center gap-1"
              >
                <Zap size={11} /> New binding
              </h3>
              <button
                onClick={resetForm}
                className="text-text-dim hover:text-text-primary"
                aria-label="Close modal"
              >
                <X size={13} />
              </button>
            </div>

            <div className="p-3 space-y-2">
              <div>
                <label className="block text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                  binding id
                </label>
                <input
                  ref={firstFieldRef}
                  className={`input w-full ${
                    formErrors.bindingId ? "border-danger/60" : ""
                  }`}
                  placeholder="e.g. brent-persistence-close-above-115"
                  value={formBindingId}
                  onChange={(e) => setFormBindingId(e.target.value)}
                  aria-invalid={!!formErrors.bindingId}
                  aria-describedby="bindingId-hint"
                />
                <div
                  id="bindingId-hint"
                  className={`text-[9px] font-mono mt-0.5 ${
                    formErrors.bindingId ? "text-danger" : "text-text-dim"
                  }`}
                >
                  {formErrors.bindingId ||
                    "kebab-case, unique within this book, used in the Pine alert payload"}
                </div>
              </div>

              <div>
                <label className="block text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                  node id
                </label>
                <input
                  className="input w-full"
                  placeholder="e.g. brent"
                  value={formNodeId}
                  onChange={(e) => setFormNodeId(e.target.value)}
                />
                <div className="text-[9px] font-mono text-text-dim mt-0.5">
                  must match a node in this book's graph
                </div>
              </div>

              <div>
                <label className="block text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                  op
                </label>
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
                <div className="text-[9px] font-mono text-text-muted mt-0.5">
                  {OP_DESCRIPTIONS[formOp]}
                </div>
                <div className="text-[9px] font-mono text-text-dim mt-0.5 leading-snug">
                  {OP_HINTS[formOp]}
                </div>
              </div>

              {/* Op-conditional fields */}
              {formOp === "incrementClosesObserved" && (
                <div>
                  <label className="block text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                    threshold level
                  </label>
                  <input
                    className={`input w-full ${
                      formErrors.threshold ? "border-danger/60" : ""
                    }`}
                    type="number"
                    step="any"
                    placeholder="e.g. 115"
                    value={formThreshold}
                    onChange={(e) => setFormThreshold(e.target.value)}
                    aria-invalid={!!formErrors.threshold}
                  />
                  <div
                    className={`text-[9px] font-mono mt-0.5 ${
                      formErrors.threshold ? "text-danger" : "text-text-dim"
                    }`}
                  >
                    {formErrors.threshold ||
                      "the price level Pine is gating on (used for binding-side validation)"}
                  </div>
                </div>
              )}

              {formOp === "setNodeState" && (
                <div>
                  <label className="block text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                    target state
                  </label>
                  <select
                    className="input w-full"
                    value={formTargetState}
                    onChange={(e) =>
                      setFormTargetState(e.target.value as TVNodeState)
                    }
                  >
                    {ALLOWED_STATES.map((s) => (
                      <option key={s} value={s}>
                        {s}
                      </option>
                    ))}
                  </select>
                  <div className="text-[9px] font-mono text-text-dim mt-0.5">
                    state to set when this binding fires
                  </div>
                </div>
              )}

              <div>
                <label className="block text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                  pine alert name <span className="text-text-dim">(optional)</span>
                </label>
                <input
                  className="input w-full"
                  placeholder="for cross-checking the inbound payload"
                  value={formPineName}
                  onChange={(e) => setFormPineName(e.target.value)}
                />
              </div>

              <div>
                <label className="block text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                  description <span className="text-text-dim">(optional)</span>
                </label>
                <input
                  className="input w-full"
                  placeholder="trade rationale, reviewer note, anything"
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                />
              </div>

              {/* Live Pine alert payload preview — reduces the gap between
                  this form and the Pine alert message field they'll paste into. */}
              {pinePreview && (
                <div className="border border-border rounded p-2 bg-elevated">
                  <div className="text-[9px] font-mono text-text-dim uppercase tracking-wide mb-0.5">
                    Pine alert message
                  </div>
                  <code className="text-[10px] font-mono text-teal break-all block">
                    {pinePreview}
                  </code>
                  <div className="text-[9px] font-mono text-text-dim mt-1 leading-snug">
                    Paste this verbatim into TradingView's "Message" field. For
                    relay-fronted setups, the relay HMAC-signs and forwards.
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-1 px-3 py-2 border-t border-border">
              <button
                className="text-[10px] text-text-dim hover:text-text-primary px-2 py-1"
                onClick={resetForm}
              >
                cancel
              </button>
              <button
                className="btn-primary disabled:opacity-40 disabled:cursor-not-allowed"
                onClick={submitForm}
                disabled={!formValid || formSubmitting}
              >
                {formSubmitting ? "creating…" : "Create binding"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
