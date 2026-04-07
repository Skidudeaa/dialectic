// API client: JWT storage, authenticated fetch, WebSocket manager.

import type { LoginResponse, WSMessage } from "./types";

let _token: string | null = null;
let _username: string | null = null;
let _displayName: string | null = null;

export function getToken(): string | null { return _token; }
export function getUsername(): string | null { return _username; }
export function getDisplayName(): string | null { return _displayName; }
export function isAuthenticated(): boolean { return _token !== null; }

export function setAuth(resp: LoginResponse): void {
  _token = resp.access_token;
  _username = resp.username;
  _displayName = resp.display_name;
}

export function clearAuth(): void {
  _token = null;
  _username = null;
  _displayName = null;
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

export class RoomSocket {
  private ws: WebSocket | null = null;
  private handlers: Set<WSHandler> = new Set();
  private roomId: string;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(roomId: string) {
    this.roomId = roomId;
    this.connect();
  }

  private connect(): void {
    if (this.closed || !_token) return;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    this.ws = new WebSocket(`${proto}//${window.location.host}/ws/${this.roomId}`);

    this.ws.onopen = () => {
      // Send token as first message for auth
      this.ws?.send(_token!);
    };

    this.ws.onmessage = (evt) => {
      try {
        const msg: WSMessage = JSON.parse(evt.data);
        this.handlers.forEach((h) => h(msg));
      } catch {
        // Ignore parse errors
      }
    };

    this.ws.onclose = () => {
      if (!this.closed) {
        this.reconnectTimer = setTimeout(() => this.connect(), 2000);
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
      this.ws.send(JSON.stringify({ content }));
    }
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}
