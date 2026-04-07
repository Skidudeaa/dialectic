import { useState, useEffect, useCallback } from "react";
import {
  MessageSquare,
  BarChart3,
  FileText,
  Scan,
  LogOut,
  Plus,
  ChevronLeft,
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

interface Props {
  onLogout: () => void;
}

type RightPanel = "thesis" | "predictions" | "journal" | "crossbook" | "brief" | null;

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

export default function Dashboard({ onLogout }: Props) {
  const isNarrow = useMediaQuery("(max-width: 1024px)");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [books, setBooks] = useState<ThesisBook[]>([]);
  const [activeRoom, setActiveRoom] = useState<Room | null>(null);
  const [rightPanel, setRightPanel] = useState<RightPanel>("thesis");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [showNewRoom, setShowNewRoom] = useState(false);
  const [newRoomName, setNewRoomName] = useState("");
  const [newRoomBook, setNewRoomBook] = useState("");

  const loadRooms = useCallback(async () => {
    try {
      const data = await apiFetch<Room[]>("/api/rooms");
      setRooms(data);
    } catch { /* ignore */ }
  }, []);

  const loadBooks = useCallback(async () => {
    try {
      const data = await apiFetch<ThesisBook[]>("/api/thesis/books");
      setBooks(data);
    } catch { /* ignore */ }
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
    } catch { /* ignore */ }
  }

  function handleLogout() {
    clearAuth();
    onLogout();
  }

  // Auto-collapse panels on narrow screens
  useEffect(() => {
    if (isNarrow) {
      setSidebarOpen(false);
    }
  }, [isNarrow]);

  function togglePanel(p: RightPanel) {
    setRightPanel((prev) => (prev === p ? null : p));
  }

  const linkedBookId = activeRoom?.linked_book_id || books[0]?.id || null;

  return (
    <div className="h-screen flex flex-col bg-void overflow-hidden">
      {/* Top bar */}
      <header className="h-8 bg-surface border-b border-border flex items-center px-2 shrink-0">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="mr-1.5 text-text-dim hover:text-text-primary p-0.5"
          title="Toggle sidebar"
        >
          <ChevronLeft size={13} className={`transition-transform ${sidebarOpen ? "" : "rotate-180"}`} />
        </button>
        <span className="font-mono text-amber font-semibold text-xs">tradingDesk</span>
        <span className="text-text-dim text-[10px] ml-2 font-mono hidden sm:inline">
          {activeRoom ? activeRoom.name : ""}
        </span>
        <div className="ml-auto flex items-center gap-px">
          <button onClick={() => togglePanel("thesis")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "thesis" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Thesis"><BarChart3 size={13} /></button>
          <button onClick={() => togglePanel("brief")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "brief" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Brief"><FileText size={13} /></button>
          <button onClick={() => togglePanel("crossbook")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "crossbook" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Cross-Book"><Scan size={13} /></button>
          <button onClick={() => togglePanel("predictions")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "predictions" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Predictions">P</button>
          <button onClick={() => togglePanel("journal")} className={`p-1 rounded text-[10px] font-mono ${rightPanel === "journal" ? "text-amber bg-elevated" : "text-text-dim hover:text-text-primary"}`} title="Journal">J</button>
          <div className="w-px h-4 bg-border mx-1" />
          <span className="text-text-dim text-[10px] font-mono">{getDisplayName()}</span>
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
                <button onClick={() => setShowNewRoom(!showNewRoom)} className="text-text-dim hover:text-amber">
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
                    onKeyDown={(e) => e.key === "Enter" && createRoom()}
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
                  <button className="btn-primary w-full" onClick={createRoom}>Create</button>
                </div>
              )}
              {rooms.map((room) => (
                <button
                  key={room.id}
                  onClick={() => setActiveRoom(room)}
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
                <p className="text-text-dim text-[10px] font-mono px-1.5 py-0.5">No rooms yet. Click + to create.</p>
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
            <Chat room={activeRoom} books={books} />
          ) : (
            <div className="flex-1 flex items-center justify-center text-text-dim">
              <div className="text-center">
                <MessageSquare size={24} className="mx-auto mb-1 opacity-30" />
                <p className="text-xs font-mono">Select or create a room</p>
              </div>
            </div>
          )}
        </main>

        {/* RIGHT panel */}
        {rightPanel && (
          <aside className={`bg-surface border-l border-border overflow-y-auto shrink-0 ${isNarrow ? "absolute right-0 top-8 bottom-0 z-30 w-72 shadow-xl" : "w-80"}`}>
            <div className="p-2">
              {rightPanel === "thesis" && <ThesisViewer bookId={linkedBookId} books={books} />}
              {rightPanel === "brief" && <MorningBrief />}
              {rightPanel === "crossbook" && <CrossBookPanel />}
              {rightPanel === "predictions" && <PredictionTracker />}
              {rightPanel === "journal" && <TradeJournal />}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
