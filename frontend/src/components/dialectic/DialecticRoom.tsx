// Dialectic — the Room (hero): a dispatch-log stream + dispatch-desk composer,
// wired to live rooms/messages/WebSocket/LLM. Real messages are mapped onto
// the dossier vocabulary: user → typed memo (signed), llm → ANALYSIS block,
// system → COMMIT ledger line.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Paperclip, FileCode2, X } from "lucide-react";
import { apiFetch, RoomSocket } from "../../lib/api";
import type { ArticleMeta, CodeExhibitMeta, Message, Room, ThesisState, TVAlertWSPayload, WSMessage } from "../../lib/types";
import { ANALYSTS, modelBadge, shortModel } from "./data";

const MENTIONS = [
  { key: "claude", label: "@claude", desc: "Anthropic Claude — long-context reasoning", cls: "var(--amber)" },
  { key: "gpt", label: "@gpt", desc: "OpenAI GPT — broad general", cls: "var(--sev-stable)" },
  { key: "gemini", label: "@gemini", desc: "Google Gemini — fast multimodal", cls: "var(--teal)" },
  { key: "deepseek", label: "@deepseek", desc: "DeepSeek R1 — chain-of-thought", cls: "var(--sev-worse)" },
  { key: "compare", label: "@compare", desc: "Run claude + gpt + gemini side-by-side", cls: "var(--teal)" },
];
const SLASH = [
  { cmd: "/brief", desc: "Post the morning brief into the file" },
  { cmd: "/thesis", desc: "Stamp phase, fired/approaching nodes, top confluence" },
  { cmd: "/diff", desc: "Re-fetch live prices for the linked book" },
  { cmd: "/predict", desc: "Log a prediction with confidence + 30d deadline" },
  { cmd: "/watchlist", desc: "Dump current market watchlist" },
];
const MODEL_MAP: Record<string, string> = {
  claude: "anthropic/claude-sonnet-4.6",
  gpt: "openai/gpt-5.3-chat",
  deepseek: "deepseek/deepseek-r1",
  gemini: "google/gemini-3.1-pro-preview",
};

function clk(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toTimeString().slice(0, 5);
}
function dayLabel(iso: string): string {
  const d = new Date(iso), n = new Date();
  const a = new Date(n.getFullYear(), n.getMonth(), n.getDate());
  const b = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dd = Math.round((a.getTime() - b.getTime()) / 86400000);
  if (dd === 0) return "TODAY · " + d.toLocaleDateString([], { month: "short", day: "numeric" }).toUpperCase();
  if (dd === 1) return "YESTERDAY";
  if (dd < 7) return d.toLocaleDateString([], { weekday: "long" }).toUpperCase();
  return d.toLocaleDateString([], { month: "short", day: "numeric" }).toUpperCase();
}
function sameDay(a: string, b: string): boolean {
  const da = new Date(a), db = new Date(b);
  return da.getFullYear() === db.getFullYear() && da.getMonth() === db.getMonth() && da.getDate() === db.getDate();
}
// Escape then re-introduce only our own markup → XSS-safe rich text for memos.
function rich(text: string): string {
  let s = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  s = s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/(^|\s)(@(?:claude|gpt|gemini|deepseek|compare))\b/g, '$1<span class="m">$2</span>');
  return s;
}

// Signal telex line — a Pine alert that just hit the webhook, surfaced live in
// the dispatch stream. Ephemeral by design (the durable record is the TV audit
// log); FLASH (scarlet) when the alert moved thesis state, CONFIRM (teal) for
// routine telemetry like a closesObserved increment.
interface TVFlash {
  id: string;
  ts: string;
  good: boolean;
  text: string;
  nodeId: string;
}

function flashText(p: TVAlertWSPayload): string {
  const head = p.pineAlertName || p.op;
  const sym = p.chartSymbol ? ` · ${p.chartSymbol}` : "";
  const moved = p.thesisStateChanged && p.changedNodes.length ? ` · ${p.changedNodes.join(", ")} moved` : "";
  return `TV alert · ${head}${sym} → ${p.nodeId}${moved}`;
}

interface Props {
  room: Room;
  bookId: string | null;
  /** false when this is a general room standing in for a case with no linked room */
  linked?: boolean;
  title: string;
  claim: string;
  state: ThesisState | null;
  /** lets the cockpit flash a node when a COMMIT line is clicked */
  onFlashNode?: (id: string) => void;
}

