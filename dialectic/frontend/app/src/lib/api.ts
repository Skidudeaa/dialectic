const BASE = '';  // Same origin via Vite proxy

class DialecticAPI {
  private roomToken: string = '';
  private accessToken: string = '';

  // `setToken` remains as a compatibility alias for existing room-entry code.
  setToken(token: string) { this.setRoomToken(token); }
  setRoomToken(token: string) { this.roomToken = token; }
  setAccessToken(token: string) { this.accessToken = token; }
  getAccessToken(): string { return this.accessToken; }
  getToken(): string { return this.roomToken; }

  private async fetch<T>(path: string, options?: RequestInit): Promise<T> {
    // User identity and room access are different credentials. JWT belongs in
    // Authorization; the invite capability uses a dedicated header so neither
    // secret is exposed in URLs.
    const res = await window.fetch(`${BASE}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(this.accessToken ? { 'Authorization': `Bearer ${this.accessToken}` } : {}),
        ...(this.roomToken ? { 'X-Room-Token': this.roomToken } : {}),
        ...options?.headers,
      },
    });
    if (!res.ok) {
      if (res.status === 401) {
        // Token expired or invalid — could trigger re-auth flow
        console.warn('API authentication failed');
      }
      const data = await res.json().catch(() => null) as { detail?: string } | null;
      throw new Error(data?.detail ?? `API error: ${res.status}`);
    }
    return res.json();
  }

  // Core
  async createRoom(name?: string) { return this.fetch('/rooms', { method: 'POST', body: JSON.stringify({ name }) }); }
  async joinRoom(roomId: string, userId: string) { return this.fetch(`/rooms/${roomId}/join`, { method: 'POST', body: JSON.stringify({ user_id: userId }) }); }
  async getThreads(roomId: string) { return this.fetch(`/rooms/${roomId}/threads`); }
  async getMessages(threadId: string, limit = 50) { return this.fetch(`/threads/${threadId}/messages?limit=${limit}`); }
  async getMemories(roomId: string) { return this.fetch(`/rooms/${roomId}/memories`); }
  async getPresence(roomId: string) { return this.fetch(`/rooms/${roomId}/presence`); }
  async getSettings(roomId: string) { return this.fetch(`/rooms/${roomId}/settings`); }
  async getRooms() { return this.fetch('/users/me/rooms'); }
  async updateSettings(roomId: string, settings: object) {
    return this.fetch(`/rooms/${roomId}/settings`, {
      method: 'PATCH',
      body: JSON.stringify(settings),
    });
  }

  // Search
  async searchMessages(roomId: string, q: string, limit = 40) {
    const params = new URLSearchParams({ q, room_id: roomId, limit: String(limit) });
    return this.fetch(`/messages/search?${params.toString()}`);
  }
  /** Messages surrounding a target, for jumping to a search hit in old history. */
  async getMessageContext(threadId: string, messageId: string, context = 25) {
    const params = new URLSearchParams({ message_id: messageId, context: String(context) });
    return this.fetch(`/threads/${threadId}/messages/context?${params.toString()}`);
  }

  // Trading
  async getTradingConfig(roomId: string) {
    const settings = await this.fetch<Record<string, unknown>>(`/rooms/${roomId}/settings`);
    return (settings.trading_config as Record<string, unknown> | null) ?? null;
  }

  // Analytics
  async getThreadDNA(threadId: string) { return this.fetch(`/analytics/threads/${threadId}/dna`); }
  async getRoomDNA(roomId: string) { return this.fetch(`/analytics/rooms/${roomId}/dna`); }
  async getThreadAnalytics(threadId: string) { return this.fetch(`/analytics/threads/${threadId}`); }

  // Graph
  async getContributions(roomId: string) { return this.fetch(`/graph/rooms/${roomId}/contributions`); }

  // Identity
  async getIdentity(roomId: string) { return this.fetch(`/rooms/${roomId}/identity`); }
  async getUserModel(roomId: string, userId: string) { return this.fetch(`/rooms/${roomId}/user-models/${userId}`); }
  async updateIdentity(roomId: string, content: string) {
    return this.fetch(`/rooms/${roomId}/identity`, { method: 'PUT', body: JSON.stringify({ content }) });
  }

  // Briefing
  async getBriefing(roomId: string) { return this.fetch(`/rooms/${roomId}/briefing`); }

  // Replay
  async getState(roomId: string, seq: number) { return this.fetch(`/replay/rooms/${roomId}/state?at_sequence=${seq}`); }
  async getTimeline(roomId: string) { return this.fetch(`/replay/rooms/${roomId}/timeline`); }

  // Stakes
  async getCommitments(roomId: string) { return this.fetch(`/stakes/rooms/${roomId}/commitments`); }
  async getCalibration(roomId: string, userId?: string) { return this.fetch(`/stakes/rooms/${roomId}/calibration${userId ? `?user_id=${userId}` : ''}`); }

  // Auth (no room token needed)
  // WHY: surfaces the backend's `detail` message (e.g. "Invalid email or password")
  // instead of returning the error body as if it were a TokenResponse — a swallowed
  // 401 here cascades into user_id=undefined 422s on every later request.
  private async authFetch<T>(path: string, body: Record<string, unknown>): Promise<T> {
    const res = await window.fetch(`${BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const detail = data && typeof data.detail === 'string' ? data.detail : `API error: ${res.status}`;
      throw new Error(detail);
    }
    return data as T;
  }
  async signup(email: string, password: string, displayName: string) {
    return this.authFetch('/auth/signup', { email, password, display_name: displayName });
  }
  async login(email: string, password: string) {
    return this.authFetch('/auth/login', { email, password });
  }
  async refreshSession(refreshToken: string) {
    return this.authFetch('/auth/refresh', { refresh_token: refreshToken });
  }
  async logoutSession(refreshToken: string) {
    return this.authFetch('/auth/logout', { refresh_token: refreshToken });
  }
}

export const api = new DialecticAPI();
