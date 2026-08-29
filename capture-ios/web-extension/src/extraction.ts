import Defuddle from "defuddle/full";

import {
  CLIENT_VERSION,
  DEFUDDLE_VERSION,
  MAX_MARKDOWN_BYTES,
  TOAST_HOST_ID,
} from "./config";
import type {
  CaptureEnvelope,
  CaptureExtraction,
  CaptureMode,
} from "./contracts";
import { CaptureError, boundedText } from "./errors";
import {
  domToMarkdown,
  fallbackToMarkdown,
  normalizeElementURLs,
  normalizeMarkdown,
} from "./markdown";

const ARTICLE_MIN_VISIBLE_CHARACTERS = 40;

export interface ArticleExtraction {
  markdown: string;
  title?: string | null;
  author?: string | null;
  site?: string | null;
  published?: string | null;
  description?: string | null;
  language?: string | null;
  wordCount?: number | null;
}

export type ArticleParser = (document: Document, url: string) => ArticleExtraction | Promise<ArticleExtraction>;

export interface CaptureDependencies {
  articleParser?: ArticleParser;
  selection?: Selection | null;
  now?: () => Date;
  randomUUID?: () => string;
  crypto?: Crypto;
}

function cloneRenderedDocument(source: Document): Document {
  const clone = source.cloneNode(true) as Document;
  clone.getElementById(TOAST_HOST_ID)?.remove();
  return clone;
}

export function extractArticleWithDefuddle(document: Document, url: string): ArticleExtraction {
  normalizeElementURLs(document, url);
  const result = new Defuddle(document, {
    url,
    separateMarkdown: true,
    useAsync: false,
  }).parse();
  if (typeof result.contentMarkdown !== "string") {
    throw new CaptureError("defuddle_missing_markdown", "Article extraction did not return Markdown");
  }
  if (result.contentMarkdown.startsWith("Partial conversion completed with errors.")) {
    throw new CaptureError("defuddle_markdown_error", "Article Markdown conversion failed");
  }
  return {
    markdown: result.contentMarkdown,
    title: result.title,
    author: result.author,
    site: result.site || result.domain,
    published: result.published,
    description: result.description,
    language: result.language,
    wordCount: result.wordCount,
  };
}

function isMeaningfulSelection(selection: Selection | null | undefined): selection is Selection {
  return Boolean(selection && selection.rangeCount > 0 && selection.toString().trim().length > 0);
}

function selectionMarkdown(selection: Selection, document: Document, baseURL: string): string {
  const container = document.createElement("div");
  container.append(selection.getRangeAt(0).cloneContents());
  return domToMarkdown(container, baseURL);
}

function visibleText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/gu, " code ")
    .replace(/!\[[^\]]*\]\([^)]*\)/gu, " image ")
    .replace(/\[([^\]]+)\]\([^)]*\)/gu, "$1")
    .replace(/[#>*_`|~-]/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
}

function countWords(markdown: string): number {
  const text = visibleText(markdown);
  return text ? text.split(/\s+/u).length : 0;
}

function metaContent(document: Document, selector: string): string | null {
  const value = document.querySelector<HTMLMetaElement>(selector)?.content.trim();
  return value || null;
}

function boundedMetadata(value: string | null | undefined, maximum: number): string | null {
  if (!value) return null;
  const normalized = value.replace(/\s+/gu, " ").trim();
  return normalized ? boundedText(normalized, maximum) : null;
}

function httpURL(value: string, label: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new CaptureError(`${label}_invalid`, "Capture is available only on HTTP or HTTPS pages");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new CaptureError(`${label}_unsupported`, "Capture is available only on HTTP or HTTPS pages");
  }
  if (parsed.href.length > 4096) {
    throw new CaptureError(`${label}_too_long`, "The page URL is too long to capture safely");
  }
  return parsed.href;
}

export function stripTextFragment(value: string): string {
  const parsed = new URL(value);
  const markerIndex = parsed.hash.indexOf(":~:text=");
  if (markerIndex >= 0) {
    const prefix = parsed.hash.slice(0, markerIndex);
    parsed.hash = prefix === "#" ? "" : prefix;
  }
  return parsed.href;
}

function canonicalURL(document: Document, fallbackURL: string): string | null {
  const raw = document.querySelector<HTMLLinkElement>("link[rel~='canonical'][href]")?.href;
  if (!raw) return fallbackURL;
  try {
    return stripTextFragment(httpURL(raw, "canonical_url"));
  } catch {
    return fallbackURL;
  }
}

