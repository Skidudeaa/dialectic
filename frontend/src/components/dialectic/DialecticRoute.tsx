// Dialectic — Field Desk shell. New lazy route (/dialectic) that composes the
// case rail + room (hero) + situation board against the live backend. The
// dossier aesthetic (Dark Roast, stamps, typed dispatches) is faithful to the
// Claude Design handoff; the data is real (rooms, messages, thesis, trades,
// predictions, presence).

import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { clearAuth } from "../../lib/api";
import "./dialectic.css";
import DialecticRoom from "./DialecticRoom";
import DialecticCockpit from "./DialecticCockpit";
import {
  ANALYSTS,
  DISTANCE_KM,
  me as getMe,
  PHASE_NAMES,
  phaseColorVar,
  useBookTrade,
  usePredictions,
  usePresence,
  useRoomsAndBooks,
  useThesis,
} from "./data";

function hueOf(id: string): string { return id === "amo" ? "var(--amber)" : "var(--teal)"; }

export default function DialecticRoute() {
  const me = getMe();
  const { rooms, books, loading } = useRoomsAndBooks();
  const [activeBookId, setActiveBookId] = useState<string | null>(null);
  const presence = usePresence();
  const flashRef = useRef<((id: string) => void) | null>(null);

  // Default the active case to the first book that has a room linked to it,
  // else the first book.
  useEffect(() => {
    if (activeBookId || !books.length) return;
    const linked = books.find((b) => rooms.some((r) => r.linked_book_id === b.id));
    // One-shot default once books/rooms arrive; not derivable as a memo.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setActiveBookId((linked || books[0]).id);
  }, [books, rooms, activeBookId]);

  const activeRoom = useMemo(
    () => rooms.find((r) => r.linked_book_id === activeBookId) || rooms[0] || null,
    [rooms, activeBookId],
  );

  const { state, structure, claim, title } = useThesis(activeBookId);
  const { detail: trade, reload: reloadTrade } = useBookTrade(activeBookId);
  const predictions = usePredictions(activeBookId);

  // clock + latency (cosmetic — wire health shown by the live indicator)
  const [clock, setClock] = useState("—");
  const [latency, setLatency] = useState(7);
  useEffect(() => {
    const t = setInterval(() => {
      setClock(new Date().toTimeString().slice(0, 8));
      setLatency(4 + Math.floor(Math.random() * 12));
    }, 1000);
    return () => clearInterval(t);
  }, []);

  function logout() { clearAuth(); window.location.assign("/"); }

  // presence helpers
  const statusOf = (uid: string): "thinking" | "online" | "offline" => {
    const u = presence.find((p) => p.user_id === uid && p.kind === "human");
    if (!u) return "offline";
    return u.status === "thinking" ? "thinking" : "online";
  };
  const agentThinking = presence.some((p) => p.kind === "agent" && p.status === "thinking");
  const hereOn = (bookId: string): string[] =>
    presence.filter((p) => p.kind === "human" && p.book_id === bookId).map((p) => p.user_id);

  return (
    <div className="dlx">
      <div className="app">
        {/* ── topbar ── */}
        <header className="topbar">
          <div className="brand">
            <span className="seal">◆</span>
            <span className="wm"><span className="t">DIALECTIC</span><span className="s">FIELD&nbsp;DESK</span></span>
            <span className="case">CASE · {(activeBookId || "—").toUpperCase()}<br /><b>EYES ONLY</b></span>
          </div>

          <div className="dyad">
            <Who id="amo" status={statusOf("amo")} side="left" />
            <div className="link"><span className="dist">{DISTANCE_KM}</span><div className="wire"><span className="pkt" /></div></div>
            <Who id="dan" status={statusOf("dan")} side="right" />
            <div className="agents">
              <div className={`av agent ${agentThinking ? "think" : ""}`} title="claude-sonnet-4.6">cl<span className={`st ${agentThinking ? "thinking" : ""}`} /></div>
              <div className="av agent" title="gpt-5.3-chat">gp<span className="st" /></div>
            </div>
          </div>

          <div className="top-right">
            <Link to="/" className="clock" style={{ color: "var(--secondary)" }} title="Back to the classic desk">← desk</Link>
            <div className="telex"><span className="d" /><b>WIRE LIVE</b><span>{latency}ms</span></div>
            <span className="clock">{clock}</span>
          </div>
        </header>

        {/* ── main grid ── */}
        <main className="main">
          {/* left rail */}
          <aside className="rail">
            <div className="rail-h"><span className="lbl">Open cases</span><button className="plus" title="Open a new case">+</button></div>
            <div className="books">
              {books.map((b) => {
                const on = b.id === activeBookId;
                const ph = on && state?.cascadePhase ? state.cascadePhase.number : null;
                const here = hereOn(b.id);
                const confVals = on ? Object.values(state?.confluenceScores || {}) : [];
                const conf = confVals.length ? Math.min(1, Math.max(...confVals) / 3) : 0;
                return (
                  <button key={b.id} className={`book ${on ? "on" : ""}`} onClick={() => setActiveBookId(b.id)}>
                    <div className="top">
                      <span className="ph" style={{ background: ph ? phaseColorVar(ph) : "var(--faint)" }} />
                      <span className="ttl">{b.title}</span>
                    </div>
                    <div className="sub">
                      <span>{ph ? `PH ${ph} · ${PHASE_NAMES[ph]}` : `${b.nodes} nodes · ${b.edges} edges`}</span>
                      <span className="here">{here.map((u) => <i key={u} style={{ background: hueOf(u) }} />)}</span>
                    </div>
                    {on && conf > 0 && <div className="conf"><i style={{ width: `${Math.round(conf * 100)}%`, background: ph ? phaseColorVar(ph) : "var(--amber)" }} /></div>}
                  </button>
                );
              })}
              {loading && <div className="empty" style={{ padding: "8px 10px" }}>loading cases…</div>}
            </div>

            <div className="rail-sec">
              <span className="lbl">Standing bets</span>
              <div>
                {predictions.slice(0, 6).map((p) => {
                  const won = p.resolution === "correct";
                  const live = !p.resolution;
                  // Confidence is stored 0–1 (JSONL) or 0–100 (v2 store) depending
                  // on age; normalise both to a percentage.
                  const raw = p.confidence || 0;
                  const pct = Math.round(raw <= 1 ? raw * 100 : raw);
                  return (
                    <div className="bet" key={p.id}>
                      <span className={`mk ${won ? "won" : live ? "live" : ""}`}>{won ? "✓" : live ? "◷" : "—"}</span>
                      <span className="pc">{pct}%</span>
                      <span className="tx">{p.statement}</span>
                    </div>
                  );
                })}
                {predictions.length === 0 && <div className="empty">No standing bets.</div>}
              </div>
            </div>

            <div className="rail-foot">
              <div className="av me" style={{ width: 26, height: 26 }}>{(ANALYSTS[me || ""]?.initial) || (me || "?")[0]?.toUpperCase()}</div>
              <div className="who-id"><span className="n">{(ANALYSTS[me || ""]?.name || me || "operator").toUpperCase()}</span><span className="s">Desk officer</span></div>
              <button className="logout" title="Sign out" onClick={logout}>⏻</button>
            </div>
          </aside>

          {/* room (hero) */}
          {activeRoom ? (
            <DialecticRoom
              key={activeRoom.id}
              room={activeRoom}
              bookId={activeBookId}
              title={title}
              claim={claim}
              state={state}
              onFlashNode={(id) => flashRef.current?.(id)}
            />
          ) : (
            <section className="room"><div className="room-h"><div className="kicker">no case open</div><div className="l1"><span className="title">{loading ? "Opening the file…" : "No rooms found"}</span></div></div></section>
          )}

          {/* situation board */}
          <DialecticCockpit
            state={state}
            structure={structure}
            trade={trade}
            onKilled={reloadTrade}
            flashRef={flashRef}
          />
        </main>
      </div>
    </div>
  );
}

function Who({ id, status, side }: { id: string; status: "thinking" | "online" | "offline"; side: "left" | "right" }) {
  const a = ANALYSTS[id];
  if (!a) return null;
  const dot = status === "thinking" ? "thinking" : status === "online" ? "online" : "";
  const av = (
    <div className={`av ${a.cls} ${status === "thinking" ? "think" : ""}`}>{a.initial}<span className={`st ${dot}`} /></div>
  );
  const meta = (
    <div className="meta" style={side === "right" ? { textAlign: "right", alignItems: "flex-end" } : undefined}>
      <span className="n">{a.name.toUpperCase()}</span><span className="c">{a.city}</span>
    </div>
  );
  return <div className="who">{side === "left" ? (<>{av}{meta}</>) : (<>{meta}{av}</>)}</div>;
}
