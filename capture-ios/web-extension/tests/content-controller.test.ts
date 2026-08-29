import { webcrypto } from "node:crypto";

import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";

import { installContentController } from "../src/content-controller";

describe("content messaging", () => {
  it("registers one listener and returns the capture envelope", async () => {
    const dom = new JSDOM(`<!doctype html><html><head><title>Message</title></head><body>
      <main>A rendered body with enough meaningful content for the article structural quality floor.</main>
    </body></html>`, { url: "https://fixture.test/message" });
    let listener: ((message: unknown) => unknown) | undefined;
    const runtime = {
      onMessage: {
        addListener: vi.fn((value: (message: unknown) => unknown) => {
          listener = value;
        }),
      },
    };
    installContentController(runtime, dom.window.document, {
      crypto: webcrypto as unknown as Crypto,
      randomUUID: () => "00000000-0000-4000-8000-000000000002",
      now: () => new Date("2026-08-28T12:00:00.000Z"),
      selection: null,
      articleParser: () => ({
        markdown: "# Rendered message\n\nA complete browser message payload with sufficient structural content.",
      }),
    });

    expect(runtime.onMessage.addListener).toHaveBeenCalledOnce();
    const response = await listener?.({ type: "capture_page" });
    expect(response).toMatchObject({
      type: "capture_ready",
      capture: {
        capture_id: "00000000-0000-4000-8000-000000000002",
        capture_mode: "article",
      },
    });
  });
});
