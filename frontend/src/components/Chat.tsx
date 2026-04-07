import { useState, useEffect, useRef, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { Send, Bot, User as UserIcon } from "lucide-react";
import { apiFetch, getUsername, RoomSocket } from "../lib/api";
import type { Room, Message, ThesisBook, WSMessage } from "../lib/types";

interface Props {
  room: Room;
  books: ThesisBook[];
}

export default function Chat({ room }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState<Record<string, string>>({});
  const scrollRef = useRef<HTMLDivElement>(null);
  const socketRef = useRef<RoomSocket | null>(null);
  const me = getUsername();

  // Load history
  useEffect(() => {
    apiFetch<Message[]>(`/api/rooms/${room.id}/messages?limit=100`)
      .then(setMessages)
      .catch(() => {});
  }, [room.id]);

  // WebSocket
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
        const { token, model } = msg.payload as { token: string; model: string };
        setStreaming((prev) => ({
          ...prev,
          [model]: (prev[model] || "") + token,
        }));
      } else if (msg.type === "llm_done") {
        const { model } = msg.payload as { model: string };
        setStreaming((prev) => {
          const next = { ...prev };
          delete next[model];
          return next;
        });
      }
    });

    return () => {
      unsub();
      sock.close();
    };
  }, [room.id]);

  // Auto-scroll
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, streaming]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text) return;
    setInput("");

    // Check for @model mentions
    const mentionMatch = text.match(/^@(claude|gpt|llama|gemini|compare)\s+/i);
    if (mentionMatch) {
      const cmd = mentionMatch[1].toLowerCase();
      const prompt = text.slice(mentionMatch[0].length);
      if (cmd === "compare") {
        // Save user message first
        await apiFetch(`/api/rooms/${room.id}/messages`, {
          method: "POST",
          body: JSON.stringify({ content: text }),
        });
        apiFetch("/api/llm/compare", {
          method: "POST",
          body: JSON.stringify({ prompt, room_id: room.id }),
        }).catch(() => {});
      } else {
        const modelMap: Record<string, string> = {
          claude: "anthropic/claude-sonnet-4-20250514",
          gpt: "openai/gpt-4o",
          llama: "meta-llama/llama-3.1-405b-instruct",
          gemini: "google/gemini-2.0-flash-001",
        };
        await apiFetch(`/api/rooms/${room.id}/messages`, {
          method: "POST",
          body: JSON.stringify({ content: text }),
        });
        apiFetch("/api/llm/chat", {
          method: "POST",
          body: JSON.stringify({ prompt, model: modelMap[cmd], room_id: room.id }),
        }).catch(() => {});
      }
    } else {
      // Normal message
      await apiFetch(`/api/rooms/${room.id}/messages`, {
        method: "POST",
        body: JSON.stringify({ content: text }),
      });
    }
  }, [input, room.id]);

  return (
    <div className="flex flex-col h-full">
      {/* Room header */}
      <div className="px-4 py-2 border-b border-border bg-surface/50 shrink-0">
        <h2 className="text-sm font-medium">{room.name}</h2>
        {room.topic && <p className="text-xs text-text-dim">{room.topic}</p>}
        {room.linked_book_id && (
          <p className="text-xs text-teal font-mono">{room.linked_book_id}</p>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} isMe={msg.user === me} />
        ))}
        {/* Streaming indicators */}
        {Object.entries(streaming).map(([model, text]) => (
          <div key={model} className="flex gap-2">
            <div className="shrink-0 mt-0.5">
              <div className="w-6 h-6 rounded bg-teal/20 flex items-center justify-center">
                <Bot size={14} className="text-teal" />
              </div>
            </div>
            <div className="min-w-0">
              <span className="text-xs font-mono text-teal">{model}</span>
              <div className="text-sm text-text-primary prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{text + " ..."}</ReactMarkdown>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-border bg-surface/50 shrink-0">
        <div className="flex gap-2">
          <input
            className="input flex-1"
            placeholder="Message... (@claude, @gpt, @compare for AI)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button onClick={send} className="btn-primary px-3" disabled={!input.trim()}>
            <Send size={14} />
          </button>
        </div>
        <p className="text-xs text-text-dim mt-1">@claude @gpt @llama @gemini @compare</p>
      </div>
    </div>
  );
}

function MessageBubble({ msg, isMe }: { msg: Message; isMe: boolean }) {
  const isLLM = msg.msg_type === "llm";
  const isSystem = msg.msg_type === "system";

  if (isSystem) {
    return (
      <div className="text-center text-xs text-text-dim py-1">
        {msg.content}
      </div>
    );
  }

  return (
    <div className={`flex gap-2 ${isMe ? "" : ""}`}>
      <div className="shrink-0 mt-0.5">
        <div className={`w-6 h-6 rounded flex items-center justify-center text-xs font-mono ${
          isLLM ? "bg-teal/20 text-teal" : "bg-elevated text-text-muted"
        }`}>
          {isLLM ? <Bot size={14} /> : <UserIcon size={14} />}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className={`text-xs font-medium ${isLLM ? "text-teal" : "text-amber"}`}>
            {msg.user}
          </span>
          {msg.model && <span className="text-xs font-mono text-text-dim">{msg.model}</span>}
          <span className="text-xs text-text-dim">
            {new Date(msg.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
        {isLLM ? (
          <div className="text-sm prose prose-invert prose-sm max-w-none [&_p]:my-1 [&_pre]:bg-elevated [&_pre]:rounded [&_pre]:p-2 [&_code]:text-teal">
            <ReactMarkdown>{msg.content}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
        )}
      </div>
    </div>
  );
}
