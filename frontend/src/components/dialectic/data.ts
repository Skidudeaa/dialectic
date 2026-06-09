// Dialectic — live-backend data hooks + presentation helpers.
//
// These wire the dossier UI to the same REST/WS surface the rest of the app
// uses (see lib/api.ts). Nothing here is mocked: rooms, messages, thesis
// snapshots, open trades, predicates, predictions and presence all come from
// the running FastAPI backend. The only static bits are presentational
// constants the backend doesn't model (the two analysts' cities + the
// distance between them — confirmed real in the design brief).

import { useCallback, useEffect, useState } from "react";
import {
  apiFetch,
  getToken,
  getUsername,
  subscribeRoomMessages,
} from "../../lib/api";
import type {
  BuilderBook,
  BuilderNode,
  OpenTradeDetail,
  OpenTradeSummary,
  Prediction,
  PresencePayload,
  PresenceUser,
  Room,
  ThesisBook,
  ThesisState,
  WSMessage,
} from "../../lib/types";

// ── presentational constants (not modelled server-side) ──────────────────
export const ANALYSTS: Record<string, { name: string; city: string; initial: string; cls: "me" | "dan" }> = {
  amo: { name: "Amo", city: "Brooklyn", initial: "A", cls: "me" },
  dan: { name: "Dan", city: "Lisbon", initial: "D", cls: "dan" },
};
export const DISTANCE_KM = "5,412 km";

export const PHASE_NAMES: Record<number, string> = {
  1: "Shock", 2: "Transmission", 3: "Amplification", 4: "Policy Response", 5: "Resolution",
};
export const PHASE_HINT: Record<number, string> = {
  1: "Watch transmission channels for first downstream firings.",
  2: "Look for amplification — multi-path confluence on shared nodes.",
  3: "Policy response (rates / fiscal / sanctions) signals a phase turn.",
  4: "Resolution requires sustained reversal across upstream nodes.",
  5: "Thesis lifecycle complete — close out remaining positions.",
};

// ── model → dossier badge class ───────────────────────────────────────────
export function modelBadge(model: string | null): string {
  const m = (model || "").toLowerCase();
  if (m.includes("claude")) return "mb-claude";
  if (m.includes("gpt")) return "mb-gpt";
  if (m.includes("gemini")) return "mb-gemini";
  if (m.includes("deepseek")) return "mb-deepseek";
  return "mb-claude";
}
export function shortModel(model: string | null): string {
  if (!model) return "agent";
  return (model.split("/").pop() || model).replace(/-preview$/, "").replace(/-chat$/, "");
}

export function phaseColorVar(n: number): string {
  return n >= 4 ? "var(--teal)" : n >= 3 ? "var(--scarlet)" : "var(--amber)";
}

