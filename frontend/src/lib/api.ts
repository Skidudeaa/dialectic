// API client: JWT storage, authenticated fetch, WebSocket manager.

import type {
  LoginResponse,
  TVAlertEvent,
  TVBinding,
  TVBindingCreate,
  TVIndicatorReading,
  TVStatus,
  WSMessage,
} from "./types";
import type {
  OutboxReplayRequest,
  OutboxReplayResponse,
  OutboxStatus,
} from "./outbox";

const STORAGE_KEY = "td_auth";

function _loadAuth(): { token: string; username: string; displayName: string } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

const _stored = _loadAuth();
let _token: string | null = _stored?.token ?? null;
let _username: string | null = _stored?.username ?? null;
let _displayName: string | null = _stored?.displayName ?? null;

export function getToken(): string | null { return _token; }
export function getUsername(): string | null { return _username; }
export function getDisplayName(): string | null { return _displayName; }
export function isAuthenticated(): boolean { return _token !== null; }

export function setAuth(resp: LoginResponse): void {
  _token = resp.access_token;
  _username = resp.username;
  _displayName = resp.display_name;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    token: resp.access_token,
    username: resp.username,
    displayName: resp.display_name,
  }));
}

export function clearAuth(): void {
  _token = null;
  _username = null;
  _displayName = null;
  localStorage.removeItem(STORAGE_KEY);
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };
  if (_token) {
    headers["Authorization"] = `Bearer ${_token}`;
  }
  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401) {
    clearAuth();
    window.location.reload();
    throw new Error("Unauthorized");
  }
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status}: ${body}`);
  }
  return resp.json();
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    throw new Error("Invalid credentials");
  }
  const data: LoginResponse = await resp.json();
  setAuth(data);
  return data;
}

// WebSocket manager with auto-reconnect
type WSHandler = (msg: WSMessage) => void;

// WHY (Unit 6): A process-wide tap into every live RoomSocket, so auxiliary
// components (MarketTicker, future live-tape views) can listen to WS frames
// without each opening a second WebSocket. The primary RoomSocket created
// by Chat fans inbound messages through this tap after its own handlers.
const _globalWSTaps = new Set<WSHandler>();

export function subscribeRoomMessages(handler: WSHandler): () => void {
  _globalWSTaps.add(handler);
  return () => _globalWSTaps.delete(handler);
}

function _dispatchToTaps(msg: WSMessage): void {
  for (const h of _globalWSTaps) {
    try { h(msg); } catch { /* a broken tap never kills the socket */ }
  }
}

// WHY (Unit 9): Track the currently-open RoomSocket so aux components
// (PresencePills in the header) can send C2S frames without holding a
// direct ref. There's at most one live socket at a time — Chat creates
// one per active room and closes it on unmount.
let _activeSocket: RoomSocket | null = null;

export function sendPresenceUpdate(bookId: string | null): void {
  _activeSocket?.sendPresenceUpdate(bookId);
}

export class RoomSocket {
  private ws: WebSocket | null = null;
  private handlers: Set<WSHandler> = new Set();
  private roomId: string;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;
  private reconnectAttempt = 0;
  private static MAX_RECONNECT = 10;

  constructor(roomId: string) {
    this.roomId = roomId;
    // Module-level registry (not an alias for scope juggling): the newest
    // socket is the presence/broadcast target for subscribeRoomMessages.
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    _activeSocket = this;
    this.connect();
  }

  private connect(): void {
    if (this.closed || !_token) return;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${window.location.host}/ws/${this.roomId}`);

    this.ws.onopen = () => {
      this.reconnectAttempt = 0;
      this.ws?.send(_token!);
    };

    this.ws.onmessage = (evt) => {
      try {
        const msg: WSMessage = JSON.parse(evt.data);
        this.handlers.forEach((h) => h(msg));
        // Fan out to process-wide taps (see subscribeRoomMessages).
        _dispatchToTaps(msg);
      } catch {
        // Ignore parse errors
      }
    };

    this.ws.onclose = () => {
      if (!this.closed && this.reconnectAttempt < RoomSocket.MAX_RECONNECT) {
        const delay = Math.min(1000 * 2 ** this.reconnectAttempt, 30000);
        const jitter = delay * (0.5 + Math.random() * 0.5);
        this.reconnectAttempt++;
        this.reconnectTimer = setTimeout(() => this.connect(), jitter);
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  subscribe(handler: WSHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  send(content: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "message", content }));
    }
  }

  sendTyping(typing: boolean): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "typing", typing }));
    }
  }

  sendViewing(viewing: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "viewing", viewing }));
    }
  }

  // Unit 9: tell the server which book this client is now viewing.
  // The server broadcasts a presence.changed envelope to every client.
  sendPresenceUpdate(bookId: string | null): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(
        JSON.stringify({
          type: "presence.update",
          payload: { book_id: bookId },
        }),
      );
    }
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (_activeSocket === this) _activeSocket = null;
    this.ws?.close();
  }
}

// ── TradingView API ──────────────────────────────────────────────────────

export async function getTVStatus(): Promise<TVStatus> {
  return apiFetch<TVStatus>("/api/tradingview/status");
}

export async function listTVEvents(bookId?: string, limit = 50): Promise<TVAlertEvent[]> {
  const path = bookId
    ? `/api/tradingview/events/${encodeURIComponent(bookId)}?limit=${limit}`
    : `/api/tradingview/events?limit=${limit}`;
  return apiFetch<TVAlertEvent[]>(path);
}

export async function getTVIndicators(bookId: string): Promise<Record<string, TVIndicatorReading>> {
  return apiFetch<Record<string, TVIndicatorReading>>(
    `/api/tradingview/indicators/${encodeURIComponent(bookId)}`,
  );
}

export async function listTVBindings(bookId: string): Promise<TVBinding[]> {
  return apiFetch<TVBinding[]>(
    `/api/thesis/${encodeURIComponent(bookId)}/tv-bindings`,
  );
}

export async function createTVBinding(
  bookId: string,
  binding: TVBindingCreate,
): Promise<TVBinding> {
  return apiFetch<TVBinding>(
    `/api/thesis/${encodeURIComponent(bookId)}/tv-bindings`,
    {
      method: "POST",
      body: JSON.stringify(binding),
    },
  );
}

export async function deleteTVBinding(
  bookId: string,
  bindingId: string,
): Promise<{ deleted: boolean; bindingId: string }> {
  return apiFetch(
    `/api/thesis/${encodeURIComponent(bookId)}/tv-bindings/${encodeURIComponent(bindingId)}`,
    { method: "DELETE" },
  );
}

// ── Bridge / outbox API ─────────────────────────────────────────────────

export async function fetchOutboxStatus(): Promise<OutboxStatus> {
  return apiFetch<OutboxStatus>("/api/bridge/outbox");
}

export async function replayOutbox(
  body: OutboxReplayRequest = {},
): Promise<OutboxReplayResponse> {
  return apiFetch<OutboxReplayResponse>("/api/bridge/outbox/replay", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
