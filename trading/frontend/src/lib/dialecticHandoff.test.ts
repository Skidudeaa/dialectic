/**
 * Tests for the Dialectic -> tradingDesk session handoff (lib/api.ts).
 *
 * WHY a separate file from api.test.ts: adoption happens at MODULE
 * INITIALIZATION, so every case has to reset the module registry and re-import
 * with a different location.hash. That needs `vi.resetModules()` plus a
 * dynamic import — a shape that does not mix with api.test.ts's single
 * top-level import.
 *
 * WHY it matters: the whole handoff is one line of ordering. If the stored
 * session were read first, clicking through from Dialectic would silently
 * drop you into whatever account the browser last held.
 */

import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";

const STORAGE_KEY = "td_auth";

let store: Record<string, string> = {};

/**
 * Every boot that adopts a token immediately POSTs it to /api/auth/exchange,
 * so every case has to say what that endpoint does. The default is a network
 * FAILURE: the fallback (keep the raw Dialectic token) is what most of these
 * tests are about, and a default that succeeded would quietly rewrite the
 * token they assert on.
 */
let exchangeCalls: Array<{ url: string; init?: RequestInit }> = [];

function stubExchange(
  handler: (url: string, init?: RequestInit) => Promise<Response> | Response,
) {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    exchangeCalls.push({ url, init });
    return handler(url, init);
  });
}

