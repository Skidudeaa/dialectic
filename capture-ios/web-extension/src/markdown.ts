import TurndownService from "turndown";
import { gfm } from "turndown-plugin-gfm";

const UNSAFE_REMOVALS = [
  "script",
  "style",
  "noscript",
  "template",
  "form",
  "input",
  "button",
  "select",
  "textarea",
  "[hidden]",
  "[aria-hidden='true']",
].join(",");

const FALLBACK_CHROME = "nav, footer";

const ACTIVE_PROTOCOLS = new Set(["javascript:", "data:", "vbscript:", "file:"]);
const LINK_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"]);
const MEDIA_PROTOCOLS = new Set(["http:", "https:"]);

function resolveSafeURL(rawValue: string, baseURL: string, protocols: Set<string>): string | null {
  const value = rawValue.trim();
  if (!value) return null;
  try {
    const resolved = new URL(value, baseURL);
    if (ACTIVE_PROTOCOLS.has(resolved.protocol) || !protocols.has(resolved.protocol)) {
      return null;
    }
    return resolved.href;
  } catch {
    return null;
  }
}

function normalizeSrcset(rawValue: string, baseURL: string): string | null {
  const candidates = rawValue
    .split(",")
    .map((candidate) => candidate.trim())
    .filter(Boolean)
    .flatMap((candidate) => {
      const [rawURL, ...descriptor] = candidate.split(/\s+/u);
      if (!rawURL) return [];
      const url = resolveSafeURL(rawURL, baseURL, MEDIA_PROTOCOLS);
      return url ? [`${url}${descriptor.length ? ` ${descriptor.join(" ")}` : ""}`] : [];
    });
  return candidates.length ? candidates.join(", ") : null;
}

export function normalizeElementURLs(root: ParentNode, baseURL: string): void {
  for (const anchor of root.querySelectorAll<HTMLAnchorElement>("a[href]")) {
    const resolved = resolveSafeURL(anchor.getAttribute("href") ?? "", baseURL, LINK_PROTOCOLS);
    if (resolved) anchor.setAttribute("href", resolved);
    else anchor.removeAttribute("href");
  }

  for (const image of root.querySelectorAll<HTMLImageElement>("img[src]")) {
    const resolved = resolveSafeURL(image.getAttribute("src") ?? "", baseURL, MEDIA_PROTOCOLS);
    if (resolved) image.setAttribute("src", resolved);
    else image.removeAttribute("src");
  }

  for (const source of root.querySelectorAll<HTMLSourceElement>("source[src], source[srcset], img[srcset]")) {
    if (source.hasAttribute("src")) {
      const resolved = resolveSafeURL(source.getAttribute("src") ?? "", baseURL, MEDIA_PROTOCOLS);
      if (resolved) source.setAttribute("src", resolved);
      else source.removeAttribute("src");
    }
    if (source.hasAttribute("srcset")) {
      const resolved = normalizeSrcset(source.getAttribute("srcset") ?? "", baseURL);
      if (resolved) source.setAttribute("srcset", resolved);
      else source.removeAttribute("srcset");
    }
  }
}

function sanitizeUnsafeRoot(root: ParentNode): void {
  for (const element of root.querySelectorAll(UNSAFE_REMOVALS)) {
    element.remove();
  }
  for (const element of root.querySelectorAll<HTMLElement>("*")) {
    for (const attribute of [...element.attributes]) {
      if (attribute.name.toLowerCase().startsWith("on")) {
        element.removeAttribute(attribute.name);
      }
    }
  }
}

export function sanitizeFallbackRoot(root: ParentNode): void {
  sanitizeUnsafeRoot(root);
  for (const element of root.querySelectorAll(FALLBACK_CHROME)) {
    element.remove();
  }
}

function createTurndownService(): TurndownService {
  const service = new TurndownService({
    headingStyle: "atx",
    bulletListMarker: "-",
    codeBlockStyle: "fenced",
    fence: "```",
    emDelimiter: "*",
    strongDelimiter: "**",
  });
  service.use(gfm);
  service.addRule("fencedCodeWithLanguage", {
    filter: (node) => node.nodeName === "PRE" && node.firstElementChild?.nodeName === "CODE",
    replacement: (_content, node) => {
      const element = node as HTMLElement;
      const code = element.firstElementChild as HTMLElement;
      const language = [...code.classList]
        .map((name) => name.match(/^(?:language|lang)-([a-z0-9_+-]+)$/iu)?.[1])
        .find(Boolean) ?? "";
      const value = (code.textContent ?? "").replace(/\n+$/u, "");
      const fence = value.includes("```") ? "````" : "```";
      return `\n\n${fence}${language}\n${value}\n${fence}\n\n`;
    },
  });
  return service;
}

export function normalizeMarkdown(markdown: string): string {
  const lf = markdown.replace(/\r\n?/gu, "\n");
  const withoutTrailingWhitespace = lf
    .split("\n")
    .map((line) => {
      const trailing = line.match(/[\t ]+$/u)?.[0];
      if (!trailing) return line;
      const content = line.slice(0, -trailing.length);
      return trailing.replace(/\t/gu, "    ").length >= 2 ? `${content}  ` : content;
    })
    .join("\n")
    .trimEnd();
  return `${withoutTrailingWhitespace}\n`;
}

export function domToMarkdown(root: TurndownService.Node, baseURL: string): string {
  const clone = root.cloneNode(true) as TurndownService.Node;
  sanitizeUnsafeRoot(clone as ParentNode);
  normalizeElementURLs(clone as ParentNode, baseURL);
  return normalizeMarkdown(createTurndownService().turndown(clone));
}

export function fallbackToMarkdown(body: HTMLElement, baseURL: string): string {
  const clone = body.cloneNode(true) as HTMLElement;
  sanitizeFallbackRoot(clone);
  normalizeElementURLs(clone, baseURL);
  return normalizeMarkdown(createTurndownService().turndown(clone));
}
