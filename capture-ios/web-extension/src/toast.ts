import { TOAST_HOST_ID } from "./config";
import type { ToastStatus } from "./contracts";

const DEFAULT_DISMISS_MS = 3_200;
const ERROR_DISMISS_MS = 8_000;

let dismissalTimer: ReturnType<typeof setTimeout> | undefined;

function toastHost(document: Document): HTMLElement {
  const existing = document.getElementById(TOAST_HOST_ID);
  if (existing) return existing;

  const host = document.createElement("div");
  host.id = TOAST_HOST_ID;
  host.style.setProperty("all", "initial", "important");
  host.style.setProperty("position", "fixed", "important");
  host.style.setProperty("right", "max(16px, env(safe-area-inset-right))", "important");
  host.style.setProperty("bottom", "max(16px, env(safe-area-inset-bottom))", "important");
  host.style.setProperty("z-index", "2147483647", "important");
  host.style.setProperty("pointer-events", "none", "important");
  host.attachShadow({ mode: "open" });
  (document.documentElement || document.body).append(host);
  return host;
}

export function showToast(document: Document, status: ToastStatus): void {
  const host = toastHost(document);
  const shadow = host.shadowRoot;
  if (!shadow) return;

  const colors = status.level === "error"
    ? { border: "#ff8066", text: "#ffe8e2" }
    : status.level === "warning"
      ? { border: "#efb366", text: "#fff0d8" }
      : status.level === "success"
        ? { border: "#48c7b0", text: "#e0fff9" }
        : { border: "#d99a52", text: "#fff2df" };

  shadow.innerHTML = `
    <style>
      :host { color-scheme: dark; }
      [role="status"] {
        box-sizing: border-box;
        max-width: min(360px, calc(100vw - 32px));
        padding: 10px 13px;
        border: 1px solid ${colors.border};
        border-radius: 10px;
        background: rgba(13, 13, 12, 0.96);
        color: ${colors.text};
        box-shadow: 0 10px 32px rgba(0, 0, 0, 0.42);
        font: 600 14px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        letter-spacing: 0.01em;
        overflow-wrap: anywhere;
        pointer-events: none;
      }
    </style>
    <div role="status" aria-live="polite" aria-atomic="true"></div>
  `;
  const statusElement = shadow.querySelector<HTMLElement>("[role='status']");
  if (statusElement) statusElement.textContent = status.message;

  if (dismissalTimer !== undefined) {
    clearTimeout(dismissalTimer);
    dismissalTimer = undefined;
  }
  if (status.level !== "busy") {
    dismissalTimer = setTimeout(() => host.remove(), status.dismiss_after_ms
      ?? (status.level === "error" ? ERROR_DISMISS_MS : DEFAULT_DISMISS_MS));
  }
}
