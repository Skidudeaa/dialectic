import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
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
  HelpCircle,
  Target,
  NotebookPen,
  AlertOctagon,
  Layers,
  Bot,
} from "lucide-react";
import { useOnboarding } from "../components/onboarding/useOnboarding";
import { apiFetch, getDisplayName, getUsername, clearAuth, sendPresenceUpdate, subscribeAuth, RoomSocket } from "../lib/api";
import type { Room, ThesisBook, ThesisState } from "../lib/types";
import ThesisViewer from "../components/ThesisViewer";
import MarketTicker from "../components/MarketTicker";
import MorningBrief from "../components/MorningBrief";
import PredictionTracker from "../components/PredictionTracker";
import TradeJournal from "../components/TradeJournal";
import CrossBookPanel from "../components/CrossBookPanel";
import CrossBookMatrix from "../components/CrossBookMatrix";
import BookTabBar from "../components/BookTabBar";
import TradingViewPanel from "../components/TradingViewPanel";
import TradeLifecyclePanel from "../components/TradeLifecyclePanel";
import AgentInRoomPanel from "../components/AgentInRoomPanel";
import OutboxBadge from "../components/OutboxBadge";
import PresencePills from "../components/PresencePills";
import CommandPalette from "../components/CommandPalette";
import { useToast } from "../components/toast";

interface Props {
  onLogout: () => void;
}

