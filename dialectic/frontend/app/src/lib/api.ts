const BASE = '';  // Same origin via Vite proxy

class DialecticAPI {
  private token: string = '';

  setToken(token: string) { this.token = token; }
  getToken(): string { return this.token; }

  private async fetch<T>(path: string, options?: RequestInit): Promise<T> {
    // SECURITY: Token sent via Authorization header, never in URL query params.
    // URL params are logged by proxies, browsers, and analytics platforms.
    const res = await window.fetch(`${BASE}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(this.token ? { 'Authorization': `Bearer ${this.token}` } : {}),
        ...options?.headers,
      },
    });
    if (!res.ok) {
      if (res.status === 401) {
        // Token expired or invalid — could trigger re-auth flow
        console.warn('API authentication failed');
      }
      throw new Error(`API error: ${res.status}`);
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
  async getRooms(userId: string) { return this.fetch(`/users/me/rooms?user_id=${userId}`); }

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
  async getBriefing(roomId: string, userId: string) { return this.fetch(`/rooms/${roomId}/briefing?user_id=${userId}`); }

  // Replay
  async getState(roomId: string, seq: number) { return this.fetch(`/replay/rooms/${roomId}/state?at_sequence=${seq}`); }
  async getTimeline(roomId: string) { return this.fetch(`/replay/rooms/${roomId}/timeline`); }

  // Stakes
  async getCommitments(roomId: string) { return this.fetch(`/stakes/rooms/${roomId}/commitments`); }
  async getCalibration(roomId: string, userId?: string) { return this.fetch(`/stakes/rooms/${roomId}/calibration${userId ? `?user_id=${userId}` : ''}`); }

  // Auth (no room token needed)
  async signup(email: string, password: string, displayName: string) {
    return window.fetch(`${BASE}/auth/signup`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password, display_name: displayName }) }).then(r => r.json());
  }
  async login(email: string, password: string) {
    return window.fetch(`${BASE}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) }).then(r => r.json());
  }
}

export const api = new DialecticAPI();
