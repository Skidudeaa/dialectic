import type { Attachment, HomeActivityProjection, Memory, Thread, ThreadNode, UserRoom } from '../types/index.ts';
import type { AtlasProjection } from '../types/atlas.ts';
import type {
  FieldProjection,
  FieldReviewRequest,
  FieldReviewResponse,
  ProposalEnvelopeProjection,
  ProposalKind,
  WorkspaceObjectKind,
  WorkspaceObjectProjection,
} from '../types/workspace.ts';

const BASE = '';  // Same origin via Vite proxy

/** Message ids per attachment-list request — see listAttachments. */
const ATTACHMENT_QUERY_BATCH = 100;

interface MemoryPromotionResponse {
  memory_id: string;
  promoted: boolean;
}

interface MemoryPromotionListResponse {
  memory_ids: string[];
}

/**
 * WHY a typed error: callers deciding between "this token is dead, leave the
 * room" and "the network blipped, stay put" need the HTTP status. A network
 * failure throws TypeError from fetch itself and never carries a status.
 */
export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

class DialecticAPI {
  private roomToken: string = '';
  private accessToken: string = '';

  // `setToken` remains as a compatibility alias for existing room-entry code.
  setToken(token: string) { this.setRoomToken(token); }
  setRoomToken(token: string) { this.roomToken = token; }
  setAccessToken(token: string) { this.accessToken = token; }
  getAccessToken(): string { return this.accessToken; }
  getToken(): string { return this.roomToken; }

  /**
   * User identity and room access are different credentials. JWT belongs in
   * Authorization; the invite capability uses a dedicated header so neither
   * secret is exposed in URLs.
   *
   * Split out from `fetch` because multipart uploads and blob reads need the
   * same two credentials WITHOUT the JSON content type — letting the browser
   * write its own multipart boundary, and not lying about what comes back.
   */
  private authHeaders(): Record<string, string> {
    return {
      ...(this.accessToken ? { 'Authorization': `Bearer ${this.accessToken}` } : {}),
      ...(this.roomToken ? { 'X-Room-Token': this.roomToken } : {}),
    };
  }

