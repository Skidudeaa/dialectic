import {
  CAPTURE_MESSAGE_TYPE,
  STATUS_MESSAGE_TYPE,
  type CapturePageResponse,
  type NativeQueueResult,
  type ShowStatusRequest,
  type ToastStatus,
  isCapturePageResponse,
  parseNativeQueueResult,
} from "./contracts";
import { isConfiguredNativeIdentifier } from "./config";
import { boundedText } from "./errors";

export interface BrowserTab {
  id?: number;
  url?: string;
}

export interface BackgroundBrowser {
  action: {
    onClicked: {
      addListener(listener: (tab: BrowserTab) => void): void;
    };
  };
  scripting: {
    executeScript(details: { target: { tabId: number }; files: string[] }): Promise<unknown>;
  };
  tabs: {
    sendMessage(tabId: number, message: unknown): Promise<unknown>;
  };
  runtime: {
    sendNativeMessage(applicationIdentifier: string, message: unknown): Promise<unknown>;
  };
}

function isHTTPPage(tab: BrowserTab): boolean {
  if (!tab.url) return true;
  try {
    const protocol = new URL(tab.url).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

function nativeStatus(result: NativeQueueResult): ToastStatus {
  if (!result.local_durable) {
    return { level: "error", message: "Capture failed locally: queue write failed" };
  }
  if (result.delivery_status === "filed") {
    return {
      level: "success",
      message: result.room_name ? `Filed to ${boundedText(result.room_name, 80)}` : "Filed",
    };
  }
  if (result.error_category === "no_room") {
    return { level: "warning", message: "Saved locally — choose a room in Somacura Capture" };
  }
  if (result.delivery_status === "needs_attention") {
    return {
      level: "warning",
      message: result.error_message
        ? `Saved locally — ${boundedText(result.error_message, 120)}`
        : "Saved locally — needs attention",
    };
  }
  return { level: "warning", message: "Saved locally — queued" };
}

export class BackgroundController {
  private readonly inFlight = new Map<number, Promise<void>>();

  constructor(
    private readonly browser: BackgroundBrowser,
    private readonly nativeApplicationIdentifier: string,
  ) {}

  handleActionClick(tab: BrowserTab): Promise<void> {
    if (tab.id === undefined) return Promise.resolve();
    const existing = this.inFlight.get(tab.id);
    if (existing) {
      void this.showStatus(tab.id, { level: "busy", message: "Capturing…" });
      return existing;
    }

    const operation = this.captureAndQueue(tab)
      .finally(() => this.inFlight.delete(tab.id as number));
    this.inFlight.set(tab.id, operation);
    return operation;
  }

  private async captureAndQueue(tab: BrowserTab): Promise<void> {
    const tabID = tab.id;
    if (tabID === undefined) return;
    if (!isHTTPPage(tab)) {
      await this.showStatus(tabID, {
        level: "error",
        message: "Capture is available only on HTTP or HTTPS pages",
      });
      return;
    }

    let nativeAttempted = false;
    try {
      await this.browser.scripting.executeScript({
        target: { tabId: tabID },
        files: ["content.js"],
      });
      const response = await this.browser.tabs.sendMessage(tabID, { type: CAPTURE_MESSAGE_TYPE });
      if (!isCapturePageResponse(response)) throw new Error("content_response_invalid");
      if (response.type === "capture_error") {
        await this.showStatus(tabID, { level: "error", message: response.error.message });
        return;
      }
      if (!isConfiguredNativeIdentifier(this.nativeApplicationIdentifier)) {
        throw new Error("native_identifier_unconfigured");
      }
      nativeAttempted = true;
      const nativeValue = await this.browser.runtime.sendNativeMessage(
        this.nativeApplicationIdentifier,
        { type: "queue_capture", capture: response.capture },
      );
      await this.showStatus(tabID, nativeStatus(parseNativeQueueResult(nativeValue)));
    } catch (error) {
      const category = error instanceof Error ? error.message : "capture_failed";
      const message = category === "native_identifier_unconfigured"
        ? "Capture failed locally: native app is not configured"
        : nativeAttempted || category === "native_result_invalid"
          ? "Capture status unknown — check Somacura Capture"
          : "Capture failed locally: extension communication failed";
      await this.showStatus(tabID, { level: "error", message });
    }
  }

  private async showStatus(tabID: number, status: ToastStatus): Promise<void> {
    const request: ShowStatusRequest = { type: STATUS_MESSAGE_TYPE, status };
    try {
      await this.browser.tabs.sendMessage(tabID, request);
    } catch {
      // A restricted page may reject content messaging; there is no safe page UI fallback.
    }
  }
}

export function installBackground(
  browser: BackgroundBrowser,
  nativeApplicationIdentifier: string,
): BackgroundController {
  const controller = new BackgroundController(browser, nativeApplicationIdentifier);
  browser.action.onClicked.addListener((tab) => {
    void controller.handleActionClick(tab);
  });
  return controller;
}

export type { CapturePageResponse };
