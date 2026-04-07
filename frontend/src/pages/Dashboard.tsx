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
      <header className="h-10 bg-surface border-b border-border flex items-center px-3 shrink-0">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="mr-2 text-text-muted hover:text-text-primary p-1"
          title="Toggle sidebar"
        >
          <ChevronLeft size={16} className={`transition-transform ${sidebarOpen ? "" : "rotate-180"}`} />
        </button>
        <span className="font-mono text-amber font-semibold text-sm">tradingDesk</span>
        <span className="text-text-dim text-xs ml-2 hidden sm:inline">
          {activeRoom ? activeRoom.name : "Select a room"}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button onClick={() => togglePanel("thesis")} className={`p-1.5 rounded ${rightPanel === "thesis" ? "text-amber bg-elevated" : "text-text-muted hover:text-text-primary"}`} title="Thesis"><BarChart3 size={15} /></button>
          <button onClick={() => togglePanel("brief")} className={`p-1.5 rounded ${rightPanel === "brief" ? "text-amber bg-elevated" : "text-text-muted hover:text-text-primary"}`} title="Brief"><FileText size={15} /></button>
          <button onClick={() => togglePanel("crossbook")} className={`p-1.5 rounded ${rightPanel === "crossbook" ? "text-amber bg-elevated" : "text-text-muted hover:text-text-primary"}`} title="Cross-Book"><Scan size={15} /></button>
          <button onClick={() => togglePanel("predictions")} className={`p-1.5 rounded ${rightPanel === "predictions" ? "text-amber bg-elevated" : "text-text-muted hover:text-text-primary"}`} title="Predictions">P</button>
          <button onClick={() => togglePanel("journal")} className={`p-1.5 rounded ${rightPanel === "journal" ? "text-amber bg-elevated" : "text-text-muted hover:text-text-primary"}`} title="Journal">J</button>
          <span className="text-text-dim text-xs ml-2">{getDisplayName()}</span>
          <button onClick={handleLogout} className="p-1.5 text-text-dim hover:text-danger" title="Logout"><LogOut size={14} /></button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* LEFT sidebar */}
        {sidebarOpen && (
          <aside className={`bg-surface border-r border-border flex flex-col shrink-0 ${isNarrow ? "absolute left-0 top-10 bottom-0 z-30 w-60 shadow-xl" : "w-60"}`}>
            {/* Rooms */}
            <div className="p-2 border-b border-border">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-text-dim font-medium uppercase tracking-wider">Rooms</span>
                <button onClick={() => setShowNewRoom(!showNewRoom)} className="text-text-muted hover:text-amber">
                  <Plus size={14} />
                </button>
              </div>
              {showNewRoom && (
                <div className="mb-2 space-y-1">
                  <input
                    className="input w-full text-xs"
                    placeholder="Room name"
                    value={newRoomName}
                    onChange={(e) => setNewRoomName(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && createRoom()}
                    autoFocus
                  />
                  <select
                    className="input w-full text-xs"
                    value={newRoomBook}
                    onChange={(e) => setNewRoomBook(e.target.value)}
                  >
                    <option value="">No linked book</option>
                    {books.map((b) => <option key={b.id} value={b.id}>{b.title}</option>)}
                  </select>
                  <button className="btn-primary text-xs w-full" onClick={createRoom}>Create</button>
                </div>
              )}
              {rooms.map((room) => (
                <button
                  key={room.id}
                  onClick={() => setActiveRoom(room)}
                  className={`w-full text-left px-2 py-1 rounded text-sm flex items-center gap-1.5 ${
                    activeRoom?.id === room.id
                      ? "bg-elevated text-amber"
                      : "text-text-muted hover:text-text-primary hover:bg-elevated/50"
                  }`}
                >
                  <MessageSquare size={13} />
                  <span className="truncate">{room.name}</span>
                </button>
              ))}
              {rooms.length === 0 && !showNewRoom && (
                <p className="text-text-dim text-xs px-2 py-1">No rooms yet</p>
              )}
            </div>

            {/* Watchlist */}
            <div className="flex-1 overflow-y-auto p-2">
              <span className="text-xs text-text-dim font-medium uppercase tracking-wider block mb-1">Watchlist</span>
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
                <MessageSquare size={32} className="mx-auto mb-2 opacity-50" />
                <p className="text-sm">Select or create a room to start</p>
              </div>
            </div>
          )}
        </main>

        {/* RIGHT panel */}
        {rightPanel && (
          <aside className={`bg-surface border-l border-border overflow-y-auto shrink-0 ${isNarrow ? "absolute right-0 top-10 bottom-0 z-30 w-72 shadow-xl" : "w-80"}`}>
            <div className="p-3">
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
