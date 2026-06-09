// Dialectic — Cockpit (situation board): cascade · open position + load-bearing
// predicates + two-step TERMINATE · signals by phase · deadlines · scenarios ·
// feed freshness. All live from the thesis snapshot + trade lifecycle API.

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertOctagon } from "lucide-react";
import type { OpenTradeDetail, ThesisState, TradePredicate } from "../../lib/types";
import {
  confirmKill,
  PHASE_HINT,
  PHASE_NAMES,
  phaseColorVar,
  requestKillToken,
} from "./data";

const NODE_STATE: Record<string, { cls: string; lab: string }> = {
  fired: { cls: "t-fired", lab: "FIRED" },
  approaching: { cls: "t-approaching", lab: "NEAR" },
  stable: { cls: "t-stable", lab: "STABLE" },
  monitoring: { cls: "t-monitoring", lab: "WATCH" },
  active: { cls: "t-monitoring", lab: "WATCH" },
  gated: { cls: "t-gated", lab: "GATED" },
  resolved: { cls: "t-resolved", lab: "RESOLVED" },
  partial: { cls: "t-resolved", lab: "PARTIAL" },
};
const PRED_STATE: Record<string, string> = { fired: "FIRED", approaching: "NEAR", stable: "STABLE", inactive: "MISSING" };

function fmtDays(d: number): string {
  if (d < 1) return Math.max(1, Math.round(d * 24)) + "h";
  return Math.floor(d) + "d";
}
function cdClass(d: number): string { return d <= 1 ? "urgent" : d <= 3 ? "soon" : d <= 7 ? "near" : "far"; }
function nodeState(s: string | undefined): { cls: string; lab: string } { return NODE_STATE[s || "monitoring"] || NODE_STATE.monitoring; }

type NodeFilter = "all" | "moving" | "fired" | "approaching" | "stable";

interface Props {
  state: ThesisState | null;
  structure: Record<string, { phase: number; label: string }>;
  trade: OpenTradeDetail | null;
  onKilled: () => void;
  /** route assigns flashNode here so room COMMIT clicks can pulse a node */
  flashRef?: React.MutableRefObject<((id: string) => void) | null>;
}

