import {
  CAPTURE_MESSAGE_TYPE,
  STATUS_MESSAGE_TYPE,
  type CapturePageResponse,
  type ContentMessage,
} from "./contracts";
import { publicCaptureError } from "./errors";
import { extractCapture, type CaptureDependencies } from "./extraction";
import { showToast } from "./toast";

export interface ContentRuntime {
  onMessage: {
    addListener(
      listener: (message: unknown) => CapturePageResponse | Promise<CapturePageResponse> | { ok: true } | undefined,
    ): void;
  };
}

export class ContentController {
  private inFlight: Promise<CapturePageResponse> | null = null;

  constructor(
    private readonly document: Document,
    private readonly dependencies: CaptureDependencies = {},
  ) {}

  handleMessage(message: unknown): CapturePageResponse | Promise<CapturePageResponse> | { ok: true } | undefined {
    if (!message || typeof message !== "object" || !("type" in message)) return undefined;
    const typedMessage = message as ContentMessage;
    if (typedMessage.type === STATUS_MESSAGE_TYPE) {
      showToast(this.document, typedMessage.status);
      return { ok: true };
    }
    if (typedMessage.type !== CAPTURE_MESSAGE_TYPE) return undefined;
    return this.capture();
  }

  capture(): Promise<CapturePageResponse> {
    if (this.inFlight) return this.inFlight;
    showToast(this.document, { level: "busy", message: "Capturing…" });
    this.inFlight = extractCapture(this.document, this.dependencies)
      .then((capture): CapturePageResponse => ({ type: "capture_ready", capture }))
      .catch((error): CapturePageResponse => {
        const publicError = publicCaptureError(error);
        showToast(this.document, { level: "error", message: publicError.message });
        return { type: "capture_error", error: publicError };
      })
      .finally(() => {
        this.inFlight = null;
      });
    return this.inFlight;
  }
}

export function installContentController(
  runtime: ContentRuntime,
  document: Document,
  dependencies: CaptureDependencies = {},
): ContentController {
  const controller = new ContentController(document, dependencies);
  runtime.onMessage.addListener((message) => controller.handleMessage(message));
  return controller;
}
