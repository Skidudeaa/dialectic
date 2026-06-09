import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertOctagon, RefreshCw, ShieldCheck, ChevronDown, ChevronRight, X } from "lucide-react";
import { apiFetch, getToken, subscribeRoomMessages } from "../lib/api";
import type {
  KillConfirmIssued,
  KillResult,
  OpenTradeDetail,
  OpenTradeSummary,
  TradePredicate,
  TradePredicateState,
  WSMessage,
} from "../lib/types";
import { useToast } from "./toast";

const REFRESH_MS = 30_000;

// WHY keep these in a map rather than a switch: per-state treatment is
// applied in three places (badge, accent, icon). Central dict keeps the
// color vocabulary stable even if we later add a fifth bucket.
const STATE_BADGE: Record<TradePredicateState, string> = {
  fired: "bg-danger/15 text-danger border border-danger/40",
  approaching: "bg-amber/15 text-amber border border-amber/40",
  stable: "bg-teal/10 text-teal border border-teal/30",
  inactive: "bg-elevated text-text-dim border border-border",
};

const STATE_LABEL: Record<TradePredicateState, string> = {
  fired: "FIRED",
  approaching: "NEAR",
  stable: "STABLE",
  inactive: "MISSING",
};

const STATE_ACCENT: Record<TradePredicateState, string> = {
  fired: "border-l-2 border-danger",
  approaching: "border-l-2 border-amber",
  stable: "border-l-2 border-teal",
  inactive: "border-l-2 border-border",
};

function formatActual(pred: TradePredicate): string {
  if (pred.actual === null || pred.actual === undefined) return "—";
  if (typeof pred.actual === "number") {
    // Avoid "1.299999999" artefacts for the operator glance.
    return Number(pred.actual).toLocaleString(undefined, {
      maximumFractionDigits: 2,
    });
  }
  return String(pred.actual);
}

function bookShort(id: string): string {
  return id.replace(/-graph$/, "").split("-").slice(-1)[0];
}

interface ConfirmState {
  trade_id: string;
  token: string | null;
  reason: string;
  confirmText: string;
  sending: boolean;
  error: string | null;
}