export default function DialecticCockpit({ state, structure, trade, onKilled, flashRef }: Props) {
  const [filter, setFilter] = useState<NodeFilter>("all");
  const [flashId, setFlashId] = useState<string | null>(null);
  const padRef = useRef<HTMLDivElement>(null);
  // Tick once a minute so feed-freshness ages stay accurate without reading
  // the impure Date.now() during render.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (flashRef) {
      flashRef.current = (id: string) => {
        if (filter !== "all") setFilter("all");
        setFlashId(id);
        requestAnimationFrame(() => {
          const el = padRef.current?.querySelector(`.nd[data-id="${id}"]`) as HTMLElement | null;
          if (el && padRef.current) padRef.current.scrollTop = Math.max(0, el.offsetTop - padRef.current.clientHeight / 2);
        });
        setTimeout(() => setFlashId(null), 1300);
      };
    }
  }, [flashRef, filter]);

  // ── nodes (merge live state with builder phase/label) ──
  const nodes = useMemo(() => {
    const ids = new Set<string>([...Object.keys(structure), ...Object.keys(state?.nodeStates || {})]);
    return Array.from(ids).map((id) => ({
      id,
      phase: structure[id]?.phase || 1,
      state: (state?.nodeStates || {})[id] || "monitoring",
      conf: (state?.confluenceScores || {})[id] || 0,
    }));
  }, [structure, state]);

  const counts = useMemo(() => {
    const c = { fired: 0, approaching: 0, stable: 0 };
    nodes.forEach((n) => { if (n.state in c) (c as Record<string, number>)[n.state]++; });
    return c;
  }, [nodes]);

  const phase = state?.cascadePhase;
  const countdowns = state ? [...state.countdowns].sort((a, b) => a.daysRemaining - b.daysRemaining) : [];
  const scenarios = useMemo(() => {
    const sc = Object.entries(state?.scenarioImpacts || {}).map(([id, v]) => ({ id, prob: v.probability, impact: v.netImpact }));
    return sc.sort((a, b) => Math.abs(b.prob * b.impact) - Math.abs(a.prob * a.impact));
  }, [state]);
  const feeds = state?.feedFreshness ? Object.values(state.feedFreshness) : [];

  return (
    <aside className="cockpit">
      <div className="cock-pad" ref={padRef}>
        {/* cascade */}
        {phase && (
          <div className="card cascade">
            <div className="sec-h"><span className="lbl">Cascade</span><span className="stamp flat s-amber" style={{ fontSize: 9, padding: "2px 6px" }}>{phase.status}</span></div>
            <div className="ribbon">
              <div className="here" style={{ left: `calc(${((phase.number - 0.5) / 5) * 100}% - 26px)` }}>we are here ↓</div>
              <div className="segs">
                {[1, 2, 3, 4, 5].map((n) => (
                  <span key={n} className={`s ${n === phase.number ? "cur" : ""}`}
                    title={`${n}. ${PHASE_NAMES[n]}`}
                    style={n <= phase.number ? { background: phaseColorVar(n), borderColor: phaseColorVar(n) } : {}} />
                ))}
              </div>
            </div>
            <div className="now"><span className="nm">{phase.number}. {PHASE_NAMES[phase.number] || phase.key}</span><span className="ahead">{5 - phase.number} phase{5 - phase.number === 1 ? "" : "s"} ahead</span></div>
            <div className="hint"><span className="a">→</span>{PHASE_HINT[phase.number]}</div>
          </div>
        )}

        {/* open position */}
        <TradeCard trade={trade} onKilled={onKilled} />

        {/* signals */}
        <div>
          <div className="sec-h"><span className="lbl">Signals · nodes</span></div>
          <div className="nf-row">
            {(["all", "moving", "fired", "approaching", "stable"] as NodeFilter[]).map((f) => {
              const c = f === "all" ? nodes.length : f === "moving" ? counts.fired + counts.approaching : (counts as Record<string, number>)[f] || 0;
              return (
                <span key={f} className={`nf ${filter === f ? "on " + f : ""}`} onClick={() => setFilter(f)}>{f}<span className="c">{c}</span></span>
              );
            })}
          </div>
          <div className="nodes">
            {[1, 2, 3, 4, 5].map((ph) => {
              let ns = nodes.filter((n) => n.phase === ph);
              if (filter !== "all") ns = ns.filter((n) => (filter === "moving" ? n.state === "fired" || n.state === "approaching" : n.state === filter));
              if (!ns.length) return null;
              return (
                <div className="phase-grp" key={ph}>
                  <div className="pg-h">P{ph} · {PHASE_NAMES[ph]}</div>
                  {ns.map((n) => {
                    const s = nodeState(n.state);
                    return (
                      <div key={n.id} className={`nd ${n.state} ${flashId === n.id ? "flash" : ""}`} data-id={n.id}>
                        <span className="id">{n.id}</span>
                        {n.conf > 1 && <span className="cf">×{n.conf.toFixed(1)}</span>}
                        <span className={`tag ${s.cls}`}>{s.lab}</span>
                      </div>
                    );
                  })}
                </div>
              );
            })}
            {nodes.length === 0 && <div className="empty">No nodes in snapshot.</div>}
          </div>
        </div>

        {/* deadlines */}
        {countdowns.length > 0 && (
          <div>
            <div className="sec-h"><span className="lbl">Deadlines</span></div>
            {countdowns.map((c) => (
              <div className="cd" key={c.nodeId}><span className="t">{c.label || c.nodeId}</span><span className={`d ${cdClass(c.daysRemaining)}`}>{fmtDays(c.daysRemaining)}</span></div>
            ))}
          </div>
        )}

        {/* scenarios */}
        {scenarios.length > 0 && (
          <div>
            <div className="sec-h"><span className="lbl">Scenarios</span><span className="lbl" style={{ letterSpacing: ".04em", color: "var(--ghost)" }}>prob × impact</span></div>
            {scenarios.map((s) => {
              const pos = s.impact >= 0;
              const mx = Math.max(...scenarios.map((x) => Math.abs(x.impact)), 1);
              return (
                <div key={s.id} style={{ padding: "3px 4px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 10.5, color: "var(--ink)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.id}</span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 9, color: "var(--faint)" }}>{Math.round(s.prob * 100)}%</span>
                    <span style={{ fontFamily: "var(--mono)", fontSize: 11, fontWeight: 600, width: 34, textAlign: "right", color: pos ? "var(--teal)" : "var(--scarlet)" }}>{pos ? "+" : ""}{s.impact.toFixed(1)}</span>
                  </div>
                  <div style={{ height: 3, background: "var(--void)", border: "1px solid var(--bean)", marginTop: 3, overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${Math.min(100, (Math.abs(s.impact) / mx) * 100)}%`, background: pos ? "var(--teal)" : "var(--scarlet)", opacity: 0.7 }} />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* feeds */}
        {feeds.length > 0 && (
          <div className="card">
            <div className="sec-h"><span className="lbl">Feeds</span><span className="lbl" style={{ letterSpacing: ".04em", color: "var(--ghost)" }}>stale &gt; ttl</span></div>
            <div className="feeds">
              {feeds.map((f) => {
                const stale = now - Date.parse(f.fetchedAt) > f.ttlSeconds * 1000;
                const age = Math.max(0, Math.round((now - Date.parse(f.fetchedAt)) / 1000));
                const ageLabel = age < 60 ? `${age}s` : age < 3600 ? `${Math.round(age / 60)}m` : `${Math.round(age / 3600)}h`;
                return (
                  <span key={f.source} className={`feed ${stale ? "stale" : "fresh"}`}>
                    <span className="s">{f.source}</span><span>{ageLabel}</span>{stale && <span style={{ fontSize: 7, letterSpacing: ".1em" }}>STALE</span>}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

// ── open position card + TERMINATE flow ──
function TradeCard({ trade, onKilled }: { trade: OpenTradeDetail | null; onKilled: () => void }) {
  const [modal, setModal] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [reason, setReason] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [ttl, setTtl] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [killed, setKilled] = useState(false);
  const [busy, setBusy] = useState(false);
  const ttlRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (ttlRef.current) clearInterval(ttlRef.current); }, []);

  if (!trade) {
    return (
      <div className="card trade">
        <div className="sec-h"><span className="lbl">Open position</span></div>
        <div className="empty">No open trade for this case.</div>
      </div>
    );
  }

  const fired = trade.predicates.filter((p) => p.state === "fired").length;
  const near = trade.predicates.filter((p) => p.state === "approaching").length;
  const cls = killed ? "" : fired ? "fired" : near ? "warn" : "";
  const armed = fired > 0 && !killed;

  function reset() {
    setModal(false); setConfirmText(""); setReason(""); setToken(null); setTtl(0); setErr(null); setBusy(false);
    if (ttlRef.current) clearInterval(ttlRef.current);
  }
  function valid() { return confirmText === "KILL" && reason.trim().length > 0; }

  async function go() {
    if (!trade) return;
    if (!valid()) { setErr("Type KILL and a reason."); return; }
    setBusy(true); setErr(null);
    try {
      if (!token) {
        const tok = await requestKillToken(trade.trade_id, reason.trim());
        setToken(tok); setTtl(15); setBusy(false);
        if (ttlRef.current) clearInterval(ttlRef.current);
        ttlRef.current = setInterval(() => {
          setTtl((t) => {
            if (t <= 1) { if (ttlRef.current) clearInterval(ttlRef.current); setToken(null); setErr("Token expired — request again."); return 0; }
            return t - 1;
          });
        }, 1000);
        return;
      }
      await confirmKill(trade.trade_id, reason.trim(), token);
      if (ttlRef.current) clearInterval(ttlRef.current);
      setKilled(true); reset(); onKilled();
    } catch (e) {
      setBusy(false);
      setErr(e instanceof Error ? e.message : "kill failed");
    }
  }

  return (
    <div className={`card trade ${cls}`}>
      <div className="sec-h"><span className="lbl">Open position</span><span className="meta">{trade.direction?.toUpperCase()}{trade.ref_price != null ? ` · ref ${Number(trade.ref_price).toFixed(2)}` : ""}</span></div>
      <div className="th"><span className="tid">{trade.trade_id}</span><span className="tk">{trade.ticker}</span><span className="bk">{trade.book}</span></div>
      <div className="summ">
        <span>{trade.predicates.length} predicates</span>
        {fired > 0 && <span className="fired">{fired} fired</span>}
        {near > 0 && <span className="near">{near} near</span>}
        {fired === 0 && near === 0 && <span className="stable">all stable</span>}
      </div>
      <div className="preds">
        {trade.predicates.map((p: TradePredicate) => (
          <div key={p.id} className={`pred ${p.state}`}>
            <div className="l1">
              <span className={`tag t-${p.state === "inactive" ? "monitoring" : p.state}`}>{PRED_STATE[p.state]}</span>
              <span className="pd">{p.description}</span>
              {p.load_bearing ? <span className="key" title="load-bearing">◆ LB</span> : <span className="sup">supporting</span>}
            </div>
            <div className="l2"><span>actual: {p.actual ?? "—"}</span>{p.note && <span className="pwarn">{p.note}</span>}</div>
          </div>
        ))}
      </div>
      <button className={`killbtn ${armed ? "armed" : ""}`} disabled={killed} onClick={() => setModal(true)}>
        {killed ? "✓ TERMINATED" : (<>{armed ? "⚠ " : ""}<AlertOctagon size={12} /> {armed ? "TERMINATE ORDER" : "Kill position"}</>)}
      </button>

      {modal && (
        <div className="scrim" onClick={(e) => { if (e.target === e.currentTarget && !busy) reset(); }}>
          <div className="modal">
            <div className="mh"><h2>Kill {trade.trade_id}</h2><p>writes a KILL row to the trade ledger · not reversible</p></div>
            <div className="mb">
              <p className="txt">This closes <code>{trade.ticker}</code> and removes it from <code>open_trades.json</code>.{armed ? " The reversal predicate has fired — the tail thesis is invalidated." : ""}</p>
              <div><label>Type KILL to confirm</label><input value={confirmText} onChange={(e) => { setConfirmText(e.target.value); setErr(null); }} placeholder="KILL" autoFocus autoComplete="off" /></div>
              <div><label>Reason (recorded in ledger)</label><textarea rows={2} value={reason} onChange={(e) => { setReason(e.target.value); setErr(null); }} placeholder="e.g. SPR release fired the load-bearing reversal" /></div>
              {token && <div className="token">confirm token <b>{token}</b><span>expires {ttl}s</span></div>}
              {err && <div className="err">{err}</div>}
              <div className="acts">
                <button className="btn-x" onClick={reset} disabled={busy}>Cancel</button>
                <button className="btn-kill" onClick={go} disabled={busy || !valid()}>{busy ? "working…" : token ? "Confirm kill" : "Request termination"}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