function exchangeBody(token: string, username: string, displayName: string) {
  return new Response(
    JSON.stringify({
      access_token: token,
      token_type: "bearer",
      username,
      display_name: displayName,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

/** A td-native token + identity, exactly as POST /api/auth/exchange returns. */
function exchangeOk(token = "td-native-jwt", username = "amo", displayName = "Amo") {
  stubExchange(() => Promise.resolve(exchangeBody(token, username, displayName)));
}

/**
 * Same, but held open until the returned release() is called — the real shape
 * of the thing: the exchange is a network round trip that lands AFTER the app
 * has mounted and painted, which is the entire reason identity has to be
 * announced rather than read once.
 */
function gatedExchangeOk(): () => void {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  stubExchange(async () => {
    await gate;
    return exchangeBody("td-native-jwt", "amo", "Amo");
  });
  return release;
}

function installLocalStorage() {
  store = {};
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    writable: true,
    value: {
      getItem: (k: string) => store[k] ?? null,
      setItem: (k: string, v: string) => {
        store[k] = v;
      },
      removeItem: (k: string) => {
        delete store[k];
      },
      clear: () => {
        store = {};
      },
      length: 0,
      key: () => null,
    },
  });
}

/** Point the jsdom URL at a given fragment, then load a fresh copy of api.ts. */
async function bootWithHash(hash: string) {
  window.history.replaceState(null, "", `/${hash}`);
  vi.resetModules();
  return await import("./api");
}

beforeEach(() => {
  installLocalStorage();
  window.history.replaceState(null, "", "/");
  exchangeCalls = [];
  stubExchange(() => Promise.reject(new Error("network down")));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Dialectic token handoff", () => {
  it("authenticates from a token in the URL fragment", async () => {
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");

    expect(api.getToken()).toBe("dialectic-jwt-abc");
    expect(api.isAuthenticated()).toBe(true);
  });

  it("persists the bridged token so a refresh keeps the session", async () => {
    await bootWithHash("#dialectic_token=dialectic-jwt-abc");

    expect(JSON.parse(store[STORAGE_KEY]).token).toBe("dialectic-jwt-abc");
  });

  it("strips the token from the address bar", async () => {
    await bootWithHash("#dialectic_token=dialectic-jwt-abc");

    // The credential must not linger in history, screenshots, or a copied URL.
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("dialectic-jwt-abc");
  });

  it("url-decodes a token that was percent-encoded by the sender", async () => {
    // Dialectic encodeURIComponent()s the token; JWTs are base64url so this is
    // usually a no-op, but a token containing '=' padding must survive.
    const api = await bootWithHash(
      `#dialectic_token=${encodeURIComponent("jwt.with=padding==")}`,
    );

    expect(api.getToken()).toBe("jwt.with=padding==");
  });

  it("preserves other fragment params while removing the token", async () => {
    await bootWithHash("#dialectic_token=abc&view=timeline");

    expect(window.location.hash).toBe("#view=timeline");
    expect(window.location.hash).not.toContain("abc");
  });

  it("overrides an existing stored session", async () => {
    // The user just clicked through from Dialectic — that is the session they
    // asked for, even if the browser still holds an older desk login.
    store[STORAGE_KEY] = JSON.stringify({
      token: "stale-desk-token",
      username: "salloum",
      displayName: "Salloum",
    });

    const api = await bootWithHash("#dialectic_token=fresh-dialectic-token");

    expect(api.getToken()).toBe("fresh-dialectic-token");
    expect(JSON.parse(store[STORAGE_KEY]).token).toBe("fresh-dialectic-token");
  });

  it("leaves identity to the server rather than guessing it", async () => {
    // The uuid -> username mapping lives in DIALECTIC_USER_MAP on the server.
    // A client-side copy would be a second source of truth that could drift —
    // so with the exchange unreachable the name stays unknown rather than
    // becoming a guess.
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    expect(api.getUsername()).toBeNull();
    expect(api.getDisplayName()).toBeNull();
  });

  it("captures the originating Dialectic room so the desk opens that case", async () => {
    const api = await bootWithHash(
      "#dialectic_token=jwt-abc&dialectic_room=room-uuid-123",
    );

    expect(api.getBridgedRoomId()).toBe("room-uuid-123");
    expect(api.getToken()).toBe("jwt-abc");
  });

  it("strips the room id from the address bar along with the token", async () => {
    await bootWithHash("#dialectic_token=jwt-abc&dialectic_room=room-uuid-123");

    expect(window.location.hash).toBe("");
  });

  it("has no room id when the link named none", async () => {
    const api = await bootWithHash("#dialectic_token=jwt-abc");

    // Must stay null rather than guessing — the desk then keeps its own
    // default case instead of following a pointer nobody supplied.
    expect(api.getBridgedRoomId()).toBeNull();
  });

  it("has no room id on an ordinary session", async () => {
    store[STORAGE_KEY] = JSON.stringify({
      token: "persisted-token",
      username: "amo",
      displayName: "Amo",
    });

    const api = await bootWithHash("");

    expect(api.getBridgedRoomId()).toBeNull();
  });

  it("still authenticates when history.replaceState throws", async () => {
    const original = window.history.replaceState;
    window.history.replaceState(null, "", "/#dialectic_token=jwt-xyz");
    // Throw only for the strip attempt, after the URL is already set.
    window.history.replaceState = vi.fn(() => {
      throw new Error("replaceState blocked");
    });

    vi.resetModules();
    const api = await import("./api");

    // An untidy address bar must not cost the user their session.
    expect(api.getToken()).toBe("jwt-xyz");
    window.history.replaceState = original;
  });
});

describe("Arrival-time token exchange", () => {
  /**
   * WHY this exists: the token in the fragment is a DIALECTIC access token,
   * and those live 15 minutes. Stored as-is it made every deep-linked session
   * a 15-minute session, ending in a 401 and a bounce to a login form the
   * arriving user has no password for. The desk trades it once, on arrival,
   * for a token it minted itself.
   */

  it("trades the arriving token for the td-native one the server returns", async () => {
    exchangeOk();
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    expect(api.getToken()).toBe("td-native-jwt");
  });

  it("persists the td-native token, so a refresh keeps the LONG session", async () => {
    // The bug in one assertion: what survives a reload has to be the 72h
    // token, not the 15-minute one that arrived in the URL.
    exchangeOk();
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    const persisted = JSON.parse(store[STORAGE_KEY]);
    expect(persisted.token).toBe("td-native-jwt");
    expect(persisted.username).toBe("amo");
    expect(persisted.displayName).toBe("Amo");
  });

  it("presents the Dialectic token as the bearer for the exchange", async () => {
    // The exchange is callable with NOTHING but the bridge token — that is
    // the entire point, since the arriving user holds no desk credential.
    exchangeOk();
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    expect(exchangeCalls).toHaveLength(1);
    expect(exchangeCalls[0].url).toBe("/api/auth/exchange");
    expect(exchangeCalls[0].init?.method).toBe("POST");
    expect(
      (exchangeCalls[0].init?.headers as Record<string, string>).Authorization,
    ).toBe("Bearer dialectic-jwt-abc");
  });

  it("learns the username the server mapped, ending the anonymous 'operator'", async () => {
    exchangeOk("td-native-jwt", "dan", "Dan");
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    expect(api.getUsername()).toBe("dan");
    expect(api.getDisplayName()).toBe("Dan");
  });

  it("tells subscribers that identity arrived", async () => {
    // Identity lands AFTER first paint. Without this the header, presence
    // pills and message authorship keep rendering the null read at mount.
    const release = gatedExchangeOk();
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    const seen: Array<string | null> = [];
    api.subscribeAuth(() => seen.push(api.getUsername()));

    // The window the subscription exists for: mounted, authenticated, nameless.
    expect(api.getUsername()).toBeNull();

    release();
    await api.bridgeExchangeSettled();

    expect(seen).toEqual(["amo"]);
  });

  it("stops notifying once unsubscribed", async () => {
    const release = gatedExchangeOk();
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    const seen: string[] = [];
    const off = api.subscribeAuth(() => seen.push("fired"));
    off();
    release();
    await api.bridgeExchangeSettled();

    expect(seen).toEqual([]);
  });

  it("keeps the raw Dialectic token when the exchange cannot be reached", async () => {
    // Default stub rejects. A dead network must cost the user nothing they
    // had before: the bridge token still authenticates for its 15 minutes.
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    expect(api.getToken()).toBe("dialectic-jwt-abc");
    expect(api.isAuthenticated()).toBe(true);
    expect(JSON.parse(store[STORAGE_KEY]).token).toBe("dialectic-jwt-abc");
  });

  it("keeps the raw Dialectic token when the server refuses the exchange", async () => {
    // 401 = this Dialectic account is not in DIALECTIC_USER_MAP. Discarding
    // the token here would be pointless (it is equally unmapped for every
    // other call) and would hide the real reason behind a blank login form.
    stubExchange(() =>
      Promise.resolve(new Response('{"detail":"not authorized"}', { status: 401 })),
    );
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    expect(api.getToken()).toBe("dialectic-jwt-abc");
    expect(api.getUsername()).toBeNull();
  });

  it("does not lose the room id to the exchange", async () => {
    exchangeOk();
    const api = await bootWithHash(
      "#dialectic_token=dialectic-jwt-abc&dialectic_room=room-uuid-123",
    );
    await api.bridgeExchangeSettled();

    expect(api.getBridgedRoomId()).toBe("room-uuid-123");
    expect(api.getToken()).toBe("td-native-jwt");
  });

  it("still strips the fragment when the exchange succeeds", async () => {
    exchangeOk();
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");
    await api.bridgeExchangeSettled();

    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain("dialectic-jwt-abc");
  });

  it("never exchanges on an ordinary stored session", async () => {
    // A td token needs no exchange and the server answers 400 for one. Firing
    // this on every boot would put a pointless failing request in front of
    // every page load.
    exchangeOk();
    store[STORAGE_KEY] = JSON.stringify({
      token: "persisted-token",
      username: "amo",
      displayName: "Amo",
    });

    const api = await bootWithHash("");
    await api.bridgeExchangeSettled();

    expect(exchangeCalls).toHaveLength(0);
    expect(api.getToken()).toBe("persisted-token");
  });

  it("never exchanges when there is no session at all", async () => {
    exchangeOk();
    const api = await bootWithHash("");
    await api.bridgeExchangeSettled();

    expect(exchangeCalls).toHaveLength(0);
    expect(api.isAuthenticated()).toBe(false);
  });
});

describe("Ordinary sessions are unaffected", () => {
  it("falls back to the stored session when there is no fragment", async () => {
    store[STORAGE_KEY] = JSON.stringify({
      token: "persisted-token",
      username: "amo",
      displayName: "Amo",
    });

    const api = await bootWithHash("");

    expect(api.getToken()).toBe("persisted-token");
    expect(api.getUsername()).toBe("amo");
    expect(api.getDisplayName()).toBe("Amo");
  });

  it("ignores an unrelated fragment and keeps the stored session", async () => {
    store[STORAGE_KEY] = JSON.stringify({
      token: "persisted-token",
      username: "amo",
      displayName: "Amo",
    });

    const api = await bootWithHash("#view=timeline");

    expect(api.getToken()).toBe("persisted-token");
    // A fragment we do not own must be left exactly as it was.
    expect(window.location.hash).toBe("#view=timeline");
  });

  it("is unauthenticated with neither a fragment nor a stored session", async () => {
    const api = await bootWithHash("");

    expect(api.getToken()).toBeNull();
    expect(api.isAuthenticated()).toBe(false);
  });

  it("a normal login still overwrites a bridged session", async () => {
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");

    api.setAuth({
      access_token: "desk-jwt",
      token_type: "bearer",
      username: "dan",
      display_name: "Dan",
    });

    expect(api.getToken()).toBe("desk-jwt");
    expect(api.getUsername()).toBe("dan");
  });
});
