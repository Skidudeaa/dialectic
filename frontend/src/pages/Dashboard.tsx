import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  MessageSquare,
  BarChart3,
  FileText,
  Scan,
  LogOut,
  Plus,
  ChevronLeft,
  Activity,
  Keyboard,
  Wifi,
  WifiOff,
  Search,
  Book,
  Hammer,
} from "lucide-react";
import { apiFetch, getDisplayName, clearAuth } from "../lib/api";
import type { Room, ThesisBook } from "../lib/types";
import Chat from "../components/Chat";
import ThesisViewer from "../components/ThesisViewer";
import MarketTicker from "../components/MarketTicker";
import MorningBrief from "../components/MorningBrief";
import PredictionTracker from "../components/PredictionTracker";
import TradeJournal from "../components/TradeJournal";
import CrossBookPanel from "../components/CrossBookPanel";
import TradingViewPanel from "../components/TradingViewPanel";
import OutboxBadge from "../components/OutboxBadge";
import { useToast } from "../components/toast";

interface Props {
  onLogout: () => void;
}

type RightPanel =
  | "thesis"
  | "predictions"
  | "journal"
  | "crossbook"
  | "brief"
  | "tradingview"
  | null;

const RECENT_CMDS_KEY = "td_cmd_recents";
const RIGHT_WIDTH_KEY = "td_right_panel_width";
const ACTIVE_BOOK_KEY = "td_active_book";

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

/** Lightweight online/offline indicator using the platform `online` event +
 *  a periodic /api/health probe. Subtle when good, loud when broken. */
function useConnectionStatus(): "online" | "reconnecting" | "offline" {
  const [status, setStatus] = useState<"online" | "reconnecting" | "offline">(
    navigator.onLine ? "online" : "offline",
  );
  useEffect(() => {
    let cancelled = false;
    let failures = 0;

    async function probe() {
      try {
        const r = await fetch("/api/health", { cache: "no-store" });
        if (cancelled) return;
        if (r.ok) {
          failures = 0;
          setStatus("online");
        } else {
          failures += 1;
          setStatus(failures >= 2 ? "offline" : "reconnecting");
        }
      } catch {
        if (cancelled) return;
        failures += 1;
        setStatus(failures >= 2 ? "offline" : "reconnecting");
      }
    }

    const onOnline = () => setStatus("reconnecting");
    const onOffline = () => setStatus("offline");
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);

    probe();
    const interval = setInterval(probe, 20_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);
  return status;
}

function loadRecents(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_CMDS_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.filter((x) => typeof x === "string").slice(0, 5) : [];
  } catch {
    return [];
  }
}
function pushRecent(label: string): string[] {
  const cur = loadRecents();
  const next = [label, ...cur.filter((l) => l !== label)].slice(0, 5);
  try {
    localStorage.setItem(RECENT_CMDS_KEY, JSON.stringify(next));
  } catch {
    /* ignore quota */
  }
  return next;
}

