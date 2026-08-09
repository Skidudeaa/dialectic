// PresencePills — top-bar pill row showing who's connected to the desk
// right now, which thesis book they're viewing, and (for the LLM) whether
// it's mid-tool-call.
//
// WHY (Unit 9): Today Amo and Dan have no visibility into each other's
// context. Dan can stare at iran-hormuz while Amo edits trump-tariffs and
// neither knows. A row of compact pills in the header gives immediate
// "who else is here and what are they looking at" without taking vertical
// space.
//
// Color semantics:
//   - teal ring = viewing same book as me
//   - amber ring = viewing a different book
//   - dim text = idle > 60s since last_activity
// Agent pill (kind="agent") uses a Sparkles glyph and pulses while
// status === "thinking".

import { useEffect, useMemo, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { subscribeRoomMessages } from "../lib/api";
import type { PresencePayload, PresenceUser, WSMessage } from "../lib/types";

const MAX_VISIBLE = 6;
const IDLE_MS = 60_000;

interface Props {
  myUserId: string | null;
  myBookId: string | null;
}

function relativeAge(iso: string, now: number): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const sec = Math.max(0, Math.round((now - then) / 1000));
  if (sec < 5) return "just now";
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

function initials(userId: string): string {
  if (!userId) return "?";
  return userId.trim().charAt(0).toUpperCase();
}

export default function PresencePills({ myUserId, myBookId }: Props) {
  const [roster, setRoster] = useState<PresenceUser[]>([]);
  // WHY: Refresh `now` every 15s so idle state recomputes — an otherwise
  // static roster (no new frames) would never transition to "idle" in the UI.
  // A timestamp (not a counter) so render never calls the impure Date.now().
  const [now, setNow] = useState(() => Date.now());
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const unsub = subscribeRoomMessages((msg: WSMessage) => {
      if (msg.type !== "presence.changed") return;
      const payload = msg.payload as unknown as PresencePayload;
      if (!payload || !Array.isArray(payload.users)) return;
      setRoster(payload.users);
    });
    return () => {
      unsub();
    };
  }, []);

  useEffect(() => {
    tickRef.current = setInterval(() => setNow(Date.now()), 15_000);
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, []);

  const { visible, overflow } = useMemo(() => {
    const v = roster.slice(0, MAX_VISIBLE);
    const o = Math.max(0, roster.length - MAX_VISIBLE);
    return { visible: v, overflow: o };
  }, [roster]);

  if (roster.length === 0) return null;

  return (
    <div
      className="flex items-center gap-1"
      role="group"
      aria-label="Connected users"
    >
      {visible.map((u, i) => (
        <Pill
          key={`${u.user_id}-${u.book_id ?? ""}-${i}`}
          u={u}
          now={now}
          isMe={u.kind === "human" && u.user_id === myUserId}
          sameBook={
            u.kind === "human" &&
            !!u.book_id &&
            u.book_id === myBookId
          }
        />
      ))}
      {overflow > 0 && (
        <span
          className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-elevated border border-border text-[9px] font-mono text-text-dim"
          title={`${overflow} more connected`}
          aria-label={`${overflow} more connected users`}
        >
          +{overflow}
        </span>
      )}
    </div>
  );
}

function Pill({
  u,
  now,
  isMe,
  sameBook,
}: {
  u: PresenceUser;
  now: number;
  isMe: boolean;
  sameBook: boolean;
}) {
  const age = Date.parse(u.last_activity);
  const isIdle =
    !Number.isNaN(age) && now - age > IDLE_MS && u.kind === "human";

  const isAgent = u.kind === "agent";
  const isThinking = isAgent && u.status === "thinking";

  let ringClass = "border-border";
  if (isAgent) ringClass = "border-amber/60";
  else if (sameBook) ringClass = "border-teal";
  else if (u.book_id) ringClass = "border-amber/40";

  const label = isAgent ? "Agent" : u.user_id;
  const tooltip = [
    isAgent ? "Agent" : `${u.user_id}${isMe ? " (you)" : ""}`,
    u.book_id ? `book: ${u.book_id}` : "no book",
    relativeAge(u.last_activity, now),
    isThinking ? "thinking…" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const textClass = isIdle
    ? "text-text-dim"
    : isAgent
      ? "text-amber"
      : isMe
        ? "text-amber"
        : "text-text-primary";

  return (
    <span
      className={`inline-flex items-center justify-center w-5 h-5 rounded-full bg-elevated border ${ringClass} font-mono text-[10px] ${textClass} ${isThinking ? "animate-pulse" : ""}`}
      title={tooltip}
      aria-label={tooltip}
      data-presence-kind={u.kind}
      data-presence-status={u.status ?? ""}
    >
      {isAgent ? (
        <Sparkles size={10} aria-hidden="true" />
      ) : (
        <span aria-hidden="true">{initials(label)}</span>
      )}
    </span>
  );
}