  private async fetch<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await window.fetch(`${BASE}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...this.authHeaders(),
        ...options?.headers,
      },
    });
    if (!res.ok) {
      if (res.status === 401) {
        // Token expired or invalid — could trigger re-auth flow
        console.warn('API authentication failed');
      }
      const data = await res.json().catch(() => null) as { detail?: string } | null;
      throw new ApiError(data?.detail ?? `API error: ${res.status}`, res.status);
    }
    return res.json();
  }

  // Core
  async createRoom(name?: string) { return this.fetch('/rooms', { method: 'POST', body: JSON.stringify({ name }) }); }
  async joinRoom(roomId: string, userId: string) { return this.fetch(`/rooms/${roomId}/join`, { method: 'POST', body: JSON.stringify({ user_id: userId }) }); }
  async getThreads(roomId: string): Promise<Thread[]> { return this.fetch(`/rooms/${roomId}/threads`); }
  async getGenealogy(roomId: string): Promise<ThreadNode[]> {
    return this.fetch(`/rooms/${roomId}/genealogy`);
  }

  // Home — the activity call authorizes from JWT plus Home membership
  // (the server ignores any room token); member administration carries
  // the current Home room token through the normal header path.
  async getHomeActivity(): Promise<HomeActivityProjection> {
    return this.fetch('/users/me/home/activity');
  }
  async resolveHomeMember(email: string): Promise<{
    user_id: string;
    display_name: string;
  }> {
    return this.fetch('/users/me/home/member-candidate', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }
  async addHomeMember(
    email: string,
    confirmedUserId: string,
  ): Promise<{
    user_id: string;
    display_name: string;
    status: 'added' | 'already_member';
  }> {
    return this.fetch('/users/me/home/members', {
      method: 'POST',
      body: JSON.stringify({
        email,
        confirmed_user_id: confirmedUserId,
      }),
    });
  }
  /**
   * The room's workspace objects — one shape over readings, briefs, the
   * thesis, commitments, proposals, dossier entries and the Record.
   *
   * Read-only by contract: the server projects rows that already exist and
   * writes nothing, so a surface that wants to ACT on an object calls that
   * entity's own endpoint (accept a proposal, retire a thesis) rather than
   * posting back here.
   */
  async getWorkspaceObjects(
    roomId: string,
    kind?: WorkspaceObjectKind,
  ): Promise<WorkspaceObjectProjection> {
    const query = kind ? `?kind=${encodeURIComponent(kind)}` : '';
    return this.fetch(`/rooms/${roomId}/workspace/objects${query}`);
  }
  /**
   * The room's proposals, normalized (design v2 §8.3–8.4).
   *
   * The projection knows what a message alone cannot: whether the target is
   * already gone — a book bound, an article filed by the wire, a deadline
   * past. Accepting still goes to the relay that owns the write.
   */
  async getRoomProposals(
    roomId: string,
    kind?: ProposalKind,
  ): Promise<ProposalEnvelopeProjection> {
    const query = kind ? `?kind=${encodeURIComponent(kind)}` : '';
    return this.fetch(`/rooms/${roomId}/workspace/proposals${query}`);
  }
  /**
   * The room's Field -- every mark with derived review and inline review
   * history (design v2 §14, dialectic/field_marks.py). Read-only, same
   * contract as getWorkspaceObjects: a surface that wants to ACT calls
   * postFieldReview, never a second write path.
   */
  async getFieldMarks(roomId: string): Promise<FieldProjection> {
    return this.fetch(`/rooms/${roomId}/field`);
  }
  /**
   * One human action on one mark -- confirm/contest/correct/split/merge/
   * supersede. All writes land in one transaction on the server; on any
   * failure nothing lands (api/field.py). The caller re-fetches (or the
   * hook's refresh()) rather than optimistically patching the projection,
   * because a correct/split/merge changes more than the one row it targets.
   */
  async postFieldReview(
    roomId: string,
    markId: string,
    request: FieldReviewRequest,
  ): Promise<FieldReviewResponse> {
    return this.fetch(`/rooms/${roomId}/field/marks/${markId}/review`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }
  /**
   * The caller's own cross-room Atlas — rooms, branches, theses, readings,
   * briefs, commitments and unresolved work, plus the real-provenance edges
   * between them (atlas_objects.py). JWT only, no room token: cross-room by
   * construction, same auth shape as getHomeActivity().
   */
  async getAtlas(): Promise<AtlasProjection> {
    return this.fetch('/users/me/atlas');
  }
  /**
   * The composer's "Make a move" affordance (§1.11, §5.3): a human-authored
   * proposal, written as an ordinary message whose metadata carries ONE
   * proposal block. Server-side validation (proposal_intake.py) re-shapes
   * every field before it reaches storage — this is a document, not a
   * write of record.
   */
  async proposeMove(
    threadId: string,
    content: string,
    metadata: Record<string, unknown>,
  ): Promise<{ id: string; metadata?: Record<string, unknown> | null }> {
    return this.fetch(`/threads/${threadId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content, message_type: 'text', metadata }),
    });
  }
  async getMessages(threadId: string, limit = 50) { return this.fetch(`/threads/${threadId}/messages?limit=${limit}`); }
  async getMemories(roomId: string): Promise<Memory[]> {
    const [memories, promotions] = await Promise.all([
      this.fetch<Omit<Memory, 'personally_promoted'>[]>(`/rooms/${roomId}/memories`),
      this.fetch<MemoryPromotionListResponse>(`/rooms/${roomId}/memory-promotions`),
    ]);
    const promotedIds = new Set(promotions.memory_ids);
    return memories.map((memory) => ({
      ...memory,
      personally_promoted: promotedIds.has(memory.id),
    }));
  }
  async promoteMemory(memoryId: string): Promise<MemoryPromotionResponse> {
    return this.fetch(`/memories/${memoryId}/promotion`, { method: 'PUT' });
  }
  async demoteMemory(memoryId: string): Promise<MemoryPromotionResponse> {
    return this.fetch(`/memories/${memoryId}/promotion`, { method: 'DELETE' });
  }
  async getPresence(roomId: string) { return this.fetch(`/rooms/${roomId}/presence`); }
  async getSettings(roomId: string) { return this.fetch(`/rooms/${roomId}/settings`); }
  async getRooms(): Promise<UserRoom[]> { return this.fetch('/users/me/rooms'); }
  async updateSettings(roomId: string, settings: object) {
    return this.fetch(`/rooms/${roomId}/settings`, {
      method: 'PATCH',
      body: JSON.stringify(settings),
    });
  }

  async getThreadReactions(threadId: string) { return this.fetch(`/threads/${threadId}/reactions`); }

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
  // The trading relay (api/trading_relay.py): room-scoped reads over the
  // desk. An unbound room answers 409 — callers treat that as "no cockpit",
  // never as an error.
  async getThesisStructure(roomId: string) { return this.fetch<import('../types/trading').ThesisStructure>(`/rooms/${roomId}/trading/structure`); }
  async getTradingQuotes(roomId: string) { return this.fetch<import('../types/trading').Quote[]>(`/rooms/${roomId}/trading/quotes`); }
  async getPolymarketOdds(roomId: string) { return this.fetch<import('../types/trading').PolymarketOdd[]>(`/rooms/${roomId}/trading/polymarket`); }
  async getTradingDiff(roomId: string) { return this.fetch<import('../types/trading').ThesisDiff>(`/rooms/${roomId}/trading/diff`); }
  async getOpenTrades(roomId: string) { return this.fetch<import('../types/trading').OpenTrades>(`/rooms/${roomId}/trading/trades`); }
  async getMorningBrief(roomId: string) { return this.fetch<import('../types/trading').MorningBrief>(`/rooms/${roomId}/trading/brief`); }
  async getThesisNews(roomId: string) { return this.fetch<import('../types/trading').ThesisNews>(`/rooms/${roomId}/trading/news`); }
  async evaluateScenario(roomId: string, scenarioId: string) {
    return this.fetch<import('../types/trading').ScenarioEvaluation>(`/rooms/${roomId}/trading/scenarios/${encodeURIComponent(scenarioId)}/evaluate`, { method: 'POST' });
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

  // Attachments
  //
  // WHY XHR and not fetch: upload progress. `fetch` can only report progress on
  // a request body by wrapping it in a ReadableStream, which needs duplex:'half'
  // and is not supported by Safari — the browser most of this room's media comes
  // from. XHR's upload.onprogress is the boring option that works everywhere.
  uploadAttachment(
    roomId: string,
    file: File,
    options?: { onProgress?: (percent: number) => void; signal?: AbortSignal },
  ): Promise<Attachment> {
    return new Promise<Attachment>((resolve, reject) => {
      const form = new FormData();
      form.append('file', file);

      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE}/rooms/${roomId}/attachments`);
      // Deliberately no Content-Type: the browser writes multipart/form-data
      // with its own boundary, and overriding it makes the body unparseable.
      for (const [name, value] of Object.entries(this.authHeaders())) {
        xhr.setRequestHeader(name, value);
      }

      const onAbort = () => xhr.abort();
      options?.signal?.addEventListener('abort', onAbort);
      const cleanup = () => options?.signal?.removeEventListener('abort', onAbort);

      xhr.upload.onprogress = (event) => {
        if (!event.lengthComputable) return;
        options?.onProgress?.(Math.round((event.loaded / event.total) * 100));
      };
      xhr.onload = () => {
        cleanup();
        let parsed: unknown = null;
        try {
          parsed = JSON.parse(xhr.responseText) as unknown;
        } catch {
          parsed = null;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(parsed as Attachment);
          return;
        }
        const detail = (parsed as { detail?: string } | null)?.detail;
        reject(new ApiError(detail ?? `Upload failed: ${xhr.status}`, xhr.status));
      };
      // status 0 is the shape of both a network failure and an abort; the
      // caller distinguishes them by whether it was the one who aborted.
      xhr.onerror = () => { cleanup(); reject(new ApiError('Upload failed — check your connection', 0)); };
      xhr.onabort = () => { cleanup(); reject(new ApiError('Upload cancelled', 0)); };
      xhr.send(form);
    });
  }

  /**
   * Attachments bound to a set of messages, as one flat list.
   *
   * The endpoint caps message_ids at 200 per call, but the binding constraint
   * is the URL, not the cap: 200 UUIDs is ~7.4KB of query string, which is
   * close enough to nginx's 8KB request-line limit to risk a 414 that would
   * look like a server fault. 100 per request is comfortably under both.
   */
  async listAttachments(roomId: string, messageIds: string[]): Promise<Attachment[]> {
    if (messageIds.length === 0) return [];
    const batches: string[][] = [];
    for (let i = 0; i < messageIds.length; i += ATTACHMENT_QUERY_BATCH) {
      batches.push(messageIds.slice(i, i + ATTACHMENT_QUERY_BATCH));
    }
    const pages = await Promise.all(batches.map((batch) => {
      const params = new URLSearchParams({ message_ids: batch.join(',') });
      return this.fetch<Attachment[]>(`/rooms/${roomId}/attachments?${params.toString()}`);
    }));
    return pages.flat();
  }

  /**
   * The bytes. GET /attachments/{id} authenticates like every other room read,
   * so this cannot be an <img src> — the caller renders from an object URL.
   */
  async fetchAttachmentBlob(attachmentId: string): Promise<Blob> {
    const res = await window.fetch(`${BASE}/attachments/${attachmentId}`, {
      headers: this.authHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null) as { detail?: string } | null;
      throw new ApiError(data?.detail ?? `Attachment error: ${res.status}`, res.status);
    }
    // A 200 carrying HTML means the request never reached the API: a proxy that
    // does not route /attachments falls through to the SPA and answers with
    // index.html. Without this check that document becomes the object URL, and
    // every image renders broken with nothing logged anywhere. (The Vite dev
    // proxy has exactly this gap today; nginx does not.)
    const contentType = res.headers.get('content-type') ?? '';
    if (contentType.startsWith('text/html')) {
      throw new ApiError(
        'Attachment route is not proxied — /attachments reached the app shell, not the API',
        502,
      );
    }
    return res.blob();
  }

  /**
   * The human tap that logs Claude's drafted prediction to tradingDesk.
   * Room-authed like every other room write; the server flips the proposal's
   * accepted flag, so a second tap answers 409 instead of double-logging.
   */
  async acceptPrediction(roomId: string, messageId: string): Promise<Record<string, unknown>> {
    return this.fetch(`/rooms/${roomId}/predictions/accept`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId }),
    });
  }

  /**
   * The human tap that settles a logged prediction: relays the verdict to
   * tradingDesk's resolve endpoint and the server flips the proposal's
   * accepted flag, so a second tap answers 409 instead of double-resolving.
   */
  async acceptResolution(
    roomId: string,
    predictionId: string,
    verdict: 'correct' | 'incorrect',
  ): Promise<Record<string, unknown>> {
    return this.fetch(`/rooms/${roomId}/predictions/${predictionId}/resolve-accept`, {
      method: 'POST',
      body: JSON.stringify({ verdict }),
    });
  }

  async acceptReading(roomId: string, messageId: string): Promise<Record<string, unknown>> {
    return this.fetch(`/rooms/${roomId}/reading/accept`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId }),
    });
  }

  /**
   * Create Thesis — mints a book on tradingDesk born bound to this room.
   * The DAG itself gets drawn later in the desk's Builder; this call only
   * establishes the binding, so the room starts receiving snapshots.
   */
  async createThesis(
    roomId: string,
    body: {
      title: string; claim?: string; monthly_budget?: number;
      nodes?: unknown[]; edges?: unknown[];
    },
  ): Promise<{ book_id: string; title: string }> {
    return this.fetch(`/rooms/${roomId}/trading/thesis`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  /**
   * Claude drafts the causal DAG — a proposal, nothing is written anywhere.
   * The human reviews it in the panel; Accept sends it through createThesis.
   */
  async draftThesis(
    roomId: string,
    body: { title: string; claim?: string; monthly_budget?: number },
  ): Promise<{ nodes: unknown[]; edges: unknown[]; rationale: string }> {
    return this.fetch(`/rooms/${roomId}/trading/thesis/draft`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  /**
   * Retire the room's thesis. The book survives on the desk as history —
   * only the binding and the push path die, and the room can birth a
   * successor.
   */
  async retireThesis(roomId: string): Promise<{ retired_book_id: string }> {
    return this.fetch(`/rooms/${roomId}/trading/thesis`, { method: 'DELETE' });
  }

  /**
   * Which doors this deployment has open — answered without a credential,
   * because the signed-out screen renders before one exists.
   *
   * WHY the screen asks instead of assuming: hardcoding "invite only" into the
   * UI is how the help modal ended up advertising five theses that may not be
   * five any more. The server owns the gate; the screen reports it.
   */
  async getCapabilities(): Promise<{ signups_enabled: boolean; guest_access_enabled: boolean }> {
    return this.fetch('/auth/capabilities');
  }

  /**
   * What THIS room can do, and what is actually running for it.
   *
   * The job list comes from the running scheduler, not a second roster — so
   * the map cannot describe a daily rhythm that is switched off, which is what
   * the hardcoded help modal did.
   */
  async getRoomCapabilities(roomId: string): Promise<{
    thesis_bound: boolean;
    auto_interjection: boolean;
    interjection_turn_threshold: number;
    scheduler_running: boolean;
    jobs: { name: string; enabled: boolean; interval_s: number; daily_at: string | null }[];
  }> {
    return this.fetch(`/rooms/${roomId}/capabilities`);
  }

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

  // Web Push
  async getVapidPublicKey() { return this.fetch('/notifications/vapid-public-key'); }
  async registerWebPushSubscription(subscription: { endpoint: string; keys: { p256dh?: string; auth?: string }; user_agent?: string }) {
    return this.fetch('/notifications/web-subscriptions', { method: 'POST', body: JSON.stringify(subscription) });
  }
  async unregisterWebPushSubscription(endpoint: string) {
    return this.fetch('/notifications/web-subscriptions', { method: 'DELETE', body: JSON.stringify({ endpoint }) });
  }
}

export const api = new DialecticAPI();