export default function Dashboard({ onLogout }: Props) {
  const navigate = useNavigate();
  const isNarrow = useMediaQuery("(max-width: 1024px)");
  const isVeryNarrow = useMediaQuery("(max-width: 640px)");
  const isMac = useMemo(() => /Mac|iPhone|iPad/.test(navigator.platform), []);
  const modKey = isMac ? "Cmd" : "Ctrl";
  const { toast } = useToast();
  const connection = useConnectionStatus();

  const [rooms, setRooms] = useState<Room[]>([]);
  const [books, setBooks] = useState<ThesisBook[]>([]);
  const [activeRoom, setActiveRoom] = useState<Room | null>(null);
  const [activeBookOverride, setActiveBookOverride] = useState<string | null>(() => {
    try {
      return localStorage.getItem(ACTIVE_BOOK_KEY);
    } catch {
      return null;
    }
  });
  const [rightPanel, setRightPanel] = useState<RightPanel>("thesis");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showNewRoom, setShowNewRoom] = useState(false);
  const [newRoomName, setNewRoomName] = useState("");
  const [newRoomBook, setNewRoomBook] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [cmdPalette, setCmdPalette] = useState(false);
  const [cmdQuery, setCmdQuery] = useState("");
  const [cmdIndex, setCmdIndex] = useState(0);
  const [recents, setRecents] = useState<string[]>(() => loadRecents());

  // Persisted right-panel width (clamped 260..520) — drag-to-resize gutter.
  const [rightWidth, setRightWidth] = useState<number>(() => {
    try {
      const v = parseInt(localStorage.getItem(RIGHT_WIDTH_KEY) || "", 10);
      if (!Number.isFinite(v)) return 320;
      return Math.max(260, Math.min(520, v));
    } catch {
      return 320;
    }
  });

  const loadRooms = useCallback(async () => {
    try {
      const data = await apiFetch<Room[]>("/api/rooms");
      setRooms(data);
    } catch {
      toast("Failed to load rooms", "error");
    }
    // toast is stable; lint silenced for clarity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadBooks = useCallback(async () => {
    try {
      const data = await apiFetch<ThesisBook[]>("/api/thesis/books");
      setBooks(data);
    } catch {
      toast("Failed to load books", "error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadRooms();
    loadBooks();
  }, [loadRooms, loadBooks]);

  async function createRoom() {
    if (!newRoomName.trim()) return;
    try {
      const room = await apiFetch<Room>("/api/rooms", {
        method: "POST",
        body: JSON.stringify({
          name: newRoomName.trim(),
          linked_book_id: newRoomBook || null,
        }),
      });
      setRooms((prev) => [...prev, room]);
      setActiveRoom(room);
      setShowNewRoom(false);
      setNewRoomName("");
      setNewRoomBook("");
    } catch {
      toast("Failed to create room", "error");
    }
  }

  function handleLogout() {
    clearAuth();
    onLogout();
  }

  // Auto-collapse panels on narrow screens
  useEffect(() => {
    if (isNarrow) setSidebarOpen(false);
  }, [isNarrow]);
  // On very narrow viewports, hide right panel entirely until the user opens it.
  useEffect(() => {
    if (isVeryNarrow) setRightPanel(null);
  }, [isVeryNarrow]);

  function togglePanel(p: RightPanel) {
    setRightPanel((prev) => (prev === p ? null : p));
  }

  function setActiveBookExplicit(id: string | null) {
    setActiveBookOverride(id);
    try {
      if (id) localStorage.setItem(ACTIVE_BOOK_KEY, id);
      else localStorage.removeItem(ACTIVE_BOOK_KEY);
    } catch {
      /* ignore */
    }
  }

  // Resolve which book the right panels render against.
  // Priority: explicit operator override → active room link → first book.
  const linkedBookId = useMemo(() => {
    if (activeBookOverride && books.some((b) => b.id === activeBookOverride)) {
      return activeBookOverride;
    }
    return activeRoom?.linked_book_id || books[0]?.id || null;
  }, [activeBookOverride, books, activeRoom]);

  // Command palette items — recents bubble to top.
  type CmdItem = { label: string; type: "room" | "panel" | "action"; action: () => void };
  const allCmdItems: CmdItem[] = useMemo(
    () => [
      ...rooms.map((r) => ({
        label: r.name,
        type: "room" as const,
        action: () => {
          setActiveRoom(r);
          setCmdPalette(false);
        },
      })),
      { label: "Thesis panel", type: "panel", action: () => { togglePanel("thesis"); setCmdPalette(false); } },
      { label: "Morning brief", type: "panel", action: () => { togglePanel("brief"); setCmdPalette(false); } },
      { label: "Cross-book scan", type: "panel", action: () => { togglePanel("crossbook"); setCmdPalette(false); } },
      { label: "Predictions", type: "panel", action: () => { togglePanel("predictions"); setCmdPalette(false); } },
      { label: "Trade journal", type: "panel", action: () => { togglePanel("journal"); setCmdPalette(false); } },
      { label: "TradingView", type: "panel", action: () => { togglePanel("tradingview"); setCmdPalette(false); } },
      { label: "New room", type: "action", action: () => { setShowNewRoom(true); setSidebarOpen(true); setCmdPalette(false); } },
      { label: "Show keyboard shortcuts", type: "action", action: () => { setShowShortcuts(true); setCmdPalette(false); } },
      { label: "Logout", type: "action", action: () => { handleLogout(); setCmdPalette(false); } },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rooms],
  );

  const cmdItems = useMemo(() => {
    const q = cmdQuery.trim().toLowerCase();
    const filtered = q
      ? allCmdItems.filter((it) => it.label.toLowerCase().includes(q))
      : // No query: show recents first (up to 5), then everything else dedup'd.
        (() => {
          const recentSet = new Set(recents);
          const recentItems = recents
            .map((label) => allCmdItems.find((it) => it.label === label))
            .filter((x): x is CmdItem => Boolean(x));
          const rest = allCmdItems.filter((it) => !recentSet.has(it.label));
          return [...recentItems, ...rest];
        })();
    return filtered;
  }, [cmdQuery, allCmdItems, recents]);

  // Reset selected index when the filtered list changes.
  useEffect(() => {
    setCmdIndex(0);
  }, [cmdQuery, cmdPalette]);

  // Wrap a command activation with recents tracking.
  function activateCmd(item: CmdItem) {
    setRecents(pushRecent(item.label));
    item.action();
  }

  // Keyboard shortcuts (global)
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // Cmd/Ctrl+K — command palette
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdPalette((prev) => !prev);
        setCmdQuery("");
        return;
      }
      // Cmd/Ctrl+B — toggle sidebar
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setSidebarOpen((s) => !s);
        return;
      }
      // ? — shortcut overlay (only when not typing in a field)
      const tag = (e.target as HTMLElement | null)?.tagName;
      const isTyping = tag === "INPUT" || tag === "TEXTAREA" || (e.target as HTMLElement)?.isContentEditable;
      if (e.key === "?" && !isTyping && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setShowShortcuts((s) => !s);
        return;
      }
      // Escape — unwind UI surfaces in priority order
      if (e.key === "Escape") {
        if (cmdPalette) { setCmdPalette(false); return; }
        if (showShortcuts) { setShowShortcuts(false); return; }
        if (rightPanel && isVeryNarrow) { setRightPanel(null); return; }
        if (sidebarOpen && isNarrow) { setSidebarOpen(false); return; }
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [cmdPalette, showShortcuts, rightPanel, sidebarOpen, isNarrow, isVeryNarrow]);

  // Drag-to-resize gutter for the right panel.
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);
  function onDragStart(e: React.MouseEvent) {
    dragRef.current = { startX: e.clientX, startW: rightWidth };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function onMove(ev: MouseEvent) {
      if (!dragRef.current) return;
      const dx = dragRef.current.startX - ev.clientX; // dragging left widens
      const next = Math.max(260, Math.min(520, dragRef.current.startW + dx));
      setRightWidth(next);
    }
    function onUp() {
      dragRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      try {
        localStorage.setItem(RIGHT_WIDTH_KEY, String(rightWidth));
      } catch {
        /* ignore */
      }
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }
  // Persist on width change too (covers programmatic / resize fallbacks).
  useEffect(() => {
    try {
      localStorage.setItem(RIGHT_WIDTH_KEY, String(rightWidth));
    } catch {
      /* ignore */
    }
  }, [rightWidth]);

  const activeBook = books.find((b) => b.id === linkedBookId) || null;

  return (
    <div className="h-screen flex flex-col bg-void overflow-hidden">
      {/* Top bar */}
      <header className="h-8 bg-surface border-b border-border flex items-center px-2 shrink-0 gap-1">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="text-text-dim hover:text-text-primary p-0.5"
          title={`Toggle sidebar (${modKey}+B)`}
          aria-label="Toggle sidebar"
        >
          <ChevronLeft size={13} className={`transition-transform ${sidebarOpen ? "" : "rotate-180"}`} />
        </button>
        <span className="font-mono text-amber font-semibold text-xs">tradingDesk</span>

        {/* Active room */}
        {activeRoom && (
          <span className="text-text-dim text-[10px] ml-1 font-mono truncate max-w-[14ch] hidden sm:inline">
            / {activeRoom.name}
          </span>
        )}

        {/* Book switcher — only when >1 book exists; otherwise quiet single-book label */}
        {books.length > 1 ? (
          <label className="ml-2 hidden md:flex items-center gap-1">
            <Book size={11} className="text-text-dim" aria-hidden="true" />
            <select
              className="bg-elevated border border-border rounded px-1 py-px text-[10px] font-mono text-text-primary focus:outline-none focus:border-amber/50 max-w-[18ch]"
              value={linkedBookId || ""}
              onChange={(e) => setActiveBookExplicit(e.target.value || null)}
              title="Active thesis book"
              aria-label="Active thesis book"
            >
              {books.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.title}
                </option>
              ))}
            </select>
          </label>
        ) : (
          activeBook && (
            <span className="ml-2 hidden md:inline text-text-dim text-[10px] font-mono truncate max-w-[20ch]">
              · {activeBook.title}
            </span>
          )
        )}

        {/* Builder buttons */}
        <div className="flex items-center gap-1 ml-2">
          <button
            onClick={() => navigate("/builder")}
            className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono text-text-dim hover:text-amber bg-elevated rounded border border-border"
            title="Create new thesis"
          >
            <Plus size={10} /> New Thesis
          </button>
          {linkedBookId && (
            <button
              onClick={() => navigate(`/builder?edit=${linkedBookId}`)}
              className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono text-text-dim hover:text-amber bg-elevated rounded border border-border"
              title="Edit current thesis in builder"
            >
              <Hammer size={10} /> Edit
            </button>
          )}
        </div>
