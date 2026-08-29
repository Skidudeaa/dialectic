import { describe, expect, it } from "vitest";

import { domToMarkdown, normalizeMarkdown } from "../src/markdown";
import { fixtureDOM } from "./helpers";

describe("DOM to Markdown", () => {
  it("preserves structured evidence and resolves safe relative assets", async () => {
    const dom = await fixtureDOM("article.html");
    const article = dom.window.document.querySelector("article");
    expect(article).not.toBeNull();

    const markdown = domToMarkdown(article as HTMLElement, dom.window.location.href);

    expect(markdown).toContain("# Rendered evidence");
    expect(markdown).toMatch(/-\s+First item/u);
    expect(markdown).toContain("*emphasis*");
    expect(markdown).toContain("**weight**");
    expect(markdown).toContain("[a source](https://fixture.test/source)");
    expect(markdown).toContain("![Evidence figure](https://fixture.test/images/figure.png)");
    expect(markdown).toMatch(/\|\s*Signal\s*\|\s*Value\s*\|/u);
    expect(markdown).toContain("`capture()`");
    expect(markdown).toContain("```swift\nlet mode = \"article\"");
    expect(markdown).toContain("Δ 東京 🩺");
    expect(markdown).not.toContain("javascript:");
    expect(markdown.endsWith("\n")).toBe(true);
    expect(markdown.endsWith("\n\n")).toBe(false);
  });

  it("normalizes CRLF, CR, trailing spaces, and the final newline", () => {
    expect(normalizeMarkdown("# One\r\n\rTwo  \r\n\r\n")).toBe("# One\n\nTwo\n");
    expect(normalizeMarkdown("First  \r\nSecond\r\n")).toBe("First  \nSecond\n");
  });
});
