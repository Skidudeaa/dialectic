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

import { describe, it, expect, beforeEach, vi } from "vitest";

const STORAGE_KEY = "td_auth";

let store: Record<string, string> = {};

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
    // A client-side copy would be a second source of truth that could drift.
    const api = await bootWithHash("#dialectic_token=dialectic-jwt-abc");

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
