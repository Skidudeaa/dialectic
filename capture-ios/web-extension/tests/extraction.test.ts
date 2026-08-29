import { webcrypto } from "node:crypto";

import { JSDOM } from "jsdom";
import { describe, expect, it, vi } from "vitest";

import {
  extractArticleWithDefuddle,
  extractCapture,
  sha256Hex,
} from "../src/extraction";
import { domToMarkdown } from "../src/markdown";
import { fixtureDOM, installDOMGlobals } from "./helpers";

const CAPTURE_ID = "00000000-0000-4000-8000-000000000001";
const NOW = new Date("2026-08-28T12:34:56.000Z");

function deterministic() {
  return {
    crypto: webcrypto as unknown as Crypto,
    randomUUID: () => CAPTURE_ID,
    now: () => NOW,
  };
}

describe("capture extraction", () => {
  it("captures a meaningful short selection without invoking article extraction", () => {
    const dom = new JSDOM(`<!doctype html><html><head><title>Selection</title></head><body>
      <p id="outside">Outside prose must not appear.</p>
      <p id="selected">短い <a href="/proof">proof ✓</a><script>selectedSecret()</script></p>
    </body></html>`, { url: "https://fixture.test/path/page" });
    const selected = dom.window.document.querySelector("#selected");
    const range = dom.window.document.createRange();
    range.selectNodeContents(selected as Node);
    const selection = dom.window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    const articleParser = vi.fn(() => {
      throw new Error("must not run");
    });

    return expect(extractCapture(dom.window.document, {
      ...deterministic(),
      selection,
      articleParser,
    })).resolves.toMatchObject({
      capture_id: CAPTURE_ID,
      capture_mode: "selection",
      captured_at: NOW.toISOString(),
      markdown: "短い [proof ✓](https://fixture.test/proof)\n",
    }).then(() => {
      expect(articleParser).not.toHaveBeenCalled();
    });
  });

  it("clones the final rendered DOM for article extraction", async () => {
    const dom = await fixtureDOM("rendered.html");
    const app = dom.window.document.querySelector("#app") as HTMLElement;
    app.innerHTML = `<h1>Client-rendered heading</h1>
      <p>Hydrated content exists only after JavaScript has rendered the live document into its final state.</p>`;
    const articleParser = vi.fn((document: Document, url: string) => ({
      markdown: domToMarkdown(document.querySelector("main") as HTMLElement, url),
      wordCount: 15,
    }));

    const capture = await extractCapture(dom.window.document, {
      ...deterministic(),
      selection: null,
      articleParser,
    });

    expect(capture.capture_mode).toBe("article");
    expect(capture.markdown).toContain("# Client-rendered heading");
    expect(capture.markdown).toContain("Hydrated content");
    expect(articleParser.mock.calls[0]?.[0]).not.toBe(dom.window.document);
  });

  it("labels and sanitizes page fallback when Defuddle fails", async () => {
    const dom = await fixtureDOM("article.html");
    const capture = await extractCapture(dom.window.document, {
      ...deterministic(),
      selection: null,
      articleParser: () => {
        throw new Error("page-controlled sensitive detail");
      },
    });

    expect(capture.capture_mode).toBe("page_fallback");
    expect(capture.extraction).toMatchObject({
      engine: "browser_dom",
      fallback_reason: "defuddle_error",
    });
    expect(capture.markdown).toContain("# Rendered evidence");
    expect(capture.markdown).not.toContain("Repeated navigation");
    expect(capture.markdown).not.toContain("Submit");
    expect(capture.markdown).not.toContain("window.hostile");
    expect(capture.content_sha256).toBe(await sha256Hex(capture.markdown, webcrypto as unknown as Crypto));
  });

  it("uses Defuddle 0.19.3's browser class API and separate Markdown output", async () => {
    const dom = new JSDOM(`<!doctype html><html lang="en"><head><title>Defuddle API</title></head><body>
      <main><article><h1>Browser parser</h1><p>
      This deliberately substantial paragraph proves the installed browser class parses a cloned rendered document
      synchronously and emits a separate Markdown body without relying on the server-side node entrypoint.
      </p></article></main>
    </body></html>`, { url: "https://fixture.test/defuddle" });
    const restore = installDOMGlobals(dom);
    try {
      const result = extractArticleWithDefuddle(
        dom.window.document.cloneNode(true) as Document,
        dom.window.location.href,
      );
      expect(result.markdown).toContain("## Browser parser");
      expect(result.markdown).toContain("installed browser class");
    } finally {
      restore();
    }
  });

  it("strips text fragments and emits deterministic SHA-256", async () => {
    const dom = new JSDOM(`<!doctype html><html><head><title>Hash</title>
      <link rel="canonical" href="/canonical#:~:text=private-fragment">
      </head><body><main>Hash material long enough to remain an article after the structural floor.</main></body></html>`, {
      url: "https://fixture.test/story#:~:text=selected-words",
    });
    const capture = await extractCapture(dom.window.document, {
      ...deterministic(),
      selection: null,
      articleParser: () => ({ markdown: "# Hi\r\n" }),
    });

    expect(capture.url).toBe("https://fixture.test/story");
    expect(capture.canonical_url).toBe("https://fixture.test/canonical");
    expect(await sha256Hex("# Hi\n", webcrypto as unknown as Crypto))
      .toBe("19812277b04a5a988e4dc361617bcb927d4297c47353da93aa992ac007f1f3cf");
  });
});