export default function TradeLifecyclePanel() {
  const { toast } = useToast();
  const [trades, setTrades] = useState<OpenTradeSummary[]>([]);
  const [details, setDetails] = useState<Record<string, OpenTradeDetail>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const mounted = useRef(true);

  const loadList = useCallback(async () => {
    try {
      const data = await apiFetch<OpenTradeSummary[]>("/api/v1/trades");
      if (!mounted.current) return;
      setTrades(data);
      setError(null);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : "failed to load trades");
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (trade_id: string) => {
    try {
      const data = await apiFetch<OpenTradeDetail>(`/api/v1/trades/${trade_id}`);
      if (!mounted.current) return;
      setDetails((prev) => ({ ...prev, [trade_id]: data }));
    } catch (e) {
      // Leave existing detail in place; surface only via toast so the
      // card doesn't blank out on a single flake.
      toast(
        `trade ${trade_id} refresh failed: ${e instanceof Error ? e.message : e}`,
        "error",
      );
    }
  }, [toast]);

  // Initial load + polling.
  useEffect(() => {
    mounted.current = true;
    loadList();
    const handle = setInterval(() => {
      loadList();
      // Refresh every currently-expanded trade.
      setExpanded((current) => {
        current.forEach((id) => loadDetail(id));
        return current;
      });
    }, REFRESH_MS);
    return () => {
      mounted.current = false;
      clearInterval(handle);
    };
  }, [loadList, loadDetail]);

  // WS hook — repull affected trade detail when the live engine emits a
  // state update. WHY: A thesis delta means predicate evaluations might
  // have changed; don't wait for the next 30s tick to repaint.
  useEffect(() => {
    return subscribeRoomMessages((msg: WSMessage) => {
      if (msg.type !== "state_update") return;
      const bookId = (msg.payload?.book_id as string | undefined)
        ?? (msg.thesisId as string | undefined);
      if (!bookId) return;
      // Which trades are linked to this book?
      trades
        .filter((t) => t.book === bookId)
        .forEach((t) => loadDetail(t.trade_id));
      // Refresh the list so header counts tick too.
      loadList();
    });
  }, [trades, loadDetail, loadList]);

  function toggle(trade_id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(trade_id)) {
        next.delete(trade_id);
      } else {
        next.add(trade_id);
        loadDetail(trade_id);
      }
      return next;
    });
  }

  function openKill(trade_id: string) {
    setConfirm({
      trade_id,
      token: null,
      reason: "",
      confirmText: "",
      sending: false,
      error: null,
    });
  }

  async function submitKill() {
    if (!confirm) return;
    if (confirm.confirmText !== "KILL") {
      setConfirm({ ...confirm, error: 'Type "KILL" to confirm.' });
      return;
    }
    if (confirm.reason.trim().length === 0) {
      setConfirm({ ...confirm, error: "Reason required." });
      return;
    }
    setConfirm({ ...confirm, sending: true, error: null });
    try {
      // Step 1: request a confirm token (expected 409 with token payload).
      if (!confirm.token) {
        const resp = await fetch(`/api/v1/trades/${confirm.trade_id}/kill`, {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify({ reason: confirm.reason }),
        });
        if (resp.status !== 409) {
          const text = await resp.text();
          throw new Error(`Expected 409 confirm prompt, got ${resp.status}: ${text}`);
        }
        const body = await resp.json();
        const issued = body.detail as KillConfirmIssued;
        // Step 2: immediately submit with the token.
        const resp2 = await fetch(`/api/v1/trades/${confirm.trade_id}/kill`, {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify({
            reason: confirm.reason,
            confirm_token: issued.confirm_token,
          }),
        });
        if (!resp2.ok) {
          const text = await resp2.text();
          throw new Error(`${resp2.status}: ${text}`);
        }
        const result = (await resp2.json()) as KillResult;
        toast(`Killed ${result.trade_id}`, "success");
      }
      setConfirm(null);
      loadList();
    } catch (e) {
      setConfirm((c) => c && {
        ...c,
        sending: false,
        error: e instanceof Error ? e.message : "kill failed",
      });
    }
  }

  const summary = useMemo(() => {
    const fired = trades.reduce((acc, t) => acc + (t.fired_count ?? 0), 0);
    const approaching = trades.reduce(
      (acc, t) => acc + (t.approaching_count ?? 0),
      0,
    );
    return { count: trades.length, fired, approaching };
  }, [trades]);

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          Trade lifecycle
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => { loadList(); expanded.forEach(loadDetail); }}
            className="text-text-dim hover:text-amber p-0.5"
            disabled={loading}
            title="Re-evaluate predicates"
            aria-label="Refresh trade predicates"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Header summary */}
      <div className="flex items-center gap-2 mb-1 text-[10px] font-mono text-text-dim px-0.5">
        <span>{summary.count} trades</span>
        {summary.fired > 0 && (
          <span className="text-danger font-bold animate-pulse-danger">
            {summary.fired} fired
          </span>
        )}
        {summary.approaching > 0 && (
          <span className="text-amber">{summary.approaching} near</span>
        )}
        {summary.fired === 0 && summary.approaching === 0 && trades.length > 0 && (
          <span className="text-teal">all stable</span>
        )}
      </div>

      {error && (
        <div className="text-[10px] text-danger font-mono mb-1 px-1">
          {error}{" "}
          <button onClick={loadList} className="underline hover:text-amber">
            retry
          </button>
        </div>
      )}

      {loading && trades.length === 0 && (
        <div className="space-y-1">
          {[0, 1].map((i) => (
            <div key={i} className="card animate-pulse h-16 bg-elevated/30" />
          ))}
        </div>
      )}

      {!loading && trades.length === 0 && (
        <div className="card flex flex-col items-center text-center py-3 gap-1">
          <ShieldCheck size={18} className="text-teal" />
          <p className="text-[11px] text-text-primary leading-tight">
            No open trades.
          </p>
          <p className="text-[10px] text-text-dim leading-tight max-w-[220px]">
            Seed entries with <code className="text-amber">tools/outcomes/log_entry.py</code>.
          </p>
        </div>
      )}

      <div className="space-y-1">
        {trades.map((t) => {
          const isOpen = expanded.has(t.trade_id);
          const detail = details[t.trade_id];
          const accent = t.fired_count > 0
            ? "border-l-2 border-danger"
            : t.approaching_count > 0
              ? "border-l-2 border-amber"
              : "border-l-2 border-teal";
          return (
            <div key={t.trade_id} className={`card ${accent}`}>
              <div className="flex items-start gap-1.5">
                <button
                  onClick={() => toggle(t.trade_id)}
                  className="text-text-dim hover:text-amber shrink-0 mt-0.5"
                  aria-label={isOpen ? "Collapse" : "Expand"}
                >
                  {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1 mb-0.5 flex-wrap">
                    <span className="text-[11px] font-mono text-amber font-semibold">
                      {t.trade_id}
                    </span>
                    <span className="text-[9px] font-mono text-text-muted">
                      {t.ticker}
                    </span>
                    <span
                      className="text-[9px] font-mono text-purple/90 bg-purple/10 px-1 rounded"
                      title={t.book}
                    >
                      {bookShort(t.book)}
                    </span>
                    {t.ref_price !== null && (
                      <span className="text-[9px] font-mono text-text-dim">
                        ref {Number(t.ref_price).toFixed(2)}
                      </span>
                    )}
                    <span className="text-[9px] font-mono text-text-dim">
                      {t.direction}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 text-[9px] font-mono">
                    <span className="text-text-dim">
                      {t.predicate_count} preds
                    </span>
                    {t.fired_count > 0 && (
                      <span className="text-danger font-bold">
                        {t.fired_count} fired
                      </span>
                    )}
                    {t.approaching_count > 0 && (
                      <span className="text-amber">
                        {t.approaching_count} near
                      </span>
                    )}
                    {t.error && (
                      <span className="text-danger" title={t.error}>
                        err
                      </span>
                    )}
                  </div>

                  {isOpen && (
                    <div className="mt-1 space-y-0.5">
                      {detail ? (
                        detail.predicates.map((p) => (
                          <div
                            key={p.id}
                            className={`px-1 py-0.5 text-[10px] font-mono rounded ${STATE_ACCENT[p.state]} bg-elevated/40`}
                          >
                            <div className="flex items-center gap-1 flex-wrap">
                              <span
                                className={`text-[8px] font-semibold px-1 py-px rounded ${STATE_BADGE[p.state]}`}
                              >
                                {STATE_LABEL[p.state]}
                              </span>
                              <span className="text-text-primary truncate">
                                {p.description}
                              </span>
                              {!p.load_bearing && (
                                <span className="text-[8px] text-text-dim italic">
                                  supporting
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 text-[9px] text-text-dim mt-px">
                              <span>actual: {formatActual(p)}</span>
                              {p.note && (
                                <span className="text-warning">{p.note}</span>
                              )}
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-[10px] text-text-dim font-mono">
                          loading predicates...
                        </div>
                      )}
                      <button
                        onClick={() => openKill(t.trade_id)}
                        className="w-full mt-1 flex items-center justify-center gap-1 text-[10px] font-mono text-danger hover:bg-danger/10 border border-danger/40 rounded py-1"
                        title="Close this trade and record a KILL event in the ledger"
                      >
                        <AlertOctagon size={11} />
                        Kill trade
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Kill confirmation modal */}
      {confirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          onClick={() => !confirm.sending && setConfirm(null)}
          role="dialog"
          aria-modal="true"
          aria-label="Confirm trade kill"
        >
          <div className="absolute inset-0 bg-void/70" />
          <div
            className="relative bg-surface border border-danger/50 rounded shadow-2xl w-full max-w-sm"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-3 py-2 border-b border-border">
              <h2 className="font-mono text-xs text-danger font-semibold">
                Kill {confirm.trade_id}
              </h2>
              <button
                onClick={() => !confirm.sending && setConfirm(null)}
                className="text-text-dim hover:text-text-primary"
                aria-label="Cancel"
                disabled={confirm.sending}
              >
                <X size={12} />
              </button>
            </div>
            <div className="px-3 py-2 space-y-2">
              <p className="text-[11px] text-text-primary leading-snug">
                This writes a <code className="text-amber">KILL</code> row to the
                trade ledger and removes it from <code className="text-amber">open_trades.json</code>.
                Not reversible.
              </p>
              <div>
                <label className="block text-[10px] text-text-dim font-mono mb-0.5">
                  Type <span className="text-danger">KILL</span> to confirm
                </label>
                <input
                  className="input w-full"
                  value={confirm.confirmText}
                  onChange={(e) =>
                    setConfirm({ ...confirm, confirmText: e.target.value, error: null })
                  }
                  placeholder="KILL"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-[10px] text-text-dim font-mono mb-0.5">
                  Reason (recorded in ledger)
                </label>
                <textarea
                  className="input w-full"
                  rows={2}
                  value={confirm.reason}
                  onChange={(e) =>
                    setConfirm({ ...confirm, reason: e.target.value, error: null })
                  }
                  placeholder="e.g. thesis invalidated by OPEC+ meeting outcome"
                />
              </div>
              {confirm.error && (
                <div className="text-[10px] font-mono text-danger">{confirm.error}</div>
              )}
              <div className="flex justify-end gap-1">
                <button
                  onClick={() => setConfirm(null)}
                  className="btn-secondary"
                  disabled={confirm.sending}
                >
                  Cancel
                </button>
                <button
                  onClick={submitKill}
                  disabled={
                    confirm.sending ||
                    confirm.confirmText !== "KILL" ||
                    confirm.reason.trim().length === 0
                  }
                  className="px-2 py-1 text-[10px] font-mono bg-danger/20 text-danger border border-danger/50 rounded hover:bg-danger/30 disabled:opacity-40"
                >
                  {confirm.sending ? "killing..." : "Confirm kill"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// WHY local helper instead of importing: api.ts's apiFetch throws on
// non-2xx. The kill flow specifically expects a 409 on the first call
// (to receive the confirm token), so we need direct control over the
// response handling. Keep the auth lookup inline and tiny.
function authHeaders(): Record<string, string> {
  const token = getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}
