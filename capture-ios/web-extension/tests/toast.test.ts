import { JSDOM } from "jsdom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TOAST_HOST_ID } from "../src/config";
import { showToast } from "../src/toast";

describe("status toast", () => {
  afterEach(() => vi.useRealTimers());

  it("updates one isolated role=status host instead of stacking", () => {
    vi.useFakeTimers();
    const dom = new JSDOM("<!doctype html><html><body><main>Page</main></body></html>");

    showToast(dom.window.document, { level: "busy", message: "Capturing…" });
    showToast(dom.window.document, { level: "success", message: "Filed to Research" });

    expect(dom.window.document.querySelectorAll(`#${TOAST_HOST_ID}`)).toHaveLength(1);
    const host = dom.window.document.getElementById(TOAST_HOST_ID) as HTMLElement;
    expect(host.style.pointerEvents).toBe("none");
    const status = host.shadowRoot?.querySelector("[role='status']");
    expect(status?.textContent).toBe("Filed to Research");
    expect(dom.window.document.body.textContent).toBe("Page");
  });
});
