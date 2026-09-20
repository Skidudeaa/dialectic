// Acceptance check for OMC work_id capture-embedded-frames. Fixed before
// implementation; do not edit as part of the fix.
//
// WHY: a production capture of a Gomerblog article carried a raw Google Ads
// <iframe> into the stored Markdown. The article path returns Defuddle's own
// Markdown, which never passed through this project's sanitiser, and the
// sanitiser's removal list did not name embedded-frame elements either.
import { webcrypto } from "node:crypto";

import { JSDOM } from "jsdom";
import { describe, expect, it } from "vitest";

import { extractArticleWithDefuddle, extractCapture } from "../src/extraction";
import { domToMarkdown, fallbackToMarkdown } from "../src/markdown";
import { installDOMGlobals } from "./helpers";

const AD_SRC =
  "https://googleads.g.doubleclick.net/pagead/ads?client=ca-pub-1&amp;output=html&amp;h=280";

const ARTICLE_HTML = `<!doctype html><html lang="en"><head><title>Rewards Program</title></head><body>
  <main><article>
    <h1>Rewards Program</h1>
    <p>BEFORE-FRAME A general practitioner has created a new frequent flyer rewards program for
    chronic illness patients, and this deliberately substantial opening paragraph exists so the
    structural floor treats the page as a real article rather than a thin fragment.</p>
    <iframe sandbox="allow-scripts" width="696" height="280" frameborder="0" src="${AD_SRC}"
      title="Advertisement" aria-label="Advertisement"></iframe>
    <p>BETWEEN-FRAMES The program is versatile and easily modified for a multitude of chronic
    ailments, with an eighteen month window of unlimited referrals for qualifying patients.</p>
    <object data="https://ads.fixture.test/banner.swf" type="application/x-shockwave-flash">
      <embed src="https://ads.fixture.test/banner.swf"></object>
    <embed src="https://ads.fixture.test/second.swf" type="application/x-shockwave-flash">
    <p>AFTER-FRAMES When reached for comment the director of orthopaedic surgery promptly
    disconnected the call, which closes the article with a final substantial paragraph.</p>
  </article></main>
</body></html>`;

const FORBIDDEN = /<\s*(iframe|object|embed)\b|doubleclick|banner\.swf|second\.swf/iu;

function expectCleanProse(markdown: string): void {
  expect(markdown).not.toMatch(FORBIDDEN);
  expect(markdown).toContain("BEFORE-FRAME");
  expect(markdown).toContain("BETWEEN-FRAMES");
  expect(markdown).toContain("AFTER-FRAMES");
}

function articleDOM(): JSDOM {
  return new JSDOM(ARTICLE_HTML, { url: "https://fixture.test/rewards" });
}

describe("embedded frames never reach captured Markdown", () => {
  it("article path (Defuddle) drops iframe/object/embed and keeps the surrounding prose", () => {
    const dom = articleDOM();
    const restore = installDOMGlobals(dom);
    try {
      const result = extractArticleWithDefuddle(
        dom.window.document.cloneNode(true) as Document,
        dom.window.location.href,
      );
      expectCleanProse(result.markdown);
    } finally {
      restore();
    }
  });

  it("full capture in article mode is clean and still reports the defuddle engine", async () => {
    const dom = articleDOM();
    const restore = installDOMGlobals(dom);
    try {
      const capture = await extractCapture(dom.window.document, {
        crypto: webcrypto as unknown as Crypto,
        randomUUID: () => "00000000-0000-4000-8000-000000000002",
        now: () => new Date("2026-09-20T00:00:00.000Z"),
        selection: null,
      });
      expect(capture.capture_mode).toBe("article");
      expect(capture.extraction.engine).toBe("defuddle");
      expectCleanProse(capture.markdown);
    } finally {
      restore();
    }
  });

  it("selection path (domToMarkdown) drops embedded frames", () => {
    const dom = articleDOM();
    const article = dom.window.document.querySelector("article") as HTMLElement;
    expectCleanProse(domToMarkdown(article, dom.window.location.href));
  });

  it("fallback path (fallbackToMarkdown) drops embedded frames", () => {
    const dom = articleDOM();
    expectCleanProse(fallbackToMarkdown(dom.window.document.body, dom.window.location.href));
  });

  it("does not mutate the live page: the source document keeps its iframe", async () => {
    const dom = articleDOM();
    const restore = installDOMGlobals(dom);
    try {
      await extractCapture(dom.window.document, {
        crypto: webcrypto as unknown as Crypto,
        randomUUID: () => "00000000-0000-4000-8000-000000000003",
        now: () => new Date("2026-09-20T00:00:00.000Z"),
        selection: null,
      });
      expect(dom.window.document.querySelectorAll("iframe")).toHaveLength(1);
      expect(dom.window.document.querySelectorAll("embed").length).toBeGreaterThan(0);
    } finally {
      restore();
    }
  });
});
