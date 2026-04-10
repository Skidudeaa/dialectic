import { useState, useEffect, useRef, useCallback, memo } from "react";
import ReactMarkdown from "react-markdown";
import { Send, Bot, Loader, Pin, Download, ChevronDown } from "lucide-react";
import { apiFetch, getUsername, RoomSocket } from "../lib/api";
import type { Room, Message, WSMessage } from "../lib/types";

interface Props {
  room: Room;
}

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
  if (model.toLowerCase().includes("claude")) return "bg-amber/20 text-amber border-amber/30";
  if (model.toLowerCase().includes("gpt")) return "bg-green/20 text-green border-green/30";
  if (model.toLowerCase().includes("deepseek")) return "bg-purple/20 text-purple border-purple/30";
  if (model.toLowerCase().includes("gemini")) return "bg-blue/20 text-blue border-blue/30";
  return "bg-teal/20 text-teal border-teal/30";
}

// WHY: Prevent javascript: URL XSS in LLM-generated markdown links.
const safeLink = ({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { children?: React.ReactNode }) => {
  if (href && (href.startsWith("http://") || href.startsWith("https://"))) {
    return <a {...props} href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
  }
  return <span>{children}</span>;
};

export default function Chat({ room }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  // WHY: Streaming tokens accumulate in a ref (no re-render per token).
  // A RAF loop flushes the ref to display state at ~60fps max, eliminating
  // the per-token re-render + ReactMarkdown parse that caused jank.
  const [streamDisplay, setStreamDisplay] = useState<Record<string, string>>({});
  const streamRef = useRef<Record<string, string>>({});
  const streamDirtyRef = useRef(false);
  const rafRef = useRef<number>(0);
  const [sending, setSending] = useState(false);
  const [typingUsers, setTypingUsers] = useState<Set<string>>(new Set());
  const [onlineUsers, setOnlineUsers] = useState<Array<{ username: string; viewing: string }>>([]);
  const [pins, setPins] = useState<Message[]>([]);
  const [pinsOpen, setPinsOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const socketRef = useRef<RoomSocket | null>(null);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const me = getUsername();

  // RAF flush loop — syncs accumulated tokens to display state
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

  useEffect(() => {
    apiFetch<Message[]>(`/api/rooms/${room.id}/messages?limit=100`).then(setMessages).catch(() => {});
    apiFetch<Message[]>(`/api/rooms/${room.id}/pins`).then(setPins).catch(() => {});
  }, [room.id]);

  useEffect(() => {
    const sock = new RoomSocket(room.id);
    socketRef.current = sock;
    const unsub = sock.subscribe((msg: WSMessage) => {
      if (msg.type === "message") {
        const m = msg.payload as unknown as Message;
        setMessages((prev) => {
          if (prev.some((p) => p.id === m.id)) return prev;
          return [...prev, m];
        });
      } else if (msg.type === "llm_chunk") {
        // WHY: Accumulate in ref, not state. RAF loop flushes to display.
        // This eliminates O(tokens) re-renders — display updates at screen refresh rate.
        const { token, model } = msg.payload as { token: string; model: string };
        streamRef.current[model] = (streamRef.current[model] || "") + token;
        streamDirtyRef.current = true;
      } else if (msg.type === "llm_done") {
        const { model } = msg.payload as { model: string };
        delete streamRef.current[model];
        streamDirtyRef.current = true;
      } else if (msg.type === "typing") {
        const { username, typing } = msg.payload as { username: string; typing: boolean };
        setTypingUsers((prev) => {
          const next = new Set(prev);
          if (typing) next.add(username); else next.delete(username);
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
  }, [room.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streamDisplay]);

  const postSystem = useCallback(async (content: string) => {
    await apiFetch(`/api/rooms/${room.id}/messages`, {
      method: "POST", body: JSON.stringify({ content, msg_type: "system" }),
    });
  }, [room.id]);

  const pinMessage = useCallback(async (msg: Message) => {
    const updated = await apiFetch<Message[]>(`/api/rooms/${room.id}/pins`, {
      method: "POST", body: JSON.stringify(msg),
    });
    setPins(updated);
  }, [room.id]);

  const unpinMessage = useCallback(async (messageId: string) => {
    const updated = await apiFetch<Message[]>(`/api/rooms/${room.id}/pins/${messageId}`, {
      method: "DELETE",
    });
    setPins(updated);
  }, [room.id]);

  const exportChat = useCallback(async () => {
    const data = await apiFetch<{ markdown: string }>(`/api/rooms/${room.id}/export`);
    const blob = new Blob([data.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${room.name}-${new Date().toISOString().slice(0, 10)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }, [room.id, room.name]);

  const handleSlashCommand = useCallback(async (text: string): Promise<boolean> => {
    const cmd = text.split(/\s+/)[0].toLowerCase();
    const args = text.slice(cmd.length).trim();

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
      const fired = Object.entries(ns).filter(([, v]) => v === "fired").map(([k]) => k);
      const approaching = Object.entries(ns).filter(([, v]) => v === "approaching").map(([k]) => k);
      const topConf = Object.entries(cs).sort(([, a], [, b]) => b - a).slice(0, 5);
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
      return true;
    }
    if (cmd === "/predict") {
      const match = args.match(/^"([^"]+)"\s+(\d+)%$/);
      if (match) {
        const deadline = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
        await apiFetch("/api/predictions", {
          method: "POST",
          body: JSON.stringify({ statement: match[1], confidence: parseInt(match[2]) / 100, deadline }),
        });
        await postSystem(`Prediction created: "${match[1]}" at ${match[2]}%`);
      } else {
        await postSystem('Usage: /predict "statement" 75%');
      }
      return true;
    }
    if (cmd === "/watchlist") {
      const items = await apiFetch<Array<{ symbol: string; label: string; last_price: number | null }>>("/api/market/watchlist");
      const lines = items.map((i) => `${i.symbol.padEnd(6)} ${i.last_price !== null ? i.last_price.toFixed(2) : "--"} ${i.label}`);
      await postSystem("WATCHLIST\n" + lines.join("\n"));
      return true;
    }
    return false;
  }, [room.id, room.linked_book_id, postSystem]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);

    try {
      // Slash commands
      if (text.startsWith("/")) {
        const handled = await handleSlashCommand(text);
        if (handled) { setSending(false); return; }
      }

      // @model mentions
      const mentionMatch = text.match(/^@(claude|gpt|deepseek|gemini|compare)\s+/i);
      if (mentionMatch) {
        const cmd = mentionMatch[1].toLowerCase();
        const prompt = text.slice(mentionMatch[0].length);
        await apiFetch(`/api/rooms/${room.id}/messages`, {
          method: "POST", body: JSON.stringify({ content: text }),
        });
        if (cmd === "compare") {
          apiFetch("/api/llm/compare", {
            method: "POST", body: JSON.stringify({ prompt, room_id: room.id }),
          }).catch((err) => {
            console.error("LLM compare failed:", err);
          });
        } else {
          const modelMap: Record<string, string> = {
            claude: "anthropic/claude-sonnet-4.6",
            gpt: "openai/gpt-5.3-chat",
            deepseek: "deepseek/deepseek-r1",
            gemini: "google/gemini-3.1-pro-preview",
          };
          apiFetch("/api/llm/chat", {
            method: "POST", body: JSON.stringify({ prompt, model: modelMap[cmd], room_id: room.id }),
          }).catch((err) => {
            console.error("LLM chat failed:", err);
          });
        }
      } else {
        // Normal message
        await apiFetch(`/api/rooms/${room.id}/messages`, {
          method: "POST", body: JSON.stringify({ content: text }),
        });
      }
    } catch { /* ignore */ }
    setSending(false);
  }, [input, room.id, sending, handleSlashCommand]);

  const handleInputChange = useCallback((value: string) => {
    setInput(value);
    // Send typing indicator
    socketRef.current?.sendTyping(true);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    typingTimerRef.current = setTimeout(() => {
      socketRef.current?.sendTyping(false);
    }, 2000);
  }, []);

  const typingList = Array.from(typingUsers).filter((u) => u !== me);

  return (
    <div className="flex flex-col h-full">
      {/* Room header with presence + actions */}
      <div className="px-3 py-1 border-b border-border bg-surface shrink-0 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-medium">{room.name}</h2>
            {room.linked_book_id && (
              <span className="text-[10px] text-teal font-mono">{room.linked_book_id}</span>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            {onlineUsers.map((u) => (
              <span key={u.username} className="flex items-center gap-0.5 text-[10px] font-mono text-text-dim">
                <span className="w-1.5 h-1.5 rounded-full bg-green inline-block" />
                {u.username}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          {pins.length > 0 && (
            <button onClick={() => setPinsOpen(!pinsOpen)} className="flex items-center gap-0.5 text-[10px] font-mono text-amber hover:text-amber-dim p-0.5">
              <Pin size={10} /> {pins.length}
            </button>
          )}
          <button onClick={exportChat} className="text-text-dim hover:text-text-primary p-0.5" title="Export chat">
            <Download size={11} />
          </button>
        </div>
      </div>

      {/* Pinned messages */}
      {pinsOpen && pins.length > 0 && (
        <div className="border-b border-amber/20 bg-amber/5 px-3 py-1.5 max-h-32 overflow-y-auto">
          <div className="flex items-center justify-between mb-0.5">
            <span className="text-[10px] text-amber font-mono uppercase tracking-widest">Pinned</span>
            <button onClick={() => setPinsOpen(false)} className="text-text-dim hover:text-text-primary"><ChevronDown size={10} /></button>
          </div>
          {pins.map((p) => (
            <div key={p.id} className="flex items-start justify-between py-0.5 group">
              <div className="min-w-0 mr-1">
                <span className="text-[10px] text-amber font-mono">{p.user}</span>
                <p className="text-[11px] text-text-primary truncate">{p.content.slice(0, 120)}</p>
              </div>
              <button onClick={() => unpinMessage(p.id)} className="text-text-dim hover:text-danger opacity-0 group-hover:opacity-100 shrink-0" title="Unpin">
                <Pin size={9} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-3 py-2 space-y-1.5">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} isMe={msg.user === me} onPin={() => pinMessage(msg)} />
        ))}
        {Object.entries(streamDisplay).map(([model, text]) => (
          <StreamingBubble key={model} model={model} text={text} />
        ))}
      </div>

      {/* Typing indicator + Input */}
      <div className="px-3 py-1.5 border-t border-border bg-surface shrink-0">
        {typingList.length > 0 && (
          <p className="text-[10px] text-text-dim font-mono mb-0.5 animate-pulse">
            {typingList.join(", ")} typing...
          </p>
        )}
        <div className="flex gap-1.5">
          <input
            className="input flex-1"
            placeholder="Message... (@claude, @gpt, @deepseek, @gemini, @compare)"
            value={input}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
          />
          <button onClick={send} className="btn-primary px-2" disabled={!input.trim() || sending || Object.keys(streamDisplay).length > 0}>
            {sending || Object.keys(streamDisplay).length > 0
              ? <Loader size={12} className="animate-spin" />
              : <Send size={12} />}
          </button>
        </div>
        <p className="text-[10px] text-text-dim mt-0.5 font-mono">@claude @gpt @deepseek @gemini @compare | /brief /thesis /diff /predict /watchlist</p>
      </div>
    </div>
  );
}

function MessageBubble({ msg, isMe, onPin }: { msg: Message; isMe: boolean; onPin?: () => void }) {
  const isLLM = msg.msg_type === "llm";
  const isSystem = msg.msg_type === "system";

  if (isSystem) {
    return (
      <div className="text-center py-0.5">
        <span className="text-[10px] text-text-dim font-mono bg-elevated px-2 py-0.5 rounded">
          {msg.content}
        </span>
      </div>
    );
  }

  if (isLLM) {
    return (
      <div className="flex gap-2 max-w-[85%] group">
        <div className="shrink-0 mt-0.5">
          <div className={`w-5 h-5 rounded flex items-center justify-center ${modelBadgeClass(msg.model)}`}>
            <Bot size={11} />
          </div>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className={`inline-block text-[10px] font-mono px-1 py-0.5 rounded border ${modelBadgeClass(msg.model)}`}>
              {msg.model || "ai"}
            </span>
            <span className="text-[10px] text-text-dim font-mono">
              {new Date(msg.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
            {onPin && (
              <button onClick={onPin} className="opacity-0 group-hover:opacity-100 text-text-dim hover:text-amber transition-opacity" title="Pin">
                <Pin size={9} />
              </button>
            )}
          </div>
          <div className="text-xs prose prose-invert prose-xs max-w-none [&_p]:my-0.5 [&_pre]:bg-elevated [&_pre]:rounded [&_pre]:p-1.5 [&_pre]:text-[11px] [&_code]:text-teal [&_code]:text-[11px]">
            <ReactMarkdown components={{ a: safeLink }}>{msg.content}</ReactMarkdown>
          </div>
        </div>
      </div>
    );
  }

  // User message
  return (
    <div className={`flex gap-2 group ${isMe ? "flex-row-reverse" : ""}`}>
      <div className="shrink-0 mt-0.5">
        <div className="w-5 h-5 rounded bg-elevated flex items-center justify-center text-[10px] font-mono text-text-muted">
          {msg.user[0]?.toUpperCase()}
        </div>
      </div>
      <div className={`min-w-0 max-w-[75%] ${isMe ? "text-right" : ""}`}>
        <div className={`flex items-center gap-1.5 mb-0.5 ${isMe ? "justify-end" : ""}`}>
          <span className="text-[10px] font-medium text-amber">{msg.user}</span>
          <span className="text-[10px] text-text-dim font-mono">
            {new Date(msg.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
          {onPin && (
            <button onClick={onPin} className="opacity-0 group-hover:opacity-100 text-text-dim hover:text-amber transition-opacity" title="Pin">
              <Pin size={9} />
            </button>
          )}
        </div>
        <div className={`inline-block px-2 py-1 rounded text-xs ${isMe ? "bg-elevated text-text-primary" : "bg-surface border border-border text-text-primary"}`}>
          {msg.content}
        </div>
      </div>
    </div>
  );
}

/**
 * WHY: Streaming text renders as plain <pre> — no markdown parsing per frame.
 * ReactMarkdown is expensive (parse + render tree diff on every update).
 * Plain text at 60fps feels instant. The final llm_done message renders with
 * full ReactMarkdown via MessageBubble.
 *
 * TRADEOFF: Users see raw markdown syntax while streaming (**, ##, etc.)
 * but get full rendering on completion. This matches terminal UX expectations
 * for a trading desk tool — speed > prettiness during generation.
 */
const StreamingBubble = memo(function StreamingBubble({ model, text }: { model: string; text: string }) {
  return (
    <div className="flex gap-2 max-w-[85%]">
      <div className="shrink-0 mt-0.5">
        <div className={`w-5 h-5 rounded flex items-center justify-center ${modelBadgeClass(model)}`}>
          <Bot size={11} />
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <span className={`inline-block text-[10px] font-mono px-1 py-0.5 rounded border mb-0.5 ${modelBadgeClass(model)}`}>{model}</span>
        <pre className="text-xs font-mono text-text-primary whitespace-pre-wrap break-words leading-relaxed [&]:my-0">
          {text}
          <span className="inline-block w-1.5 h-3 bg-amber animate-pulse ml-0.5 align-middle" />
        </pre>
      </div>
    </div>
  );
});