pass
        {/* Command palette hint — center-ish, clickable */}
        <button
          onClick={() => { setCmdPalette(true); setCmdQuery(""); }}
          className="ml-3 hidden md:inline-flex items-center gap-1 text-[10px] text-text-dim hover:text-text-muted font-mono px-1.5 py-px rounded border border-border/60 hover:border-border"
          title="Open command palette"
        >
          <Search size={10} />
          <span>Search</span>
          <span className="kbd ml-1">{modKey}+K</span>
        </button>

        <div className="ml-auto flex items-center gap-px">
          {/* Outbox queue badge — hidden when nothing is queued */}
          <OutboxBadge />
          {/* Connection status */}
          <ConnectionDot status={connection} />

          <button onClick={() => togglePanel("thesis")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "thesis" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Thesis"><BarChart3 size={13} /></button>
          <button onClick={() => togglePanel("brief")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "brief" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Brief"><FileText size={13} /></button>
          <button onClick={() => togglePanel("crossbook")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "crossbook" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Cross-Book"><Scan size={13} /></button>
          <button onClick={() => togglePanel("predictions")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "predictions" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Predictions">P</button>
          <button onClick={() => togglePanel("journal")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "journal" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Journal">J</button>
          <button onClick={() => togglePanel("tradingview")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "tradingview" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="TradingView"><Activity size={13} /></button>
          <div className="w-px h-4 bg-border mx-1" />
          <button
            onClick={() => setShowShortcuts(true)}
            className="p-1 text-text-dim hover:text-text-primary"
            title="Keyboard shortcuts (?)"
            aria-label="Show keyboard shortcuts"
          >
            <Keyboard size={12} />
          </button>
          <span className="text-text-dim text-[10px] font-mono px-1" title="Logged in user">
            {getDisplayName()}
          </span>
          <button onClick={handleLogout} className="p-1 text-text-dim hover:text-danger" title="Logout"><LogOut size={11} /></button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* LEFT sidebar */}
        {sidebarOpen && (
          <aside className={`bg-surface border-r border-border flex flex-col shrink-0 ${isNarrow ? "absolute left-0 top-8 bottom-0 z-30 w-60 shadow-xl" : "w-60"}`}>
            {/* Rooms */}
            <div className="p-1.5 border-b border-border">
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">Rooms</span>
                <button
                  onClick={() => setShowNewRoom(!showNewRoom)}
                  className="text-text-dim hover:text-amber"
                  aria-label="New room"
                >
                  <Plus size={11} />
                </button>
              </div>
              {showNewRoom && (
                <div className="mb-1 space-y-0.5">
                  <input
                    className="input w-full"
                    placeholder="Room name"
                    value={newRoomName}
                    onChange={(e) => setNewRoomName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") createRoom();
                      if (e.key === "Escape") { setShowNewRoom(false); setNewRoomName(""); }
                    }}
                    autoFocus
                  />
                  <select
                    className="input w-full"
                    value={newRoomBook}
                    onChange={(e) => setNewRoomBook(e.target.value)}
                  >
                    <option value="">No linked book</option>
                    {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
                  </select>
                  <button className="btn-primary w-full" onClick={createRoom} disabled={!newRoomName.trim()}>
                    Create
                  </button>
                </div>
              )}
              {rooms.map((room) => (
                <button
                  key={room.id}
                  onClick={() => { setActiveRoom(room); if (isNarrow) setSidebarOpen(false); }}
                  className={`w-full text-left px-1.5 py-0.5 rounded text-xs flex items-center gap-1 ${
                    activeRoom?.id === room.id
                      ? "bg-elevated text-amber"
                      : "text-text-muted hover:text-text-primary hover:bg-elevated/50"
                  }`}
                >
                  <MessageSquare size={11} />
                  <span className="truncate">{room.name}</span>
                </button>
              ))}
              {rooms.length === 0 && !showNewRoom && (
                <button
                  onClick={() => setShowNewRoom(true)}
                  className="w-full text-left text-text-dim hover:text-amber text-[10px] font-mono px-1.5 py-0.5"
                >
                  No rooms yet — create your first +
                </button>
              )}
            </div>

            {/* Watchlist */}
            <div className="flex-1 overflow-y-auto p-1.5">
              <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest block mb-0.5">Watchlist</span>
              <MarketTicker />
            </div>
          </aside>
        )}

        {/* CENTER — chat */}
        <main className="flex-1 flex flex-col min-w-0">
          {activeRoom ? (
            <Chat room={activeRoom} />
          ) : (
            <EmptyChatState
              hasRooms={rooms.length > 0}
              modKey={modKey}
              onCreate={() => { setSidebarOpen(true); setShowNewRoom(true); }}
              onPalette={() => { setCmdPalette(true); setCmdQuery(""); }}
            />
          )}
        </main>

        {/* RIGHT panel + drag gutter */}
        {rightPanel && (
          <>
            {!isNarrow && (
              <div
                onMouseDown={onDragStart}
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize right panel"
                title="Drag to resize"
                className="w-1 cursor-col-resize bg-border hover:bg-amber/40 transition-colors shrink-0"
              />
            )}
            <aside
              className={`bg-surface border-l border-border overflow-y-auto shrink-0 ${
                isNarrow ? "absolute right-0 top-8 bottom-0 z-30 w-72 shadow-xl" : ""
              }`}
              style={!isNarrow ? { width: rightWidth } : undefined}
            >
              <div className="p-2">
                {rightPanel === "thesis" && <ThesisViewer bookId={linkedBookId} books={books} />}
                {rightPanel === "brief" && <MorningBrief />}
                {rightPanel === "crossbook" && <CrossBookPanel />}
                {rightPanel === "predictions" && <PredictionTracker />}
                {rightPanel === "journal" && <TradeJournal />}
                {rightPanel === "tradingview" && <TradingViewPanel bookId={linkedBookId} books={books} />}
              </div>
            </aside>
          </>
        )}
      </div>

      {/* Command palette (Cmd/Ctrl+K) */}
      {cmdPalette && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center pt-24"
          onClick={() => setCmdPalette(false)}
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
        >
          <div className="absolute inset-0 bg-void/60" />
          <div
            className="relative bg-surface border border-border rounded w-full max-w-md shadow-2xl animate-fade-in"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              className="w-full bg-transparent border-b border-border px-3 py-2 text-xs font-mono text-text-primary focus:outline-none placeholder-text-dim"
              placeholder="Search rooms, panels, actions..."
              value={cmdQuery}
              onChange={(e) => setCmdQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCmdIndex((i) => Math.min(i + 1, Math.max(cmdItems.length - 1, 0)));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCmdIndex((i) => Math.max(i - 1, 0));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  const item = cmdItems[cmdIndex];
                  if (item) activateCmd(item);
                }
              }}
              autoFocus
              aria-label="Command palette search"
            />
            <div className="max-h-64 overflow-y-auto py-1" role="listbox">
              {!cmdQuery && recents.length > 0 && (
                <div className="px-3 py-1 text-[9px] uppercase tracking-widest text-text-dim font-mono">
                  Recent
                </div>
              )}
              {cmdItems.map((item, i) => {
                const isRecent = !cmdQuery && i < recents.length;
                const showHeader =
                  !cmdQuery && recents.length > 0 && i === recents.length;
                return (
                  <div key={`${item.label}-${i}`}>
                    {showHeader && (
                      <div className="px-3 py-1 mt-1 text-[9px] uppercase tracking-widest text-text-dim font-mono border-t border-border">
                        All
                      </div>
                    )}
                    <button
                      onClick={() => activateCmd(item)}
                      onMouseEnter={() => setCmdIndex(i)}
                      role="option"
                      aria-selected={cmdIndex === i}
                      className={`w-full text-left px-3 py-1 text-xs flex items-center justify-between ${
                        cmdIndex === i ? "bg-elevated" : "hover:bg-elevated/60"
                      }`}
                    >
                      <span className="font-mono flex items-center gap-1.5">
                        {isRecent && <span className="text-text-dim text-[9px]">•</span>}
                        {item.label}
                      </span>
                      <span className="text-[9px] text-text-dim uppercase">{item.type}</span>
                    </button>
                  </div>
                );
              })}
              {cmdItems.length === 0 && (
                <p className="text-[10px] text-text-dim px-3 py-2 font-mono">No matches</p>
              )}
            </div>
            <div className="border-t border-border px-3 py-1 text-[9px] text-text-dim font-mono flex justify-between">
              <span>
                <span className="kbd">↑↓</span> navigate · <span className="kbd">↵</span> select ·{" "}
                <span className="kbd">Esc</span> close
              </span>
              <span>{cmdItems.length} item{cmdItems.length === 1 ? "" : "s"}</span>
            </div>
          </div>
        </div>
      )}

      {/* Keyboard shortcuts overlay (?) */}
      {showShortcuts && (
        <ShortcutsOverlay onClose={() => setShowShortcuts(false)} modKey={modKey} />
      )}
    </div>
  );
}

