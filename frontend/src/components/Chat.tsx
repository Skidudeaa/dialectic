import { useState, useEffect, useRef, useCallback, useMemo, memo } from "react";
import ReactMarkdown from "react-markdown";
import {
  Send,
  Bot,
  Loader,
  Pin,
  Download,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  RefreshCw,
  Search,
  X,
  Wifi,
  WifiOff,
  AlertCircle,
} from "lucide-react";
import { apiFetch, getUsername, RoomSocket } from "../lib/api";
import type { Room, Message, WSMessage } from "../lib/types";

interface Props {
  room: Room;
}

// ────────────────────────────────────────────────────────────────────────────
// Static config — slash commands and @mentions surfaced for autocomplete
// ────────────────────────────────────────────────────────────────────────────

const MENTIONS: Array<{ key: string; label: string; desc: string; cls: string }> = [
  { key: "claude", label: "@claude", desc: "Anthropic Claude — long-context reasoning", cls: "text-amber" },
  { key: "gpt", label: "@gpt", desc: "OpenAI GPT — broad general", cls: "text-green" },
  { key: "gemini", label: "@gemini", desc: "Google Gemini — fast multimodal", cls: "text-blue" },
  { key: "deepseek", label: "@deepseek", desc: "DeepSeek R1 — chain-of-thought", cls: "text-purple" },
  { key: "compare", label: "@compare", desc: "Run claude + gpt + gemini side-by-side", cls: "text-teal" },
];

const SLASH_COMMANDS: Array<{ cmd: string; desc: string; usage?: string }> = [
  { cmd: "/brief", desc: "Post the morning brief into chat" },
  { cmd: "/thesis", desc: "Snapshot phase, fired/approaching nodes, top confluence", usage: "/thesis [book-id]" },
  { cmd: "/diff", desc: "Re-fetch live prices for the linked book", usage: "/diff [book-id]" },
  { cmd: "/predict", desc: "Log a prediction with confidence + 30d deadline", usage: '/predict "statement" 75%' },
  { cmd: "/watchlist", desc: "Dump current market watchlist" },
];

const MODEL_MAP: Record<string, string> = {
  claude: "anthropic/claude-sonnet-4.6",
  gpt: "openai/gpt-5.3-chat",
  deepseek: "deepseek/deepseek-r1",
  gemini: "google/gemini-3.1-pro-preview",
};

const MODEL_COLORS: Record<string, string> = {
  "claude-sonnet-4.6": "bg-amber/20 text-amber border-amber/30",
  "gpt-5.3-chat": "bg-green/20 text-green border-green/30",
  "deepseek-r1": "bg-purple/20 text-purple border-purple/30",
  "gemini-3.1-pro-preview": "bg-blue/20 text-blue border-blue/30",
};

function modelBadgeClass(model: string | null): string {
  if (!model) return "bg-teal/20 text-teal border-teal/30";
  for (const [key, cls] of Object.entries(MODEL_COLORS)) {
    if (model.includes(key) || key.includes(model)) return cls;
  }
  const lower = model.toLowerCase();
  if (lower.includes("claude")) return "bg-amber/20 text-amber border-amber/30";
  if (lower.includes("gpt")) return "bg-green/20 text-green border-green/30";
  if (lower.includes("deepseek")) return "bg-purple/20 text-purple border-purple/30";
  if (lower.includes("gemini")) return "bg-blue/20 text-blue border-blue/30";
  return "bg-teal/20 text-teal border-teal/30";
}

function shortModelName(model: string | null): string {
  if (!model) return "ai";
  const last = model.split("/").pop() || model;
  return last.replace(/-preview$/, "").replace(/-chat$/, "");
}

// WHY: Prevent javascript: URL XSS in LLM-generated markdown links.
const safeLink = ({
  href,
  children,
  ...props
}: React.AnchorHTMLAttributes<HTMLAnchorElement> & { children?: React.ReactNode }) => {
  if (href && (href.startsWith("http://") || href.startsWith("https://"))) {
    return (
      <a {...props} href={href} target="_blank" rel="noopener noreferrer" className="text-teal underline decoration-teal/30 hover:decoration-teal">
        {children}
      </a>
    );
  }
  return <span>{children}</span>;
};

// ────────────────────────────────────────────────────────────────────────────
// Time helpers
// ────────────────────────────────────────────────────────────────────────────

function relTime(iso: string, now: number): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const sec = Math.floor((now - t) / 1000);
  if (sec < 5) return "now";
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

function absTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sameDay(a: string, b: string): boolean {
  const da = new Date(a);
  const db = new Date(b);
  return (
    da.getFullYear() === db.getFullYear() &&
    da.getMonth() === db.getMonth() &&
    da.getDate() === db.getDate()
  );
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((today.getTime() - target.getTime()) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return d.toLocaleDateString([], { weekday: "long" });
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

// ────────────────────────────────────────────────────────────────────────────
// Optimistic send model (local-only entries pending server echo)
// ────────────────────────────────────────────────────────────────────────────

interface PendingMessage {
  tempId: string;
  content: string;
  ts: string;
  status: "sending" | "failed";
  error?: string;
}

// ────────────────────────────────────────────────────────────────────────────
// Connection state inferred from WS event flow
// ────────────────────────────────────────────────────────────────────────────

type ConnState = "connecting" | "live" | "stale" | "offline";

export default function Chat({ room }: Props) {
  const me = getUsername();
  const [messages, setMessages] = useState<Message[]>([]);
  const [pending, setPending] = useState<PendingMessage[]>([]);
  const [input, setInput] = useState("");

  // Streaming: ref-buffered tokens flushed at RAF cadence
  const [streamDisplay, setStreamDisplay] = useState<Record<string, string>>({});
  const streamRef = useRef<Record<string, string>>({});
  const streamDirtyRef = useRef(false);
  const rafRef = useRef<number>(0);

  // Track which models are awaiting first chunk (for "thinking" indicator)
  const [pendingLLM, setPendingLLM] = useState<Set<string>>(new Set());
  const llmStartTimes = useRef<Record<string, number>>({});
  const llmLatency = useRef<Record<string, number>>({});

  const [sending, setSending] = useState(false);
  const [typingUsers, setTypingUsers] = useState<Set<string>>(new Set());
  const [onlineUsers, setOnlineUsers] = useState<Array<{ username: string; viewing: string }>>([]);
  const [pins, setPins] = useState<Message[]>([]);
  const [pinsExpanded, setPinsExpanded] = useState(false);

  // Search / filter
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);

  // Composer popover state
  const [popover, setPopover] = useState<null | { kind: "mention" | "slash"; query: string; selected: number }>(null);

  // Connection state — inferred from WS event traffic
  const [conn, setConn] = useState<ConnState>("connecting");
  const lastWSEventRef = useRef<number>(0);

  // Auto-scroll guard: only auto-scroll if user is near bottom
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const liveRegionRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [showJumpDown, setShowJumpDown] = useState(false);

  // Now-tick for relative-time updates (every 30s)
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);

  const socketRef = useRef<RoomSocket | null>(null);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // ── RAF flush loop for streaming tokens ─────────────────────────────
  useEffect(() => {
    function flush() {
      if (streamDirtyRef.current) {
        streamDirtyRef.current = false;
        setStreamDisplay({ ...streamRef.current });
      }
      rafRef.current = requestAnimationFrame(flush);
    }
    rafRef.current = requestAnimationFrame(flush);
    return () => cancelAnimationFrame(rafRef.current);
  }, []);

  // ── Initial fetch on room change ────────────────────────────────────
  useEffect(() => {
    setMessages([]);
    setPins([]);
    setPending([]);
    setPopover(null);
    apiFetch<Message[]>(`/api/rooms/${room.id}/messages?limit=100`)
      .then(setMessages)
      .catch(() => {});
    apiFetch<Message[]>(`/api/rooms/${room.id}/pins`)
      .then(setPins)
      .catch(() => {});
  }, [room.id]);

  // ── WebSocket subscription ──────────────────────────────────────────
  useEffect(() => {
    const sock = new RoomSocket(room.id);
    socketRef.current = sock;
    setConn("connecting");
    lastWSEventRef.current = Date.now();

    const unsub = sock.subscribe((msg: WSMessage) => {
      lastWSEventRef.current = Date.now();
      setConn("live");

      if (msg.type === "message") {
        const m = msg.payload as unknown as Message;
        setMessages((prev) => {
          if (prev.some((p) => p.id === m.id)) return prev;
          // Reconcile against optimistic pending entries — if the echoed
          // message matches a pending one (same user + content + close ts),
          // drop the optimistic entry.
          if (m.user === me && m.msg_type === "user") {
            setPending((pp) => pp.filter((q) => q.content !== m.content));
          }
          return [...prev, m];
        });
        // Announce new messages to screen readers (debounced via DOM update)
        if (liveRegionRef.current && m.user !== me) {
          const author = m.msg_type === "llm" ? shortModelName(m.model) : m.user;
          liveRegionRef.current.textContent = `${author}: ${m.content.slice(0, 140)}`;
        }
      } else if (msg.type === "llm_chunk") {
        const { token, model } = msg.payload as { token: string; model: string };
        if (!streamRef.current[model]) {
          // First chunk → record latency
          const startedAt = llmStartTimes.current[model];
          if (startedAt) llmLatency.current[model] = Date.now() - startedAt;
          setPendingLLM((p) => {
            if (!p.has(model)) return p;
            const next = new Set(p);
            next.delete(model);
            return next;
          });
        }
        streamRef.current[model] = (streamRef.current[model] || "") + token;
        streamDirtyRef.current = true;
      } else if (msg.type === "llm_done") {
        const { model } = msg.payload as { model: string };
        delete streamRef.current[model];
        delete llmStartTimes.current[model];
        streamDirtyRef.current = true;
        setPendingLLM((p) => {
          if (!p.has(model)) return p;
          const next = new Set(p);
          next.delete(model);
          return next;
        });
      } else if (msg.type === "typing") {
        const { username, typing } = msg.payload as { username: string; typing: boolean };
        setTypingUsers((prev) => {
          const next = new Set(prev);
          if (typing) next.add(username);
          else next.delete(username);
          return next;
        });
      } else if (msg.type === "presence") {
        const { users } = msg.payload as { users: Array<{ username: string; viewing: string }> };
        setOnlineUsers(users);
      }
    });
    return () => {
      unsub();
      sock.close();
      socketRef.current = null;
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    };
  }, [room.id, me]);

  // ── Connection-state staleness watchdog ─────────────────────────────
  // The RoomSocket reconnects internally on close, but doesn't expose the
  // ready state. We infer liveness from WS event traffic — typing, presence,
  // and message events all bump lastWSEventRef. If nothing inbound for 45s,
  // mark stale; 90s → offline.
  useEffect(() => {
    const t = setInterval(() => {
      const since = Date.now() - lastWSEventRef.current;
      if (since > 90000) setConn("offline");
      else if (since > 45000) setConn((c) => (c === "live" ? "stale" : c));
    }, 5000);
    return () => clearInterval(t);
  }, []);

  // ── Auto-scroll: only if user is near bottom ───────────────────────
  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [messages, streamDisplay, pending, pendingLLM]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    const wasNearBottom = stickToBottomRef.current;
    stickToBottomRef.current = distanceFromBottom < 80;
    if (wasNearBottom !== stickToBottomRef.current) {
      setShowJumpDown(!stickToBottomRef.current);
    }
  }

  function jumpToBottom() {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current = true;
    setShowJumpDown(false);
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }

  // ── Message actions ─────────────────────────────────────────────────
  const postSystem = useCallback(
    async (content: string) => {
      await apiFetch(`/api/rooms/${room.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ content, msg_type: "system" }),
      });
    },
    [room.id],
  );

  const pinMessage = useCallback(
    async (msg: Message) => {
      try {
        const updated = await apiFetch<Message[]>(`/api/rooms/${room.id}/pins`, {
          method: "POST",
          body: JSON.stringify(msg),
        });
        setPins(updated);
      } catch {
        /* swallow — pin failure is non-critical */
      }
    },
    [room.id],
  );

  const unpinMessage = useCallback(
    async (messageId: string) => {
      try {
        const updated = await apiFetch<Message[]>(`/api/rooms/${room.id}/pins/${messageId}`, {
          method: "DELETE",
        });
        setPins(updated);
      } catch {
        /* swallow */
      }
    },
    [room.id],
  );

  const exportChat = useCallback(async () => {
    try {
      const data = await apiFetch<{ markdown: string }>(`/api/rooms/${room.id}/export`);
      const blob = new Blob([data.markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${room.name}-${new Date().toISOString().slice(0, 10)}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* swallow */
    }
  }, [room.id, room.name]);

  // ── LLM dispatch (kicks off a chat or compare call) ─────────────────
  const dispatchLLM = useCallback(
    (cmd: string, prompt: string) => {
      if (cmd === "compare") {
        // WHY all three: the onboarding tour + welcome page promise "@compare runs
        // claude + gpt + gemini side-by-side". Drop one and the spec lies.
        const models = [
          "anthropic/claude-sonnet-4.6",
          "openai/gpt-5.3-chat",
          "google/gemini-3.1-pro-preview",
        ];
        models.forEach((m) => {
          llmStartTimes.current[m] = Date.now();
          setPendingLLM((p) => new Set(p).add(m));
        });
        apiFetch("/api/llm/compare", {
          method: "POST",
          body: JSON.stringify({ prompt, room_id: room.id }),
        }).catch((err) => {
          console.error("LLM compare failed:", err);
          models.forEach((m) =>
            setPendingLLM((p) => {
              const next = new Set(p);
              next.delete(m);
              return next;
            }),
          );
        });
      } else {
        const model = MODEL_MAP[cmd];
        if (!model) return;
        llmStartTimes.current[model] = Date.now();
        setPendingLLM((p) => new Set(p).add(model));
        apiFetch("/api/llm/chat", {
          method: "POST",
          body: JSON.stringify({ prompt, model, room_id: room.id }),
        }).catch((err) => {
          console.error("LLM chat failed:", err);
          setPendingLLM((p) => {
            const next = new Set(p);
            next.delete(model);
            return next;
          });
        });
      }
    },
    [room.id],
  );

  // ── Slash command handler ───────────────────────────────────────────
  const handleSlashCommand = useCallback(
    async (text: string): Promise<boolean> => {
      const cmd = text.split(/\s+/)[0].toLowerCase();
      const args = text.slice(cmd.length).trim();

      try {
        if (cmd === "/brief") {
          const data = await apiFetch<{ brief: string }>("/api/outcomes/brief");
          await postSystem(data.brief);
          return true;
        }
        if (cmd === "/thesis") {
          const bookId = args || room.linked_book_id || "iran-hormuz-graph";
          const state = await apiFetch<Record<string, unknown>>(`/api/thesis/${bookId}/state`);
          const ns = state.nodeStates as Record<string, string>;
          const cs = state.confluenceScores as Record<string, number>;
          const phase = state.cascadePhase as Record<string, unknown>;
          const fired = Object.entries(ns)
            .filter(([, v]) => v === "fired")
            .map(([k]) => k);
          const approaching = Object.entries(ns)
            .filter(([, v]) => v === "approaching")
            .map(([k]) => k);
          const topConf = Object.entries(cs)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 5);
          const lines = [
            `THESIS: ${state.title || bookId}`,
            `Phase ${phase.number} (${phase.key}) — ${phase.status}`,
            `Fired: ${fired.join(", ") || "none"}`,
            `Approaching: ${approaching.join(", ") || "none"}`,
            `Confluence: ${topConf.map(([k, v]) => `${k}=${v}`).join(", ")}`,
          ];
          await postSystem(lines.join("\n"));
          return true;
        }
        if (cmd === "/diff") {
          const bookId = args || room.linked_book_id || "iran-hormuz-graph";
          await apiFetch(`/api/thesis/${bookId}/fetch-prices`, { method: "POST" });
          await postSystem(`Prices re-fetched for ${bookId}`);
          return true;
        }
        if (cmd === "/predict") {
          const match = args.match(/^"([^"]+)"\s+(\d+)%$/);
          if (match) {
            const deadline = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
            await apiFetch("/api/predictions", {
              method: "POST",
              body: JSON.stringify({
                statement: match[1],
                confidence: parseInt(match[2]) / 100,
                deadline,
              }),
            });
            await postSystem(`Prediction created: "${match[1]}" at ${match[2]}%`);
          } else {
            await postSystem('Usage: /predict "statement" 75%');
          }
          return true;
        }
        if (cmd === "/watchlist") {
          const items = await apiFetch<
            Array<{ symbol: string; label: string; last_price: number | null }>
          >("/api/market/watchlist");
          const lines = items.map(
            (i) =>
              `${i.symbol.padEnd(6)} ${i.last_price !== null ? i.last_price.toFixed(2) : "--"} ${i.label}`,
          );
          await postSystem("WATCHLIST\n" + lines.join("\n"));
          return true;
        }
      } catch (err) {
        await postSystem(`Command failed: ${cmd} — ${(err as Error).message || "unknown error"}`);
        return true;
      }
      return false;
    },
    [room.linked_book_id, postSystem],
  );

  // ── Send pipeline (with optimistic + retry) ────────────────────────
  const sendText = useCallback(
    async (text: string, retryOf?: PendingMessage) => {
      // Slash command path bypasses optimistic UI entirely
      if (text.startsWith("/")) {
        const handled = await handleSlashCommand(text);
        if (handled) return;
      }

      const tempId = retryOf?.tempId ?? `pending-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const optimistic: PendingMessage = {
        tempId,
        content: text,
        ts: new Date().toISOString(),
        status: "sending",
      };
      setPending((p) => {
        const without = retryOf ? p.filter((q) => q.tempId !== retryOf.tempId) : p;
        return [...without, optimistic];
      });
      stickToBottomRef.current = true;

      try {
        const mentionMatch = text.match(/^@(claude|gpt|deepseek|gemini|compare)\s+/i);
        if (mentionMatch) {
          const cmd = mentionMatch[1].toLowerCase();
          const prompt = text.slice(mentionMatch[0].length);
          await apiFetch(`/api/rooms/${room.id}/messages`, {
            method: "POST",
            body: JSON.stringify({ content: text }),
          });
          dispatchLLM(cmd, prompt);
        } else {
          await apiFetch(`/api/rooms/${room.id}/messages`, {
            method: "POST",
            body: JSON.stringify({ content: text }),
          });
        }
        // The WS echo will reconcile and remove the pending entry. As a
        // safety net, drop it after 8s so retry doesn't get stuck.
        setTimeout(() => {
          setPending((p) => p.filter((q) => q.tempId !== tempId));
        }, 8000);
      } catch (err) {
        setPending((p) =>
          p.map((q) =>
            q.tempId === tempId
              ? { ...q, status: "failed", error: (err as Error).message || "send failed" }
              : q,
          ),
        );
      }
    },
    [room.id, dispatchLLM, handleSlashCommand],
  );

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setPopover(null);
    setSending(true);
    try {
      await sendText(text);
    } finally {
      setSending(false);
      composerRef.current?.focus();
    }
  }, [input, sending, sendText]);

  const retryPending = useCallback(
    (p: PendingMessage) => {
      sendText(p.content, p);
    },
    [sendText],
  );

  const dismissPending = useCallback((tempId: string) => {
    setPending((p) => p.filter((q) => q.tempId !== tempId));
  }, []);

  // ── Composer: typing indicator + popover detection ──────────────────
  const handleInputChange = useCallback((value: string) => {
    setInput(value);
    socketRef.current?.sendTyping(true);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    typingTimerRef.current = setTimeout(() => {
      socketRef.current?.sendTyping(false);
    }, 2000);

    // Popover detection — only when the cursor token at start matches
    // an unfinished mention or slash command.
    if (value.startsWith("@") && !/\s/.test(value.slice(1))) {
      setPopover({ kind: "mention", query: value.slice(1).toLowerCase(), selected: 0 });
    } else if (value.startsWith("/") && !/\s/.test(value.slice(1))) {
      setPopover({ kind: "slash", query: value.slice(1).toLowerCase(), selected: 0 });
    } else {
      setPopover(null);
    }
  }, []);

  // ── Filtered popover items ──────────────────────────────────────────
  const popoverItems = useMemo(() => {
    if (!popover) return [];
    if (popover.kind === "mention") {
      return MENTIONS.filter((m) => m.key.startsWith(popover.query));
    }
    return SLASH_COMMANDS.filter((c) => c.cmd.slice(1).startsWith(popover.query));
  }, [popover]);

  function applyPopoverItem(idx: number) {
    if (!popover) return;
    const item = popoverItems[idx];
    if (!item) return;
    if (popover.kind === "mention") {
      const mi = item as (typeof MENTIONS)[number];
      setInput(mi.label + " ");
    } else {
      const ci = item as (typeof SLASH_COMMANDS)[number];
      setInput(ci.cmd + " ");
    }
    setPopover(null);
    composerRef.current?.focus();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Popover navigation
    if (popover && popoverItems.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setPopover({ ...popover, selected: (popover.selected + 1) % popoverItems.length });
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setPopover({
          ...popover,
          selected: (popover.selected - 1 + popoverItems.length) % popoverItems.length,
        });
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        applyPopoverItem(popover.selected);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setPopover(null);
        return;
      }
    }
    // Send
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
    // Ctrl/Cmd+F → focus search
    if ((e.metaKey || e.ctrlKey) && e.key === "f") {
      e.preventDefault();
      setSearchOpen(true);
    }
  }

  // ── Filtered + grouped message stream ──────────────────────────────
  const filteredMessages = useMemo(() => {
    if (!search.trim()) return messages;
    const q = search.toLowerCase();
    return messages.filter(
      (m) =>
        m.content.toLowerCase().includes(q) ||
        m.user.toLowerCase().includes(q) ||
        (m.model || "").toLowerCase().includes(q),
    );
  }, [messages, search]);

  const pinnedIds = useMemo(() => new Set(pins.map((p) => p.id)), [pins]);

  // Compute "should I show author header" per message — collapse runs
  // from same author within a 5-minute window.
  const renderRows = useMemo(() => {
    const rows: Array<
      | { kind: "day"; key: string; label: string }
      | { kind: "msg"; msg: Message; showHeader: boolean }
    > = [];
    let prev: Message | null = null;
    for (const m of filteredMessages) {
      if (!prev || !sameDay(prev.ts, m.ts)) {
        rows.push({ kind: "day", key: `day-${m.ts}`, label: dayLabel(m.ts) });
      }
      let showHeader = true;
      if (
        prev &&
        prev.user === m.user &&
        prev.msg_type === m.msg_type &&
        (m.model || null) === (prev.model || null) &&
        new Date(m.ts).getTime() - new Date(prev.ts).getTime() < 5 * 60_000
      ) {
        showHeader = false;
      }
      rows.push({ kind: "msg", msg: m, showHeader });
      prev = m;
    }
    return rows;
  }, [filteredMessages]);

  const typingList = Array.from(typingUsers).filter((u) => u !== me);

  // ────────────────────────────────────────────────────────────────────
  // Render
  // ────────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full">
      {/* ─── Room header ─── */}
      <header className="px-3 py-1 border-b border-border bg-surface shrink-0 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-medium truncate">{room.name}</h2>
            {room.linked_book_id && (
              <span className="text-[10px] text-teal font-mono truncate">{room.linked_book_id}</span>
            )}
            <ConnIndicator state={conn} />
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            {onlineUsers.length === 0 ? (
              <span className="text-[10px] text-text-dim font-mono">no participants online</span>
            ) : (
              onlineUsers.map((u) => (
                <span
                  key={u.username}
                  className="flex items-center gap-0.5 text-[10px] font-mono text-text-dim"
                  title={`${u.username} viewing ${u.viewing}`}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-green inline-block" />
                  {u.username}
                </span>
              ))
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setSearchOpen((s) => !s)}
            className={`p-1 rounded ${searchOpen ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`}
            title="Search messages (Ctrl+F)"
            aria-label="Search messages"
          >
            <Search size={11} />
          </button>
          {pins.length > 0 && (
            <button
              onClick={() => setPinsExpanded(!pinsExpanded)}
              className="flex items-center gap-0.5 text-[10px] font-mono text-amber hover:text-amber-dim p-1 rounded"
              aria-label={`${pins.length} pinned messages`}
              aria-expanded={pinsExpanded}
            >
              <Pin size={10} /> {pins.length}
            </button>
          )}
          <button
            onClick={exportChat}
            className="text-text-dim hover:text-text-primary p-1"
            title="Export chat as markdown"
            aria-label="Export chat"
          >
            <Download size={11} />
          </button>
        </div>
      </header>

      {/* ─── Search bar ─── */}
      {searchOpen && (
        <div className="px-3 py-1 border-b border-border bg-surface shrink-0 flex items-center gap-1.5">
          <Search size={11} className="text-text-dim shrink-0" />
          <input
            className="input flex-1 py-0.5 text-[11px]"
            placeholder="Filter messages by text, author, or model..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setSearch("");
                setSearchOpen(false);
              }
            }}
          />
          {search && (
            <span className="text-[10px] text-text-dim font-mono">
              {filteredMessages.length}/{messages.length}
            </span>
          )}
          <button
            onClick={() => {
              setSearch("");
              setSearchOpen(false);
            }}
            className="text-text-dim hover:text-text-primary p-0.5"
            aria-label="Close search"
          >
            <X size={11} />
          </button>
        </div>
      )}

      {/* ─── Pinned messages strip ─── */}
      {pins.length > 0 && (
        <div className="border-b border-amber/20 bg-amber/5 shrink-0">
          <button
            onClick={() => setPinsExpanded(!pinsExpanded)}
            className="w-full px-3 py-1 flex items-center justify-between hover:bg-amber/10 transition-colors"
            aria-expanded={pinsExpanded}
          >
            <span className="text-[10px] text-amber font-mono uppercase tracking-widest flex items-center gap-1">
              <Pin size={9} /> Pinned · {pins.length}
            </span>
            {pinsExpanded ? (
              <ChevronUp size={10} className="text-amber" />
            ) : (
              <ChevronDown size={10} className="text-amber" />
            )}
          </button>
          {pinsExpanded && (
            <div className="px-3 pb-1.5 max-h-40 overflow-y-auto space-y-0.5">
              {pins.map((p) => (
                <div
                  key={p.id}
                  className="flex items-start justify-between py-0.5 group border-l border-amber/30 pl-1.5"
                >
                  <div className="min-w-0 mr-1 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-amber font-mono">
                        {p.msg_type === "llm" ? shortModelName(p.model) : p.user}
                      </span>
                      <span className="text-[9px] text-text-dim font-mono" title={absTime(p.ts)}>
                        {relTime(p.ts, now)}
                      </span>
                    </div>
                    <p className="text-[11px] text-text-primary truncate" title={p.content}>
                      {p.content.length > 140 ? p.content.slice(0, 140) + "…" : p.content}
                    </p>
                  </div>
                  <button
                    onClick={() => unpinMessage(p.id)}
                    className="text-text-dim hover:text-danger opacity-0 group-hover:opacity-100 shrink-0 p-0.5"
                    title="Unpin"
                    aria-label="Unpin message"
                  >
                    <X size={10} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ─── Messages ─── */}
      <div className="flex-1 relative min-h-0">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="absolute inset-0 overflow-y-auto px-3 py-2 space-y-0.5"
          role="log"
          aria-label="Chat messages"
          aria-live="polite"
          aria-relevant="additions"
        >
          {messages.length === 0 && pending.length === 0 ? (
            <EmptyState
              roomName={room.name}
              linkedBook={room.linked_book_id}
              onSeed={(text) => setInput(text)}
            />
          ) : search.trim() && filteredMessages.length === 0 ? (
            <NoSearchResults query={search} onClear={() => setSearch("")} />
          ) : (
            renderRows.map((row) =>
              row.kind === "day" ? (
                <div
                  key={row.key}
                  className="flex items-center gap-2 py-1.5 sticky top-0 bg-void/80 backdrop-blur-sm z-10"
                >
                  <div className="flex-1 h-px bg-border" />
                  <span className="text-[10px] text-text-dim font-mono uppercase tracking-widest">
                    {row.label}
                  </span>
                  <div className="flex-1 h-px bg-border" />
                </div>
              ) : (
                <MessageRow
                  key={row.msg.id}
                  msg={row.msg}
                  isMe={row.msg.user === me}
                  showHeader={row.showHeader}
                  isPinned={pinnedIds.has(row.msg.id)}
                  now={now}
                  onPin={() => pinMessage(row.msg)}
                  onUnpin={() => unpinMessage(row.msg.id)}
                  onRetryWith={
                    row.msg.msg_type === "llm"
                      ? (model) => {
                          // Find the user-prompt that triggered this LLM
                          // — heuristic: the most recent prior @mention from a user.
                          const idx = messages.findIndex((m) => m.id === row.msg.id);
                          for (let i = idx - 1; i >= 0; i--) {
                            const cand = messages[i];
                            if (cand.msg_type !== "user") continue;
                            const mm = cand.content.match(/^@(claude|gpt|deepseek|gemini|compare)\s+/i);
                            if (mm) {
                              const prompt = cand.content.slice(mm[0].length);
                              dispatchLLM(model, prompt);
                              return;
                            }
                          }
                        }
                      : undefined
                  }
                />
              ),
            )
          )}

          {/* "Thinking" placeholders before first stream chunk arrives */}
          {Array.from(pendingLLM)
            .filter((m) => !streamDisplay[m])
            .map((model) => (
              <ThinkingBubble key={`thinking-${model}`} model={model} />
            ))}

          {/* Live streaming bubbles */}
          {Object.entries(streamDisplay).map(([model, text]) => (
            <StreamingBubble
              key={model}
              model={model}
              text={text}
              latencyMs={llmLatency.current[model]}
            />
          ))}

          {/* Optimistic pending user messages (appended last) */}
          {pending.map((p) => (
            <PendingRow
              key={p.tempId}
              pending={p}
              me={me || ""}
              now={now}
              onRetry={() => retryPending(p)}
              onDismiss={() => dismissPending(p.tempId)}
            />
          ))}
        </div>

        {/* Jump-to-bottom pill */}
        {showJumpDown && (
          <button
            onClick={jumpToBottom}
            className="absolute bottom-3 right-3 bg-elevated border border-border rounded-full px-2 py-1 text-[10px] font-mono text-text-primary hover:border-amber/50 shadow-lg flex items-center gap-1"
            aria-label="Scroll to latest"
          >
            <ChevronDown size={10} /> jump to latest
          </button>
        )}

        {/* aria-live announcer for off-screen new messages */}
        <div
          ref={liveRegionRef}
          aria-live="polite"
          aria-atomic="true"
          className="sr-only absolute"
          style={{ position: "absolute", left: -10000 }}
        />
      </div>

      {/* ─── Composer ─── */}
      <div className="px-3 py-1.5 border-t border-border bg-surface shrink-0 relative">
        {/* Typing indicator */}
        <div className="h-3.5 flex items-center">
          {typingList.length > 0 && (
            <p className="text-[10px] text-text-dim font-mono animate-pulse">
              <span className="inline-block w-1 h-1 rounded-full bg-text-muted mr-0.5 animate-pulse" />
              {typingList.join(", ")} typing...
            </p>
          )}
        </div>

        {/* Popover (mention/slash autocomplete) */}
        {popover && popoverItems.length > 0 && (
          <div className="absolute bottom-full left-3 right-3 mb-1 bg-elevated border border-border rounded shadow-xl overflow-hidden max-h-56 overflow-y-auto z-20">
            <div className="px-2 py-1 text-[9px] uppercase tracking-widest text-text-dim font-mono border-b border-border bg-surface">
              {popover.kind === "mention" ? "Mention an LLM" : "Slash command"}
              <span className="ml-2 normal-case tracking-normal">↑↓ navigate · Tab/Enter pick · Esc dismiss</span>
            </div>
            {popoverItems.map((item, i) => {
              const selected = i === popover.selected;
              if (popover.kind === "mention") {
                const mi = item as (typeof MENTIONS)[number];
                return (
                  <button
                    key={mi.key}
                    onClick={() => applyPopoverItem(i)}
                    onMouseEnter={() => setPopover({ ...popover, selected: i })}
                    className={`w-full text-left px-2 py-1 flex items-center gap-2 text-xs ${
                      selected ? "bg-surface" : "hover:bg-surface/50"
                    }`}
                  >
                    <span className={`font-mono font-medium ${mi.cls}`}>{mi.label}</span>
                    <span className="text-[10px] text-text-dim truncate">{mi.desc}</span>
                  </button>
                );
              }
              const ci = item as (typeof SLASH_COMMANDS)[number];
              return (
                <button
                  key={ci.cmd}
                  onClick={() => applyPopoverItem(i)}
                  onMouseEnter={() => setPopover({ ...popover, selected: i })}
                  className={`w-full text-left px-2 py-1 flex items-center gap-2 text-xs ${
                    selected ? "bg-surface" : "hover:bg-surface/50"
                  }`}
                >
                  <span className="font-mono font-medium text-amber">{ci.cmd}</span>
                  <span className="text-[10px] text-text-dim truncate">
                    {ci.desc}
                    {ci.usage ? ` · ${ci.usage}` : ""}
                  </span>
                </button>
              );
            })}
          </div>
        )}

        <div className="flex gap-1.5 items-end">
          <textarea
            ref={composerRef}
            className="input flex-1 resize-none leading-snug py-1 max-h-32"
            rows={1}
            placeholder="Message... type @ for LLM, / for command, Shift+Enter newline"
            value={input}
            onChange={(e) => {
              handleInputChange(e.target.value);
              // Auto-grow up to max-h
              const ta = e.target;
              ta.style.height = "auto";
              ta.style.height = Math.min(ta.scrollHeight, 128) + "px";
            }}
            onKeyDown={handleKeyDown}
            aria-label="Message composer"
            aria-describedby="composer-hint"
          />
          <button
            onClick={send}
            className="btn-primary px-2 py-1.5 self-stretch flex items-center justify-center disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={!input.trim() || sending}
            aria-label="Send message"
            title="Send (Enter)"
          >
            {sending ? <Loader size={12} className="animate-spin" /> : <Send size={12} />}
          </button>
        </div>
        <div
          id="composer-hint"
          className="flex items-center justify-between mt-0.5 text-[10px] text-text-dim font-mono"
        >
          <span>
            <kbd className="px-1 bg-elevated rounded border border-border text-[9px]">Enter</kbd> send ·{" "}
            <kbd className="px-1 bg-elevated rounded border border-border text-[9px]">⇧ Enter</kbd> newline ·{" "}
            <kbd className="px-1 bg-elevated rounded border border-border text-[9px]">@</kbd> LLM ·{" "}
            <kbd className="px-1 bg-elevated rounded border border-border text-[9px]">/</kbd> command
          </span>
          {input.length > 1500 && (
            <span className={input.length > 4000 ? "text-danger" : "text-amber"}>
              {input.length} chars
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Connection indicator
// ────────────────────────────────────────────────────────────────────────────

const ConnIndicator = memo(function ConnIndicator({ state }: { state: ConnState }) {
  if (state === "live") {
    return (
      <span
        className="flex items-center gap-0.5 text-[9px] font-mono text-green"
        title="WebSocket live"
      >
        <Wifi size={9} /> live
      </span>
    );
  }
  if (state === "connecting") {
    return (
      <span
        className="flex items-center gap-0.5 text-[9px] font-mono text-text-dim animate-pulse"
        title="Connecting..."
      >
        <Loader size={9} className="animate-spin" /> connecting
      </span>
    );
  }
  if (state === "stale") {
    return (
      <span
        className="flex items-center gap-0.5 text-[9px] font-mono text-amber"
        title="No traffic in 45s — connection may be stale"
      >
        <AlertCircle size={9} /> stale
      </span>
    );
  }
  return (
    <span
      className="flex items-center gap-0.5 text-[9px] font-mono text-danger"
      title="Disconnected — auto-reconnecting"
    >
      <WifiOff size={9} /> offline
    </span>
  );
});

// ────────────────────────────────────────────────────────────────────────────
// Empty / no-results states
// ────────────────────────────────────────────────────────────────────────────

function EmptyState({
  roomName,
  linkedBook,
  onSeed,
}: {
  roomName: string;
  linkedBook: string | null;
  onSeed: (text: string) => void;
}) {
  const seeds = [
    { label: "Get the morning brief", text: "/brief" },
    { label: "Snapshot the thesis state", text: linkedBook ? `/thesis ${linkedBook}` : "/thesis" },
    { label: "Ask Claude what's moving", text: "@claude What's the most important thing on the desk right now?" },
    { label: "Compare Claude vs GPT", text: "@compare Where do you disagree about the current setup?" },
  ];
  return (
    <div className="h-full flex items-center justify-center py-8">
      <div className="max-w-sm text-center space-y-3">
        <div className="text-[10px] uppercase tracking-widest text-text-dim font-mono">
          {roomName} · empty
        </div>
        <p className="text-xs text-text-muted">
          This room has no messages yet. Start a thread, mention an LLM, or run a slash command.
        </p>
        <div className="space-y-1 pt-1 text-left">
          {seeds.map((s) => (
            <button
              key={s.text}
              onClick={() => onSeed(s.text)}
              className="w-full px-2 py-1 rounded bg-elevated border border-border hover:border-amber/40 text-[11px] font-mono text-text-primary transition-colors flex items-center justify-between gap-2 group"
            >
              <span className="truncate">{s.label}</span>
              <span className="text-[10px] text-amber group-hover:text-amber-dim shrink-0">{s.text.split(" ")[0]}</span>
            </button>
          ))}
        </div>
        <div className="pt-2 text-[10px] text-text-dim font-mono">
          @claude @gpt @gemini @compare · /brief /thesis /diff /predict /watchlist
        </div>
      </div>
    </div>
  );
}

function NoSearchResults({ query, onClear }: { query: string; onClear: () => void }) {
  return (
    <div className="h-full flex items-center justify-center py-8">
      <div className="text-center space-y-2">
        <Search size={20} className="mx-auto text-text-dim" />
        <p className="text-xs text-text-muted">
          No matches for <span className="font-mono text-amber">"{query}"</span>
        </p>
        <button onClick={onClear} className="btn-secondary text-[10px]">
          Clear filter
        </button>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Message row — handles user / llm / system + collapsed-header runs
// ────────────────────────────────────────────────────────────────────────────

interface MessageRowProps {
  msg: Message;
  isMe: boolean;
  showHeader: boolean;
  isPinned: boolean;
  now: number;
  onPin: () => void;
  onUnpin: () => void;
  onRetryWith?: (model: string) => void;
}

const MessageRow = memo(function MessageRow({
  msg,
  isMe,
  showHeader,
  isPinned,
  now,
  onPin,
  onUnpin,
  onRetryWith,
}: MessageRowProps) {
  const [copied, setCopied] = useState(false);
  const [retryOpen, setRetryOpen] = useState(false);

  const copy = useCallback(() => {
    navigator.clipboard.writeText(msg.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }, [msg.content]);

  // System message — center-pill, full-width
  if (msg.msg_type === "system") {
    return (
      <div className="flex items-center gap-2 py-1 group" role="status">
        <div className="flex-1 h-px bg-border/50" />
        <span className="text-[10px] text-text-dim font-mono bg-elevated px-2 py-0.5 rounded border border-border max-w-[80%] whitespace-pre-wrap">
          {msg.content}
        </span>
        <span
          className="text-[9px] text-text-dim font-mono opacity-0 group-hover:opacity-100"
          title={absTime(msg.ts)}
        >
          {relTime(msg.ts, now)}
        </span>
        <div className="flex-1 h-px bg-border/50" />
      </div>
    );
  }

  const isLLM = msg.msg_type === "llm";
  const author = isLLM ? shortModelName(msg.model) : msg.user;
  const accentCls = isLLM ? modelBadgeClass(msg.model) : "";

  return (
    <div
      className={`group flex gap-2 ${isMe ? "flex-row-reverse" : ""} ${
        isPinned ? "border-l-2 border-amber/40 pl-1.5 -ml-2" : ""
      } ${showHeader ? "mt-1.5" : ""}`}
    >
      {/* Avatar (only on header rows; placeholder otherwise to keep alignment) */}
      <div className="shrink-0 w-5">
        {showHeader ? (
          isLLM ? (
            <div className={`w-5 h-5 rounded flex items-center justify-center border ${accentCls}`}>
              <Bot size={11} />
            </div>
          ) : (
            <div className="w-5 h-5 rounded bg-elevated flex items-center justify-center text-[10px] font-mono text-text-muted border border-border">
              {(msg.user[0] || "?").toUpperCase()}
            </div>
          )
        ) : (
          <div className="h-1" />
        )}
      </div>

      <div className={`min-w-0 flex-1 ${isMe ? "flex flex-col items-end" : ""}`}>
        {showHeader && (
          <div className={`flex items-center gap-1.5 mb-0.5 ${isMe ? "flex-row-reverse" : ""}`}>
            {isLLM ? (
              <span className={`text-[10px] font-mono px-1 py-px rounded border ${accentCls}`}>
                {author}
              </span>
            ) : (
              <span className={`text-[10px] font-medium ${isMe ? "text-amber" : "text-teal"}`}>
                {author}
              </span>
            )}
            <span className="text-[10px] text-text-dim font-mono" title={absTime(msg.ts)}>
              {relTime(msg.ts, now)}
            </span>
            {isPinned && (
              <Pin size={9} className="text-amber" aria-label="Pinned" />
            )}
          </div>
        )}

        <div
          className={`relative inline-block max-w-full ${isMe ? "text-right" : ""}`}
          onMouseLeave={() => setRetryOpen(false)}
        >
          {isLLM ? (
            <div className="text-xs prose prose-invert prose-xs max-w-none [&_p]:my-0.5 [&_pre]:bg-elevated [&_pre]:rounded [&_pre]:p-1.5 [&_pre]:text-[11px] [&_code]:text-teal [&_code]:text-[11px] [&_ul]:my-0.5 [&_ol]:my-0.5 [&_h1]:text-[13px] [&_h2]:text-[12px] [&_h3]:text-[11px]">
              <ReactMarkdown components={{ a: safeLink }}>{msg.content}</ReactMarkdown>
            </div>
          ) : (
            <div
              className={`inline-block px-2 py-1 rounded text-xs whitespace-pre-wrap break-words ${
                isMe
                  ? "bg-amber/10 border border-amber/20 text-text-primary"
                  : "bg-surface border border-border text-text-primary"
              }`}
            >
              {msg.content}
            </div>
          )}

          {/* Hover action bar — pin/unpin, copy, retry-with-different-model */}
          <div
            className={`absolute -top-2 ${
              isMe ? "left-0" : "right-0"
            } opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-px bg-elevated border border-border rounded shadow-md`}
          >
            <button
              onClick={copy}
              className="p-1 text-text-dim hover:text-text-primary"
              title="Copy"
              aria-label="Copy message"
            >
              {copied ? <Check size={10} className="text-green" /> : <Copy size={10} />}
            </button>
            <button
              onClick={isPinned ? onUnpin : onPin}
              className={`p-1 ${isPinned ? "text-amber" : "text-text-dim hover:text-amber"}`}
              title={isPinned ? "Unpin" : "Pin"}
              aria-label={isPinned ? "Unpin message" : "Pin message"}
            >
              <Pin size={10} />
            </button>
            {isLLM && onRetryWith && (
              <div className="relative">
                <button
                  onClick={() => setRetryOpen((o) => !o)}
                  className="p-1 text-text-dim hover:text-text-primary"
                  title="Retry with another model"
                  aria-label="Retry with another model"
                  aria-expanded={retryOpen}
                >
                  <RefreshCw size={10} />
                </button>
                {retryOpen && (
                  <div className="absolute top-full right-0 mt-0.5 bg-elevated border border-border rounded shadow-xl py-0.5 z-30 min-w-[110px]">
                    {Object.keys(MODEL_MAP).map((k) => (
                      <button
                        key={k}
                        onClick={() => {
                          onRetryWith(k);
                          setRetryOpen(false);
                        }}
                        className="w-full text-left px-2 py-0.5 text-[10px] font-mono text-text-primary hover:bg-surface flex items-center gap-1"
                      >
                        <RefreshCw size={9} className="text-text-dim" /> @{k}
                      </button>
                    ))}
                    <button
                      onClick={() => {
                        onRetryWith("compare");
                        setRetryOpen(false);
                      }}
                      className="w-full text-left px-2 py-0.5 text-[10px] font-mono text-teal hover:bg-surface flex items-center gap-1 border-t border-border"
                    >
                      <RefreshCw size={9} /> @compare
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
});

// ────────────────────────────────────────────────────────────────────────────
// "Thinking" placeholder — shown after LLM dispatch, before first chunk
// ────────────────────────────────────────────────────────────────────────────

const ThinkingBubble = memo(function ThinkingBubble({ model }: { model: string }) {
  return (
    <div className="flex gap-2 mt-1.5" role="status" aria-label={`${shortModelName(model)} is thinking`}>
      <div className="shrink-0">
        <div className={`w-5 h-5 rounded flex items-center justify-center border ${modelBadgeClass(model)}`}>
          <Bot size={11} />
        </div>
      </div>
      <div className="min-w-0">
        <span className={`inline-block text-[10px] font-mono px-1 py-px rounded border ${modelBadgeClass(model)}`}>
          {shortModelName(model)}
        </span>
        <div className="mt-0.5 inline-flex items-center gap-1.5 text-[11px] text-text-dim font-mono">
          <span className="flex gap-0.5">
            <span className="w-1 h-1 bg-text-dim rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
            <span className="w-1 h-1 bg-text-dim rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
            <span className="w-1 h-1 bg-text-dim rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
          </span>
          thinking...
        </div>
      </div>
    </div>
  );
});

// ────────────────────────────────────────────────────────────────────────────
// Streaming bubble — plain text + caret while tokens arrive
// ────────────────────────────────────────────────────────────────────────────

const StreamingBubble = memo(function StreamingBubble({
  model,
  text,
  latencyMs,
}: {
  model: string;
  text: string;
  latencyMs?: number;
}) {
  return (
    <div className="flex gap-2 mt-1.5" role="status" aria-label={`${shortModelName(model)} is responding`}>
      <div className="shrink-0">
        <div className={`w-5 h-5 rounded flex items-center justify-center border ${modelBadgeClass(model)}`}>
          <Bot size={11} />
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className={`inline-block text-[10px] font-mono px-1 py-px rounded border ${modelBadgeClass(model)}`}>
            {shortModelName(model)}
          </span>
          <span className="text-[9px] text-text-dim font-mono uppercase tracking-widest">streaming</span>
          {latencyMs !== undefined && (
            <span className="text-[9px] text-text-dim font-mono" title="Time to first token">
              ttft {latencyMs}ms
            </span>
          )}
        </div>
        <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap break-words leading-relaxed [&]:my-0">
          {text}
          <span className="inline-block w-1.5 h-3 bg-amber animate-pulse ml-0.5 align-middle" />
        </pre>
      </div>
    </div>
  );
});

// ────────────────────────────────────────────────────────────────────────────
// Optimistic pending row — sent locally, awaiting echo or showing failure
// ────────────────────────────────────────────────────────────────────────────

function PendingRow({
  pending,
  me,
  now,
  onRetry,
  onDismiss,
}: {
  pending: PendingMessage;
  me: string;
  now: number;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  const failed = pending.status === "failed";
  return (
    <div className="flex gap-2 flex-row-reverse mt-1.5 group">
      <div className="shrink-0 w-5">
        <div
          className={`w-5 h-5 rounded flex items-center justify-center text-[10px] font-mono border ${
            failed ? "bg-danger/20 text-danger border-danger/30" : "bg-elevated text-text-muted border-border"
          }`}
        >
          {(me[0] || "?").toUpperCase()}
        </div>
      </div>
      <div className="min-w-0 flex flex-col items-end">
        <div className="flex items-center gap-1.5 mb-0.5">
          <span className="text-[10px] font-medium text-amber">{me}</span>
          <span className="text-[10px] text-text-dim font-mono" title={absTime(pending.ts)}>
            {relTime(pending.ts, now)}
          </span>
          {failed ? (
            <span className="text-[9px] font-mono text-danger uppercase tracking-widest">failed</span>
          ) : (
            <span className="text-[9px] font-mono text-text-dim uppercase tracking-widest flex items-center gap-0.5">
              <Loader size={8} className="animate-spin" /> sending
            </span>
          )}
        </div>
        <div
          className={`inline-block px-2 py-1 rounded text-xs whitespace-pre-wrap break-words ${
            failed
              ? "bg-danger/10 border border-danger/30 text-text-primary"
              : "bg-amber/10 border border-amber/20 text-text-muted"
          }`}
        >
          {pending.content}
        </div>
        {failed && (
          <div className="flex items-center gap-1 mt-0.5">
            {pending.error && (
              <span className="text-[9px] text-danger font-mono">{pending.error.slice(0, 80)}</span>
            )}
            <button
              onClick={onRetry}
              className="text-[10px] font-mono text-amber hover:text-amber-dim flex items-center gap-0.5"
            >
              <RefreshCw size={9} /> retry
            </button>
            <button
              onClick={onDismiss}
              className="text-[10px] font-mono text-text-dim hover:text-text-primary"
            >
              dismiss
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