// ════════════════════════════════════════════════════════════════════════
// rooms + books — the case drawer
// ════════════════════════════════════════════════════════════════════════
export function useRoomsAndBooks() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [books, setBooks] = useState<ThesisBook[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    Promise.all([
      apiFetch<Room[]>("/api/rooms").catch(() => [] as Room[]),
      apiFetch<ThesisBook[]>("/api/thesis/books").catch(() => [] as ThesisBook[]),
    ]).then(([r, b]) => {
      if (!alive) return;
      setRooms(r);
      setBooks(b);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  return { rooms, books, loading };
}

/** Mock-style short case title: strip the "Thesis" suffix and date stamp. */
export function shortCaseTitle(title: string): string {
  return title
    .replace(/\s*[—–-]\s*\w+\s+\d{4}\s*$/u, "")
    .replace(/\s+Thesis$/i, "")
    .trim() || title;
}

// ════════════════════════════════════════════════════════════════════════
// per-book snapshot map — phase diamonds + conf bars for the case drawer
// ════════════════════════════════════════════════════════════════════════
export interface CasePulse {
  phase: number;
  phaseName: string;
  /** strongest confluence, normalised to 0–1 for the bar */
  conf: number;
}

export function useCasePulses(books: ThesisBook[]): Record<string, CasePulse> {
  const [pulses, setPulses] = useState<Record<string, CasePulse>>({});
  useEffect(() => {
    if (!books.length) return;
    let alive = true;
    const load = () => {
      Promise.all(
        books.map((b) =>
          apiFetch<ThesisState>(`/api/thesis/${b.id}/state`)
            .then((s) => {
              const confVals = Object.values(s.confluenceScores || {});
              return [b.id, {
                phase: s.cascadePhase?.number || 1,
                phaseName: PHASE_NAMES[s.cascadePhase?.number || 1] || s.cascadePhase?.key || "",
                conf: confVals.length ? Math.min(1, Math.max(...confVals) / 3) : 0,
              }] as const;
            })
            .catch(() => null),
        ),
      ).then((entries) => {
        if (!alive) return;
        setPulses(Object.fromEntries(entries.filter((e): e is NonNullable<typeof e> => e !== null)));
      });
    };
    load();
    const poll = setInterval(load, 120_000);
    return () => { alive = false; clearInterval(poll); };
  }, [books]);
  return pulses;
}

// ════════════════════════════════════════════════════════════════════════
// thesis snapshot (live) + builder structure (node→phase mapping + claim)
// ════════════════════════════════════════════════════════════════════════
export interface ThesisBundle {
  state: ThesisState | null;
  /** node id → { phase, label } from the builder config (snapshot lacks phase). */
  structure: Record<string, { phase: number; label: string }>;
  claim: string;
  title: string;
}

export function useThesis(bookId: string | null): ThesisBundle {
  const [state, setState] = useState<ThesisState | null>(null);
  const [structure, setStructure] = useState<Record<string, { phase: number; label: string }>>({});
  const [claim, setClaim] = useState("");
  const [title, setTitle] = useState("");

  const fetchState = useCallback(async (book: string) => {
    try {
      const data = await apiFetch<ThesisState>(`/api/thesis/${book}/state`);
      setState(data);
      if (data.title && !title) setTitle(data.title);
    } catch { /* keep prior */ }
  }, [title]);

  // Builder config — gives us node phases + the thesis claim (not in snapshot).
  useEffect(() => {
    if (!bookId) return;
    setStructure({}); setClaim(""); setTitle("");
    apiFetch<BuilderBook>(`/api/thesis/builder/books/${bookId}`)
      .then((bk) => {
        const map: Record<string, { phase: number; label: string }> = {};
        (bk.nodes || []).forEach((n: BuilderNode) => {
          map[n.id] = { phase: n.phase || 1, label: n.label || n.id };
        });
        setStructure(map);
        setClaim(bk.meta?.claim || "");
        setTitle(bk.meta?.title || "");
      })
      .catch(() => { /* structure is best-effort */ });
  }, [bookId]);

  // Live snapshot + WS-driven refresh.
  useEffect(() => {
    if (!bookId) { setState(null); return; }
    fetchState(bookId);
    const poll = setInterval(() => fetchState(bookId), 60_000);
    const unsub = subscribeRoomMessages((msg: WSMessage) => {
      if (msg.type === "state_update" || msg.type === "price.tick") {
        const b = (msg.payload?.book_id as string | undefined) ?? msg.thesisId;
        if (!b || b === bookId) fetchState(bookId);
      } else if (msg.type === "tv-alert") {
        // Pine alert mutated the thesis (closesObserved / state / probability)
        // — pull a fresh snapshot so the board reflects it immediately.
        const b = msg.payload?.bookId as string | undefined;
        if (!b || b === bookId) fetchState(bookId);
      }
    });
    return () => { clearInterval(poll); unsub(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId]);

  return { state, structure, claim, title };
}

// ════════════════════════════════════════════════════════════════════════
// open position for the active book (+ live predicate detail)
// ════════════════════════════════════════════════════════════════════════
export function useBookTrade(bookId: string | null) {
  const [detail, setDetail] = useState<OpenTradeDetail | null>(null);
  const [summary, setSummary] = useState<OpenTradeSummary | null>(null);

  const reload = useCallback(async () => {
    if (!bookId) { setDetail(null); setSummary(null); return; }
    try {
      const list = await apiFetch<OpenTradeSummary[]>("/api/v1/trades");
      const mine = list.find((t) => t.book === bookId) || list[0] || null;
      setSummary(mine);
      if (mine) {
        const d = await apiFetch<OpenTradeDetail>(`/api/v1/trades/${mine.trade_id}`);
        setDetail(d);
      } else {
        setDetail(null);
      }
    } catch { /* leave prior */ }
  }, [bookId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
    const poll = setInterval(reload, 30_000);
    const unsub = subscribeRoomMessages((msg: WSMessage) => {
      if (msg.type === "state_update") reload();
    });
    return () => { clearInterval(poll); unsub(); };
  }, [reload]);

  return { detail, summary, reload };
}

// ════════════════════════════════════════════════════════════════════════
// standing bets (predictions) — left rail
// ════════════════════════════════════════════════════════════════════════
export function usePredictions(bookId: string | null) {
  const [items, setItems] = useState<Prediction[]>([]);
  useEffect(() => {
    let alive = true;
    apiFetch<Prediction[]>("/api/predictions")
      .then((p) => { if (alive) setItems(p); })
      .catch(() => { if (alive) setItems([]); });
    return () => { alive = false; };
  }, []);
  // Prefer bets linked to the active book, then unlinked, capped for the rail.
  const ranked = [...items].sort((a, b) => {
    const am = a.linked_book_id === bookId ? 0 : 1;
    const bm = b.linked_book_id === bookId ? 0 : 1;
    return am - bm;
  });
  return ranked;
}

// ════════════════════════════════════════════════════════════════════════
// presence — driven by the active RoomSocket's presence.changed frames
// ════════════════════════════════════════════════════════════════════════
export function usePresence() {
  const [roster, setRoster] = useState<PresenceUser[]>([]);
  useEffect(() => {
    return subscribeRoomMessages((msg: WSMessage) => {
      if (msg.type !== "presence.changed") return;
      const payload = msg.payload as unknown as PresencePayload;
      if (payload && Array.isArray(payload.users)) setRoster(payload.users);
    });
  }, []);
  return roster;
}

// ── kill flow (two-step confirm token), mirrors TradeLifecyclePanel ───────
function authHeaders(): Record<string, string> {
  const token = getToken();
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

/** Request a confirm token (expects HTTP 409 with detail.confirm_token). */
export async function requestKillToken(tradeId: string, reason: string): Promise<string> {
  const resp = await fetch(`/api/v1/trades/${tradeId}/kill`, {
    method: "POST", headers: authHeaders(), body: JSON.stringify({ reason }),
  });
  if (resp.status !== 409) {
    const text = await resp.text();
    throw new Error(`Expected 409 confirm prompt, got ${resp.status}: ${text}`);
  }
  const body = await resp.json();
  return body.detail.confirm_token as string;
}

/** Confirm the kill with the issued token. */
export async function confirmKill(tradeId: string, reason: string, token: string): Promise<void> {
  const resp = await fetch(`/api/v1/trades/${tradeId}/kill`, {
    method: "POST", headers: authHeaders(),
    body: JSON.stringify({ reason, confirm_token: token }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
}

export const me = () => getUsername();