// ─── Subcomponents ───────────────────────────────────────────────────────────

function ConnectionDot({ status }: { status: "online" | "reconnecting" | "offline" }) {
  if (status === "online") {
    return (
      <span
        className="inline-flex items-center mr-1"
        title="Connected"
        aria-label="Connected"
      >
        <Wifi size={11} className="text-teal-dim" />
      </span>
    );
  }
  if (status === "reconnecting") {
    return (
      <span
        className="inline-flex items-center gap-1 mr-1 px-1 py-px rounded bg-warning/15 text-warning text-[9px] font-mono uppercase animate-pulse-amber"
        title="Reconnecting to server..."
        aria-live="polite"
      >
        <Wifi size={10} />
        <span className="hidden sm:inline">Reconnecting</span>
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 mr-1 px-1 py-px rounded bg-danger/20 text-danger text-[9px] font-mono uppercase animate-pulse-danger"
      title="Disconnected — backend unreachable"
      role="alert"
    >
      <WifiOff size={10} />
      <span className="hidden sm:inline">Offline</span>
    </span>
  );
}

function EmptyChatState({
  hasRooms,
  modKey,
  onCreate,
  onPalette,
}: {
  hasRooms: boolean;
  modKey: string;
  onCreate: () => void;
  onPalette: () => void;
}) {
  return (
    <div className="flex-1 flex items-center justify-center text-text-dim p-4">
      <div className="text-center max-w-xs">
        <MessageSquare size={28} className="mx-auto mb-2 opacity-20" />
        {hasRooms ? (
          <>
            <p className="text-xs font-mono mb-2 text-text-muted">Select a room to start.</p>
            <p className="text-[10px] font-mono text-text-dim">
              Press <span className="kbd">{modKey}+K</span> for the command palette
              {" · "}
              <span className="kbd">?</span> for shortcuts
            </p>
          </>
        ) : (
          <>
            <p className="text-xs font-mono mb-1 text-text-muted">Welcome to tradingDesk.</p>
            <p className="text-[10px] font-mono text-text-dim mb-3 leading-relaxed">
              Rooms are workspaces for collaborative thesis discussion. Each room links to
              an active thesis book (Iran/Hormuz, Trump tariffs, etc.).
            </p>
            <div className="flex gap-2 justify-center">
              <button onClick={onCreate} className="btn-primary">
                + Create first room
              </button>
              <button onClick={onPalette} className="btn-secondary">
                {modKey}+K
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function ShortcutsOverlay({ onClose, modKey }: { onClose: () => void; modKey: string }) {
  const rows: Array<[string, string]> = [
    [`${modKey}+K`, "Open command palette"],
    [`${modKey}+B`, "Toggle left sidebar"],
    ["?", "Show this shortcut list"],
    ["Esc", "Close palette / overlay / sheet"],
    ["↑ ↓", "Navigate command palette"],
    ["Enter", "Select highlighted command"],
  ];
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div className="absolute inset-0 bg-void/70" />
      <div
        className="relative bg-surface border border-border rounded shadow-2xl w-full max-w-sm animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b border-border">
          <h2 className="font-mono text-xs text-amber font-semibold">Keyboard shortcuts</h2>
          <button
            onClick={onClose}
            className="text-text-dim hover:text-text-primary text-xs"
            aria-label="Close"
          >
            ✕
          </button>
        </div>
        <table className="w-full text-xs">
          <tbody>
            {rows.map(([keys, desc]) => (
              <tr key={keys} className="border-b border-border/40 last:border-0">
                <td className="px-3 py-1.5 w-1/3">
                  {keys.split(" ").map((k, i) => (
                    <span key={i} className="kbd mr-1">{k}</span>
                  ))}
                </td>
                <td className="px-3 py-1.5 text-text-muted font-mono">{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="px-3 py-1.5 border-t border-border text-[9px] text-text-dim font-mono">
          Tip: chat slash-commands (/brief, /thesis, /diff, /predict, /watchlist) work inside any room.
        </div>
      </div>
    </div>
  );
}