function fallbackReason(error: unknown): string {
  if (error instanceof CaptureError) return boundedText(error.category, 100);
  return "defuddle_error";
}

function uuidV4(cryptoImpl: Crypto): string {
  if (typeof cryptoImpl.randomUUID === "function") return cryptoImpl.randomUUID();
  const bytes = cryptoImpl.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export async function sha256Hex(markdown: string, cryptoImpl: Crypto = globalThis.crypto): Promise<string> {
  if (!cryptoImpl?.subtle) {
    throw new CaptureError("hash_unavailable", "Capture failed locally: SHA-256 is unavailable");
  }
  const digest = await cryptoImpl.subtle.digest("SHA-256", new TextEncoder().encode(markdown));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function extractionMetadata(mode: CaptureMode, reason: string | null): CaptureExtraction {
  return {
    engine: mode === "article" ? "defuddle" : "browser_dom",
    engine_version: mode === "article" ? DEFUDDLE_VERSION : CLIENT_VERSION,
    client_version: CLIENT_VERSION,
    fallback_reason: reason,
  };
}

export async function extractCapture(
  document: Document,
  dependencies: CaptureDependencies = {},
): Promise<CaptureEnvelope> {
  const cryptoImpl = dependencies.crypto ?? globalThis.crypto;
  const sourceURL = stripTextFragment(httpURL(document.location.href, "url"));
  const selection = dependencies.selection === undefined
    ? document.defaultView?.getSelection()
    : dependencies.selection;
  let mode: CaptureMode;
  let markdown: string;
  let reason: string | null = null;
  let article: ArticleExtraction | null = null;

  if (isMeaningfulSelection(selection)) {
    mode = "selection";
    markdown = selectionMarkdown(selection, document, sourceURL);
  } else {
    const parser = dependencies.articleParser ?? extractArticleWithDefuddle;
    try {
      article = await parser(cloneRenderedDocument(document), sourceURL);
      markdown = normalizeMarkdown(article.markdown);
      if (visibleText(markdown).length < ARTICLE_MIN_VISIBLE_CHARACTERS) {
        throw new CaptureError("defuddle_thin", "Article extraction was structurally thin");
      }
      mode = "article";
    } catch (error) {
      mode = "page_fallback";
      reason = fallbackReason(error);
      const fallbackDocument = cloneRenderedDocument(document);
      if (!fallbackDocument.body) {
        throw new CaptureError("page_body_missing", "Capture failed locally: page body is unavailable");
      }
      markdown = fallbackToMarkdown(fallbackDocument.body, sourceURL);
    }
  }

  markdown = normalizeMarkdown(markdown);
  if (!visibleText(markdown)) {
    throw new CaptureError("markdown_empty", "Capture failed locally: the page produced no readable content");
  }
  const bodyBytes = new TextEncoder().encode(markdown).byteLength;
  if (bodyBytes > MAX_MARKDOWN_BYTES) {
    throw new CaptureError("markdown_too_large", "Capture failed locally: Markdown exceeds the 2 MB limit");
  }

  const pageTitle = boundedMetadata(article?.title || document.title, 500)
    ?? boundedMetadata(new URL(sourceURL).hostname, 500)
    ?? "Untitled capture";
  const captureID = dependencies.randomUUID
    ? dependencies.randomUUID()
    : uuidV4(cryptoImpl);

  return {
    capture_id: captureID,
    url: sourceURL,
    canonical_url: canonicalURL(document, sourceURL),
    title: pageTitle,
    author: boundedMetadata(article?.author ?? metaContent(document, "meta[name='author']"), 300),
    site: boundedMetadata(
      article?.site ?? metaContent(document, "meta[property='og:site_name']") ?? new URL(sourceURL).hostname,
      200,
    ),
    published: boundedMetadata(
      article?.published
        ?? metaContent(document, "meta[property='article:published_time']")
        ?? metaContent(document, "meta[name='date']"),
      100,
    ),
    description: boundedMetadata(
      article?.description
        ?? metaContent(document, "meta[name='description']")
        ?? metaContent(document, "meta[property='og:description']"),
      1000,
    ),
    language: boundedMetadata(article?.language ?? document.documentElement.lang, 35),
    word_count: Number.isInteger(article?.wordCount) && (article?.wordCount ?? -1) >= 0
      ? article?.wordCount ?? 0
      : countWords(markdown),
    capture_mode: mode,
    markdown,
    content_sha256: await sha256Hex(markdown, cryptoImpl),
    captured_at: (dependencies.now ?? (() => new Date()))().toISOString(),
    note: null,
    extraction: extractionMetadata(mode, reason),
  };
}