type RightPanel =
  | "predictions"
  | "journal"
  | "crossbook"
  | "matrix"
  | "brief"
  | "tradingview"
  | "trades"
  | "agent"
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
  const { startTour } = useOnboarding();

  // WHY: a session arriving from Dialectic's deep link holds a token but no
  // name — the uuid -> username map is server-side, and the exchange that
  // resolves it answers a round trip after this component mounts. Without
  // this nudge the header would sit blank and presence/authorship would keep
  // using the null read at mount for the rest of the session.
  const [, setIdentityTick] = useState(0);
  useEffect(() => subscribeAuth(() => setIdentityTick((n) => n + 1)), []);

  const [rooms, setRooms] = useState<Room[]>([]);
  const [books, setBooks] = useState<ThesisBook[]>([]);
  const [activeBookOverride, setActiveBookOverride] = useState<string | null>(() => {
    try {
      return localStorage.getItem(ACTIVE_BOOK_KEY);
    } catch {
      return null;
    }
  });
  const [rightPanel, setRightPanel] = useState<RightPanel>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
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

  // Per-book thesis snapshots, keyed by book.id. Populated lazily once
  // `books` resolves so the tab-bar dots and the cross-book matrix can
  // share one warm cache. Refreshed every 5min — same cadence as the
  // ThesisViewer poll. Populated in parallel; failures are silently
  // dropped so a single broken book doesn't blank the whole UI.
  const [bookStates, setBookStates] = useState<
    Record<string, ThesisState | null>
  >({});

  const loadAllBookStates = useCallback(async (ids: string[]) => {
    const next: Record<string, ThesisState | null> = {};
    await Promise.all(
      ids.map(async (id) => {
        try {
          next[id] = await apiFetch<ThesisState>(
            `/api/thesis/${encodeURIComponent(id)}/state`,
          );
        } catch {
          next[id] = null;
        }
      }),
    );
    setBookStates((prev) => ({ ...prev, ...next }));
  }, []);

  useEffect(() => {
    loadRooms();
    loadBooks();
  }, [loadRooms, loadBooks]);

  useEffect(() => {
    if (books.length === 0) return;
    const ids = books.map((b) => b.id);
    loadAllBookStates(ids);
    const interval = setInterval(() => loadAllBookStates(ids), 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [books, loadAllBookStates]);

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

  // Resolve which book the right panels + center thesis view render against.
  // Priority: explicit operator override → first book.
  const linkedBookId = useMemo(() => {
    if (activeBookOverride && books.some((b) => b.id === activeBookOverride)) {
      return activeBookOverride;
    }
    return books[0]?.id || null;
  }, [activeBookOverride, books]);

  // Room used purely to key the live WebSocket (price ticks, presence,
  // agent state) now that there's no rooms UI to pick one explicitly —
  // prefer the room linked to the active book, falling back to the first
  // room so live updates still flow even when no room names its book.
  const activeRoom = useMemo(() => {
    if (rooms.length === 0) return null;
    return rooms.find((r) => r.linked_book_id === linkedBookId) || rooms[0];
  }, [rooms, linkedBookId]);

  // Sole owner of the room WebSocket now that Chat is gone. Every other
  // live-data component (MarketTicker, PresencePills, AgentInRoomPanel)
  // taps into it via subscribeRoomMessages() / the module-level active
  // socket in lib/api.ts rather than opening a second connection.
  useEffect(() => {
    if (!activeRoom) return;
    const sock = new RoomSocket(activeRoom.id);
    return () => sock.close();
  }, [activeRoom?.id]);

  // Unit 9: tell the server which book we're viewing so other clients can
  // render our presence pill with the right ring color. Also retry shortly
  // after mount because the active RoomSocket may not be open yet when
  // linkedBookId first resolves.
  useEffect(() => {
    sendPresenceUpdate(linkedBookId);
    const t = setTimeout(() => sendPresenceUpdate(linkedBookId), 750);
    return () => clearTimeout(t);
  }, [linkedBookId, activeRoom?.id]);

  // Command palette items — recents bubble to top.
  type CmdItem = { label: string; type: "panel" | "action"; action: () => void };
  const allCmdItems: CmdItem[] = useMemo(
    () => [
      { label: "Morning brief", type: "panel", action: () => { togglePanel("brief"); setCmdPalette(false); } },
      { label: "Cross-book scan", type: "panel", action: () => { togglePanel("crossbook"); setCmdPalette(false); } },
      { label: "Cross-book matrix", type: "panel", action: () => { togglePanel("matrix"); setCmdPalette(false); } },
      { label: "Predictions", type: "panel", action: () => { togglePanel("predictions"); setCmdPalette(false); } },
      { label: "Trade journal", type: "panel", action: () => { togglePanel("journal"); setCmdPalette(false); } },
      { label: "TradingView", type: "panel", action: () => { togglePanel("tradingview"); setCmdPalette(false); } },
      { label: "Trade lifecycle", type: "panel", action: () => { togglePanel("trades"); setCmdPalette(false); } },
      { label: "Agent in room", type: "panel", action: () => { togglePanel("agent"); setCmdPalette(false); } },
      { label: "Show keyboard shortcuts", type: "action", action: () => { setShowShortcuts(true); setCmdPalette(false); } },
      { label: "Logout", type: "action", action: () => { handleLogout(); setCmdPalette(false); } },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
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
      // Cmd/Ctrl+1..9 — switch active book by tab order. Only handle when
      // exactly the digit is pressed (skip Shift to avoid clobbering
      // browser-native shortcuts like Cmd+Shift+1).
      if (
        (e.metaKey || e.ctrlKey) &&
        !e.shiftKey &&
        !e.altKey &&
        /^[1-9]$/.test(e.key)
      ) {
        const idx = parseInt(e.key, 10) - 1;
        if (idx >= 0 && idx < books.length) {
          e.preventDefault();
          setActiveBookExplicit(books[idx].id);
        }
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
  }, [cmdPalette, showShortcuts, rightPanel, sidebarOpen, isNarrow, isVeryNarrow, books]);

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
          {/* Unit 9: presence pills — who's connected, what book they view,
              agent pulse when LLM is mid tool-call. */}
          <PresencePills myUserId={getUsername()} myBookId={linkedBookId} />
          {/* Connection status */}
          <ConnectionDot status={connection} />

          <button onClick={() => togglePanel("brief")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "brief" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Brief"><FileText size={13} /></button>
          <button onClick={() => togglePanel("crossbook")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "crossbook" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Cross-Book"><Scan size={13} /></button>
          <button onClick={() => togglePanel("matrix")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "matrix" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Cross-book matrix" aria-label="Cross-book matrix"><Layers size={13} /></button>
          <button onClick={() => togglePanel("predictions")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "predictions" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Predictions" aria-label="Predictions panel"><Target size={13} /></button>
          <button onClick={() => togglePanel("journal")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "journal" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Journal" aria-label="Trade journal panel"><NotebookPen size={13} /></button>
          <button onClick={() => togglePanel("tradingview")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "tradingview" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="TradingView"><Activity size={13} /></button>
          <button onClick={() => togglePanel("trades")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "trades" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Trade lifecycle" aria-label="Trade lifecycle panel"><AlertOctagon size={13} /></button>
          <button onClick={() => togglePanel("agent")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "agent" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Agent in room" aria-label="Agent in room panel"><Bot size={13} /></button>
          <div className="w-px h-4 bg-border mx-1" />
          <button
            onClick={() => startTour()}
            className="p-1 text-text-dim hover:text-text-primary"
            title="Replay product tour"
            aria-label="Replay product tour"
          >
            <HelpCircle size={12} />
          </button>
          <button
            onClick={() => navigate("/welcome")}
            className="p-1 text-text-dim hover:text-text-primary"
            title="Open the full guide"
            aria-label="Open the welcome guide"
          >
            <Book size={12} />
          </button>
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

      {/* Book tab bar — one tab per book, state dot reflects worst node
          state, click-to-activate, Cmd/Ctrl+1..N keybinds. */}
      {books.length > 0 && (
        <BookTabBar
          books={books}
          activeBookId={linkedBookId}
          bookStates={bookStates}
          onSelect={(id) => setActiveBookExplicit(id)}
        />
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* LEFT sidebar */}
        {sidebarOpen && (
          <aside className={`bg-surface border-r border-border flex flex-col shrink-0 ${isNarrow ? "absolute left-0 top-8 bottom-0 z-30 w-60 shadow-xl" : "w-60"}`}>
            {/* Watchlist */}
            <div className="flex-1 overflow-y-auto p-1.5">
              <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest block mb-0.5">Watchlist</span>
              <MarketTicker roomId={activeRoom?.id} thesisId={linkedBookId} />
            </div>
          </aside>
        )}

        {/* CENTER — thesis viewer (the desk's primary surface now that
            rooms/chat are gone; BookTabBar above drives which book it
            shows) */}
        <main className="flex-1 flex flex-col min-w-0 overflow-y-auto">
          <div className="p-2">
            <ThesisViewer bookId={linkedBookId} books={books} />
          </div>
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
                {rightPanel === "brief" && <MorningBrief />}
                {rightPanel === "crossbook" && <CrossBookPanel />}
                {rightPanel === "matrix" && (
                  <CrossBookMatrix
                    books={books}
                    bookStates={bookStates}
                    activeBookId={linkedBookId}
                    onSelect={(id) => setActiveBookExplicit(id)}
                  />
                )}
                {rightPanel === "predictions" && <PredictionTracker />}
                {rightPanel === "journal" && <TradeJournal />}
                {rightPanel === "tradingview" && <TradingViewPanel bookId={linkedBookId} books={books} />}
                {rightPanel === "trades" && <TradeLifecyclePanel />}
                {rightPanel === "agent" && <AgentInRoomPanel bookId={linkedBookId} books={books} roomId={activeRoom?.id ?? null} />}
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

      {/* Backend command palette — Ctrl/Cmd+Shift+K, introspects /api/v1/commands */}
      <CommandPalette defaultBookId={linkedBookId} />
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

function ShortcutsOverlay({ onClose, modKey }: { onClose: () => void; modKey: string }) {
  const rows: Array<[string, string]> = [
    [`${modKey}+K`, "Open command palette"],
    [`${modKey}+B`, "Toggle left sidebar"],
    [`${modKey}+1..9`, "Switch active book"],
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
          Tip: {modKey}+K opens the command palette from anywhere.
        </div>
      </div>
    </div>
  );
}