export default function DialecticRoom({ room, bookId, linked = true, title, claim, state, onFlashNode }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [alerts, setAlerts] = useState<TVFlash[]>([]);
  const alertSeq = useRef(0);
  const [input, setInput] = useState("");
  const [typingUsers, setTypingUsers] = useState<Set<string>>(new Set());
  const [popover, setPopover] = useState<null | { kind: "mention" | "slash"; query: string; sel: number }>(null);
  const [showJump, setShowJump] = useState(false);
  // structured-attachment authoring (clipping / code exhibit)
  const [attach, setAttach] = useState<null | "article" | "code">(null);
  const [artForm, setArtForm] = useState<ArticleMeta>({ source: "", title: "", take: "" });
  const [codeForm, setCodeForm] = useState<CodeExhibitMeta>({ fn: "", lang: "", code: "" });

  // streaming (RAF-buffered, mirrors Chat.tsx)
  const [streamDisplay, setStreamDisplay] = useState<Record<string, string>>({});
  const streamRef = useRef<Record<string, string>>({});
  const dirtyRef = useRef(false);
  const rafRef = useRef(0);
  const [pendingLLM, setPendingLLM] = useState<Set<string>>(new Set());

  const socketRef = useRef<RoomSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const followRef = useRef(true);
  const typingTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  // ── RAF flush for streaming tokens ──
  useEffect(() => {
    function flush() {
      if (dirtyRef.current) { dirtyRef.current = false; setStreamDisplay({ ...streamRef.current }); }
      rafRef.current = requestAnimationFrame(flush);
    }
    rafRef.current = requestAnimationFrame(flush);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  // ── load history on room change ──
  useEffect(() => {
    // Reset on room switch then fetch; matches the codebase fetch-on-effect pattern.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMessages([]); setAlerts([]); setPopover(null);
    apiFetch<Message[]>(`/api/rooms/${room.id}/messages?limit=100`).then(setMessages).catch(() => {});
  }, [room.id]);

  // ── socket ──
  useEffect(() => {
    const sock = new RoomSocket(room.id);
    socketRef.current = sock;
    const unsub = sock.subscribe((msg: WSMessage) => {
      if (msg.type === "message") {
        const m = msg.payload as unknown as Message;
        setMessages((prev) => (prev.some((p) => p.id === m.id) ? prev : [...prev, m]));
      } else if (msg.type === "llm_chunk") {
        const { token, model } = msg.payload as { token: string; model: string };
        if (!streamRef.current[model]) {
          setPendingLLM((p) => { const n = new Set(p); n.delete(model); return n; });
        }
        streamRef.current[model] = (streamRef.current[model] || "") + token;
        dirtyRef.current = true;
      } else if (msg.type === "llm_done") {
        const { model } = msg.payload as { model: string };
        delete streamRef.current[model]; dirtyRef.current = true;
        setPendingLLM((p) => { const n = new Set(p); n.delete(model); return n; });
      } else if (msg.type === "typing") {
        const { username, typing } = msg.payload as { username: string; typing: boolean };
        setTypingUsers((prev) => { const n = new Set(prev); if (typing) n.add(username); else n.delete(username); return n; });
      } else if (msg.type === "tv-alert") {
        const p = msg.payload as unknown as TVAlertWSPayload;
        alertSeq.current += 1;
        setAlerts((prev) => [...prev, {
          id: `tv-${alertSeq.current}-${p.bindingId}`,
          ts: new Date().toISOString(),
          good: !p.thesisStateChanged,
          text: flashText(p),
          nodeId: p.nodeId,
        }]);
      }
    });
    return () => { unsub(); sock.close(); socketRef.current = null; if (typingTimer.current) clearTimeout(typingTimer.current); };
  }, [room.id]);

  // ── auto-follow ──
  useEffect(() => {
    if (!followRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, alerts, streamDisplay, pendingLLM]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    followRef.current = near;
    setShowJump(!near);
  }
  function jump() {
    const el = scrollRef.current;
    if (el) { followRef.current = true; el.scrollTop = el.scrollHeight; setShowJump(false); }
  }

  // ── LLM dispatch ──
  const dispatchLLM = useCallback((cmd: string, prompt: string) => {
    if (cmd === "compare") {
      const models = ["anthropic/claude-sonnet-4.6", "openai/gpt-5.3-chat", "google/gemini-3.1-pro-preview"];
      models.forEach((m) => setPendingLLM((p) => new Set(p).add(m)));
      apiFetch("/api/llm/compare", { method: "POST", body: JSON.stringify({ prompt, room_id: room.id }) })
        .catch(() => models.forEach((m) => setPendingLLM((p) => { const n = new Set(p); n.delete(m); return n; })));
    } else {
      const model = MODEL_MAP[cmd];
      if (!model) return;
      setPendingLLM((p) => new Set(p).add(model));
      apiFetch("/api/llm/chat", { method: "POST", body: JSON.stringify({ prompt, model, room_id: room.id }) })
        .catch(() => setPendingLLM((p) => { const n = new Set(p); n.delete(model); return n; }));
    }
  }, [room.id]);

  // ── send ──
  const send = useCallback(async () => {
    const text = input.trim();
    if (!text) return;
    setInput(""); setPopover(null); followRef.current = true;
    if (taRef.current) taRef.current.style.height = "auto";

    if (text.startsWith("/")) {
      const cmd = text.split(/\s+/)[0].toLowerCase();
      if (SLASH.some((s) => s.cmd === cmd)) {
        apiFetch(`/api/rooms/${room.id}/command`, { method: "POST", body: JSON.stringify({ text }) }).catch(() => {});
        return;
      }
    }
    const mm = text.match(/^@(claude|gpt|gemini|deepseek|compare)\s+/i);
    try {
      await apiFetch(`/api/rooms/${room.id}/messages`, { method: "POST", body: JSON.stringify({ content: text }) });
      if (mm) dispatchLLM(mm[1].toLowerCase(), text.slice(mm[0].length));
    } catch { /* surfaced by absence of echo */ }
  }, [input, room.id, dispatchLLM]);

  // ── structured attachments → POST as article/code kinds ──
  const fileArticle = useCallback(async () => {
    if (!artForm.source.trim() || !artForm.title.trim()) return;
    followRef.current = true;
    try {
      await apiFetch(`/api/rooms/${room.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ kind: "article", article: artForm }),
      });
      setArtForm({ source: "", title: "", take: "" });
      setAttach(null);
    } catch { /* surfaced by absence of echo */ }
  }, [artForm, room.id]);

  const fileCode = useCallback(async () => {
    if (!codeForm.fn.trim() || !codeForm.code.trim()) return;
    followRef.current = true;
    try {
      await apiFetch(`/api/rooms/${room.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ kind: "code", code: codeForm }),
      });
      setCodeForm({ fn: "", lang: "", code: "" });
      setAttach(null);
    } catch { /* surfaced by absence of echo */ }
  }, [codeForm, room.id]);

  // ── composer popover ──
  const popItems = useMemo(() => {
    if (!popover) return [] as Array<{ label: string; desc: string; cls?: string }>;
    return popover.kind === "mention"
      ? MENTIONS.filter((m) => m.key.startsWith(popover.query)).map((m) => ({ label: m.label, desc: m.desc, cls: m.cls }))
      : SLASH.filter((c) => c.cmd.slice(1).startsWith(popover.query)).map((c) => ({ label: c.cmd, desc: c.desc, cls: "var(--amber)" }));
  }, [popover]);

  function onInput(v: string) {
    setInput(v);
    socketRef.current?.sendTyping(true);
    if (typingTimer.current) clearTimeout(typingTimer.current);
    typingTimer.current = setTimeout(() => socketRef.current?.sendTyping(false), 2000);
    if (v.startsWith("@") && !/\s/.test(v.slice(1))) setPopover({ kind: "mention", query: v.slice(1).toLowerCase(), sel: 0 });
    else if (v.startsWith("/") && !/\s/.test(v.slice(1))) setPopover({ kind: "slash", query: v.slice(1).toLowerCase(), sel: 0 });
    else setPopover(null);
  }
  function applyPop(i: number) {
    const it = popItems[i];
    if (!it) return;
    setInput(it.label + " "); setPopover(null); taRef.current?.focus();
  }
  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (popover && popItems.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); setPopover({ ...popover, sel: (popover.sel + 1) % popItems.length }); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setPopover({ ...popover, sel: (popover.sel - 1 + popItems.length) % popItems.length }); return; }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) { e.preventDefault(); applyPop(popover.sel); return; }
      if (e.key === "Escape") { e.preventDefault(); setPopover(null); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  // ── render rows (day dividers + entries + signal telex, merged by ts) ──
  const rows = useMemo(() => {
    const merged: Array<{ ts: string; m?: Message; a?: TVFlash }> = [
      ...messages.map((m) => ({ ts: m.ts, m })),
      ...alerts.map((a) => ({ ts: a.ts, a })),
    ].sort((x, y) => Date.parse(x.ts) - Date.parse(y.ts));
    const out: Array<
      | { kind: "day"; label: string; key: string }
      | { kind: "msg"; m: Message; ix: number }
      | { kind: "tv"; a: TVFlash; ix: number }
    > = [];
    let prev: string | null = null;
    let ix = 0;
    for (const e of merged) {
      if (!prev || !sameDay(prev, e.ts)) out.push({ kind: "day", label: dayLabel(e.ts), key: "d" + e.ts });
      ix++;
      if (e.m) out.push({ kind: "msg", m: e.m, ix });
      else if (e.a) out.push({ kind: "tv", a: e.a, ix });
      prev = e.ts;
    }
    return out;
  }, [messages, alerts]);

  const phase = state?.cascadePhase;
  const typingList = Array.from(typingUsers).filter((u) => u !== (ANALYSTS.amo ? "amo" : ""));

  return (
    <section className="room">
      {/* room head */}
      <div className="room-h">
        <span className="stamp s-amber classify">EYES ONLY</span>
        <div className="kicker">
          {linked
            ? `${bookId || room.name} · case file`
            : `${room.name} · general dispatches — no room linked to this case`}
        </div>
        <div className="l1"><span className="title">{title || room.name}</span></div>
        {claim && <div className="claim">{claim}</div>}
        {phase && (
          <div className="ribbon">
            {[1, 2, 3, 4, 5].map((n) => {
              const reached = n <= phase.number;
              const cur = n === phase.number;
              const col = n >= 4 ? "var(--teal)" : n >= 3 ? "var(--scarlet)" : "var(--amber)";
              return (
                <span key={n} className="seg"
                  style={{
                    ...(reached ? { background: col, borderColor: col } : {}),
                    ...(cur ? { boxShadow: "0 0 0 1px var(--amber-30)" } : {}),
                  }} />
              );
            })}
            <span className="pn">{phase.number}. {phase.key}</span>
          </div>
        )}
      </div>

      {/* stream */}
      <div className="stream-wrap">
        <div className="stream" ref={scrollRef} onScroll={onScroll}>
          {rows.map((r) =>
            r.kind === "day" ? (
              <div className="day" key={r.key}><span className="ln" /><span className="t">{r.label}</span><span className="ln" /></div>
            ) : r.kind === "tv" ? (
              <div className="disp k-sys" key={r.a.id}>
                <div className="gut"><span className="tm">{clk(r.a.ts)}</span><span className="ix">#{String(r.ix).padStart(3, "0")}</span></div>
                <div className="entry">
                  <div className={`flash ${r.a.good ? "good" : ""}`} style={{ cursor: "pointer" }}
                    title="Flash node on the board" onClick={() => onFlashNode?.(r.a.nodeId)}>
                    <span className="pre">{r.a.good ? "CONFIRM" : "FLASH"}</span><span>{r.a.text}</span>
                  </div>
                </div>
              </div>
            ) : (
              <Dispatch key={r.m.id} m={r.m} ix={r.ix} onFlashNode={onFlashNode} />
            ),
          )}
          {/* thinking placeholders */}
          {Array.from(pendingLLM).filter((m) => !streamDisplay[m]).map((model) => (
            <div className="disp" key={"think-" + model}>
              <div className="gut"><span className="tm">now</span></div>
              <div className="entry">
                <div className="ehead"><span className="analysis-tag">▸ analysis</span><span className={`mbadge ${modelBadge(model)}`}>{shortModel(model)}</span></div>
                <div className="thinking">reasoning<span className="dots"><i /><i /><i /></span></div>
              </div>
            </div>
          ))}
          {/* live streaming */}
          {Object.entries(streamDisplay).map(([model, text]) => (
            <div className="disp" key={"stream-" + model}>
              <div className="gut"><span className="tm">now</span></div>
              <div className="entry">
                <div className="ehead"><span className="analysis-tag">▸ analysis</span><span className={`mbadge ${modelBadge(model)}`}>{shortModel(model)}</span></div>
                <div className="etext" dangerouslySetInnerHTML={{ __html: rich(text) }} />
                <span className="caret" />
              </div>
            </div>
          ))}
        </div>
        {showJump && <button className="jump" onClick={jump}>↓ latest</button>}
      </div>

      {/* composer */}
      <div className="composer">
        <div className="typing">
          {typingList.length > 0 && (<><span className="d" />{typingList.join(", ")} is typing…</>)}
        </div>
        {popover && popItems.length > 0 && (
          <div className="pop">
            <div className="ph"><span>{popover.kind === "mention" ? "Task an agent" : "Command"}</span><span style={{ textTransform: "none", letterSpacing: 0 }}>↑↓ · ↵ pick · esc</span></div>
            {popItems.map((it, i) => (
              <div key={it.label} className={`it ${i === popover.sel ? "sel" : ""}`}
                onMouseEnter={() => setPopover({ ...popover, sel: i })} onClick={() => applyPop(i)}>
                <span className="k" style={{ color: it.cls }}>{it.label}</span>
                <span className="d">{it.desc}</span>
              </div>
            ))}
          </div>
        )}
        {/* structured-attachment authoring panel */}
        {attach === "article" && (
          <div className="attach">
            <div className="ah"><span><Paperclip size={11} /> File a clipping</span><button onClick={() => setAttach(null)} aria-label="Close"><X size={12} /></button></div>
            <input placeholder="source · e.g. reuters.com" value={artForm.source} onChange={(e) => setArtForm({ ...artForm, source: e.target.value })} autoFocus />
            <input placeholder="headline / title" value={artForm.title} onChange={(e) => setArtForm({ ...artForm, title: e.target.value })} />
            <textarea rows={2} placeholder="your take (optional)" value={artForm.take} onChange={(e) => setArtForm({ ...artForm, take: e.target.value })} />
            <div className="aacts"><button className="btn-x" onClick={() => setAttach(null)}>Cancel</button><button className="afile" onClick={fileArticle} disabled={!artForm.source.trim() || !artForm.title.trim()}>FILE CLIPPING</button></div>
          </div>
        )}
        {attach === "code" && (
          <div className="attach">
            <div className="ah"><span><FileCode2 size={11} /> File an exhibit</span><button onClick={() => setAttach(null)} aria-label="Close"><X size={12} /></button></div>
            <div className="arow">
              <input placeholder="filename · e.g. reroute.py" value={codeForm.fn} onChange={(e) => setCodeForm({ ...codeForm, fn: e.target.value })} autoFocus />
              <input className="lang" placeholder="lang" value={codeForm.lang} onChange={(e) => setCodeForm({ ...codeForm, lang: e.target.value })} />
            </div>
            <textarea className="codearea" rows={5} placeholder="paste code…" value={codeForm.code} onChange={(e) => setCodeForm({ ...codeForm, code: e.target.value })} spellCheck={false} />
            <div className="aacts"><button className="btn-x" onClick={() => setAttach(null)}>Cancel</button><button className="afile" onClick={fileCode} disabled={!codeForm.fn.trim() || !codeForm.code.trim()}>FILE EXHIBIT</button></div>
          </div>
        )}

        <div className="cbox">
          <span className="pfx">{(ANALYSTS.amo?.initial || "A")}&nbsp;»</span>
          <div className="ctools">
            <button className={`ctool ${attach === "article" ? "on" : ""}`} title="Attach a clipping" onClick={() => setAttach(attach === "article" ? null : "article")}><Paperclip size={13} /></button>
            <button className={`ctool ${attach === "code" ? "on" : ""}`} title="Attach a code exhibit" onClick={() => setAttach(attach === "code" ? null : "code")}><FileCode2 size={13} /></button>
          </div>
          <textarea ref={taRef} rows={1}
            placeholder="Add to the file…  @claude to task an agent · /thesis to stamp a snapshot"
            value={input}
            onChange={(e) => { onInput(e.target.value); const t = e.target; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px"; }}
            onKeyDown={onKey} />
          <button className="send" onClick={send} disabled={!input.trim()} title="Transmit (Enter)">FILE</button>
        </div>
        <div className="chints">
          <span className="h"><span className="kbd">@</span> task an agent</span>
          <span className="h"><span className="kbd">/</span> commands</span>
          <span className="h"><Paperclip size={9} /> clip · <span style={{ marginLeft: 4 }}>exhibit</span></span>
          <span className="h"><span className="kbd">↵</span> file</span>
        </div>
      </div>
    </section>
  );
}

// ── one dispatch entry ──
function Dispatch({ m, ix, onFlashNode }: { m: Message; ix: number; onFlashNode?: (id: string) => void }) {
  const gutter = (
    <div className="gut"><span className="tm">{clk(m.ts)}</span><span className="ix">#{String(ix).padStart(3, "0")}</span></div>
  );

  if (m.msg_type === "system") {
    // System line → COMMIT ledger row. If it references a node id we know,
    // clicking flashes it on the board.
    const nodeMatch = m.content.match(/\b([a-z][a-z0-9-]{2,})\b/);
    return (
      <div className="disp k-sys">
        {gutter}
        <div className="entry">
          <div className="commit" onClick={() => nodeMatch && onFlashNode?.(nodeMatch[1])}>
            <span className="gl">▣</span><span className="nm" style={{ whiteSpace: "pre-wrap" }}>{m.content}</span>
          </div>
        </div>
      </div>
    );
  }

  if (m.msg_type === "llm") {
    return (
      <div className={`disp k-${modelBadge(m.model).replace("mb-", "")}`}>
        {gutter}
        <div className="entry">
          <div className="ehead">
            <span className="analysis-tag">▸ analysis</span>
            <span className={`mbadge ${modelBadge(m.model)}`}>{shortModel(m.model)}</span>
          </div>
          <div className="etext">
            <ReactMarkdown components={{ a: SafeLink }}>{m.content}</ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  const analyst = ANALYSTS[m.user];
  const auCls = analyst?.cls === "me" ? "me" : analyst?.cls === "dan" ? "dan" : "";

  // article clipping → paperclipped memo card
  if (m.kind === "article" && m.meta) {
    const a = m.meta as ArticleMeta;
    return (
      <div className={`disp k-${m.user}`}>
        {gutter}
        <div className="entry">
          <div className="ehead"><span className={`au ${auCls}`}>{(analyst?.name || m.user).toUpperCase()}</span><span className="lbl" style={{ letterSpacing: ".1em" }}>shared a clipping</span></div>
          <div className="memo">
            <div className="src">filed from · <b>{a.source}</b></div>
            <div className="at">{a.title}</div>
            {a.take && <div className="ad">"{a.take}"</div>}
          </div>
        </div>
      </div>
    );
  }

  // code exhibit
  if (m.kind === "code" && m.meta) {
    const c = m.meta as CodeExhibitMeta;
    return (
      <div className={`disp k-${m.user}`}>
        {gutter}
        <div className="entry">
          <div className="ehead"><span className={`au ${auCls}`}>{(analyst?.name || m.user).toUpperCase()}</span><span className="lbl" style={{ letterSpacing: ".1em" }}>exhibit · {c.fn}</span></div>
          <div className="exhibit">
            <div className="xh"><span className="fn">{c.fn}</span><span className="lg">{c.lang}</span></div>
            <pre>{c.code}</pre>
          </div>
        </div>
      </div>
    );
  }

  // user memo (plain text)
  return (
    <div className={`disp k-${m.user}`}>
      {gutter}
      <div className="entry">
        <div className="ehead"><span className={`au ${auCls}`}>{(analyst?.name || m.user).toUpperCase()}</span></div>
        <div className="etext">
          <span dangerouslySetInnerHTML={{ __html: rich(m.content) }} />
          {analyst && <span className="sign">— {analyst.initial}</span>}
        </div>
      </div>
    </div>
  );
}

function SafeLink({ href, children }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { children?: React.ReactNode }) {
  if (href && (href.startsWith("http://") || href.startsWith("https://"))) {
    return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
  }
  return <span>{children}</span>;
}
