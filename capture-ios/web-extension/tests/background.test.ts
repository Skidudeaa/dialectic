import { describe, expect, it, vi } from "vitest";

import { BackgroundController, installBackground, type BackgroundBrowser } from "../src/background-controller";
import { NATIVE_APPLICATION_IDENTIFIER } from "../src/config";
import type { CaptureEnvelope, CapturePageResponse } from "../src/contracts";

const capture: CaptureEnvelope = {
  capture_id: "00000000-0000-4000-8000-000000000003",
  url: "https://fixture.test/article",
  canonical_url: "https://fixture.test/article",
  title: "Article",
  author: null,
  site: "Fixture",
  published: null,
  description: null,
  language: "en",
  word_count: 12,
  capture_mode: "article",
  markdown: "# Article\n",
  content_sha256: "1".repeat(64),
  captured_at: "2026-08-28T12:00:00.000Z",
  note: null,
  extraction: {
    engine: "defuddle",
    engine_version: "0.19.3",
    client_version: "0.1.0",
    fallback_reason: null,
  },
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolver) => {
    resolve = resolver;
  });
  return { promise, resolve };
}

function fakeBrowser(captureResponse: Promise<CapturePageResponse>) {
  const statuses: unknown[] = [];
  let actionListener: ((tab: { id?: number; url?: string }) => void) | undefined;
  const browser: BackgroundBrowser = {
    action: {
      onClicked: {
        addListener: vi.fn((listener) => {
          actionListener = listener;
        }),
      },
    },
    scripting: {
      executeScript: vi.fn(async () => []),
    },
    tabs: {
      sendMessage: vi.fn(async (_tabID, message) => {
        if ((message as { type?: string }).type === "capture_page") return captureResponse;
        statuses.push(message);
        return { ok: true };
      }),
    },
    runtime: {
      sendNativeMessage: vi.fn(async () => ({
        local_durable: true,
        delivery_status: "filed",
        room_name: "Research",
      })),
    },
  };
  return { actionListener: () => actionListener, browser, statuses };
}

describe("background action", () => {
  it("registers the action listener at installation", () => {
    const ready = Promise.resolve<CapturePageResponse>({ type: "capture_ready", capture });
    const fake = fakeBrowser(ready);
    installBackground(fake.browser, "org.test.SomacuraCapture");
    expect(fake.browser.action.onClicked.addListener).toHaveBeenCalledOnce();
    expect(fake.actionListener()).toBeTypeOf("function");
  });

  it("coalesces duplicate clicks and sends one native queue message", async () => {
    const pending = deferred<CapturePageResponse>();
    const fake = fakeBrowser(pending.promise);
    const controller = new BackgroundController(fake.browser, "org.test.SomacuraCapture");

    const first = controller.handleActionClick({ id: 7, url: "https://fixture.test/article" });
    const second = controller.handleActionClick({ id: 7, url: "https://fixture.test/article" });
    pending.resolve({ type: "capture_ready", capture });
    await Promise.all([first, second]);

    expect(fake.browser.scripting.executeScript).toHaveBeenCalledOnce();
    expect(fake.browser.runtime.sendNativeMessage).toHaveBeenCalledOnce();
    expect(fake.browser.runtime.sendNativeMessage).toHaveBeenCalledWith(
      "org.test.SomacuraCapture",
      { type: "queue_capture", capture },
    );
    expect(fake.statuses).toContainEqual({
      type: "show_status",
      status: { level: "success", message: "Filed to Research" },
    });
  });

  it("maps a durable no-room native result to queued configuration status", async () => {
    const fake = fakeBrowser(Promise.resolve({ type: "capture_ready", capture }));
    vi.mocked(fake.browser.runtime.sendNativeMessage).mockResolvedValue({
      local_durable: true,
      delivery_status: "pending",
      error_category: "no_room",
    });
    const controller = new BackgroundController(fake.browser, "org.test.SomacuraCapture");

    await controller.handleActionClick({ id: 8, url: "https://fixture.test/article" });

    expect(fake.statuses).toContainEqual({
      type: "show_status",
      status: { level: "warning", message: "Saved locally — choose a room in Somacura Capture" },
    });
  });

  it("fails visibly and never calls native messaging while the bundle identifier is unresolved", async () => {
    const fake = fakeBrowser(Promise.resolve({ type: "capture_ready", capture }));
    expect(NATIVE_APPLICATION_IDENTIFIER).toBe("__SOMACURA_NATIVE_APPLICATION_IDENTIFIER__");
    const controller = new BackgroundController(fake.browser, NATIVE_APPLICATION_IDENTIFIER);

    await controller.handleActionClick({ id: 9, url: "https://fixture.test/article" });

    expect(fake.browser.runtime.sendNativeMessage).not.toHaveBeenCalled();
    expect(fake.statuses).toContainEqual({
      type: "show_status",
      status: { level: "error", message: "Capture failed locally: native app is not configured" },
    });
  });

  it("reports unknown status when native messaging fails after it may have committed", async () => {
    const fake = fakeBrowser(Promise.resolve({ type: "capture_ready", capture }));
    vi.mocked(fake.browser.runtime.sendNativeMessage).mockRejectedValue(new Error("connection closed"));
    const controller = new BackgroundController(fake.browser, "org.test.SomacuraCapture");

    await controller.handleActionClick({ id: 10, url: "https://fixture.test/article" });

    expect(fake.statuses).toContainEqual({
      type: "show_status",
      status: { level: "error", message: "Capture status unknown — check Somacura Capture" },
    });
  });
});
