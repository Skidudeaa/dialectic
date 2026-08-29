"use strict";
(() => {
  // src/contracts.ts
  var CAPTURE_MESSAGE_TYPE = "capture_page", STATUS_MESSAGE_TYPE = "show_status";
  function isRecord(value) {
    return typeof value == "object" && value !== null;
  }
  function isCapturePageResponse(value) {
    return isRecord(value) ? value.type === "capture_ready" ? isRecord(value.capture) && typeof value.capture.markdown == "string" : value.type === "capture_error" && isRecord(value.error) && typeof value.error.category == "string" && typeof value.error.message == "string" : !1;
  }
  function parseNativeQueueResult(value) {
    if (!isRecord(value) || typeof value.local_durable != "boolean" || typeof value.delivery_status != "string" || !["pending", "filing", "filed", "needs_attention"].includes(value.delivery_status))
      throw new Error("native_result_invalid");
    return {
      local_durable: value.local_durable,
      delivery_status: value.delivery_status,
      room_name: typeof value.room_name == "string" ? value.room_name : null,
      error_category: typeof value.error_category == "string" ? value.error_category : null,
      error_message: typeof value.error_message == "string" ? value.error_message : null
    };
  }

  // src/config.ts
  var NATIVE_APPLICATION_IDENTIFIER = "com.example.unconfigured.SomacuraCapture";
  function isConfiguredNativeIdentifier(identifier) {
    return identifier.length > 0 && !identifier.startsWith("__");
  }

  // src/errors.ts
  function boundedText(value, maximum = 180) {
    let normalized = value.replace(/[\r\n\t]+/gu, " ").replace(/\s{2,}/gu, " ").trim();
    return normalized.length <= maximum ? normalized : `${normalized.slice(0, Math.max(0, maximum - 1)).trimEnd()}\u2026`;
  }

  // src/background-controller.ts
  function isHTTPPage(tab) {
    if (!tab.url) return !0;
    try {
      let protocol = new URL(tab.url).protocol;
      return protocol === "http:" || protocol === "https:";
    } catch {
      return !1;
    }
  }
  function nativeStatus(result) {
    return result.local_durable ? result.delivery_status === "filed" ? {
      level: "success",
      message: result.room_name ? `Filed to ${boundedText(result.room_name, 80)}` : "Filed"
    } : result.error_category === "no_room" ? { level: "warning", message: "Saved locally \u2014 choose a room in Somacura Capture" } : result.delivery_status === "needs_attention" ? {
      level: "warning",
      message: result.error_message ? `Saved locally \u2014 ${boundedText(result.error_message, 120)}` : "Saved locally \u2014 needs attention"
    } : { level: "warning", message: "Saved locally \u2014 queued" } : { level: "error", message: "Capture failed locally: queue write failed" };
  }
  var BackgroundController = class {
    constructor(browser2, nativeApplicationIdentifier) {
      this.browser = browser2;
      this.nativeApplicationIdentifier = nativeApplicationIdentifier;
    }
    inFlight = /* @__PURE__ */ new Map();
    handleActionClick(tab) {
      if (tab.id === void 0) return Promise.resolve();
      let existing = this.inFlight.get(tab.id);
      if (existing)
        return this.showStatus(tab.id, { level: "busy", message: "Capturing\u2026" }), existing;
      let operation = this.captureAndQueue(tab).finally(() => this.inFlight.delete(tab.id));
      return this.inFlight.set(tab.id, operation), operation;
    }
    async captureAndQueue(tab) {
      let tabID = tab.id;
      if (tabID === void 0) return;
      if (!isHTTPPage(tab)) {
        await this.showStatus(tabID, {
          level: "error",
          message: "Capture is available only on HTTP or HTTPS pages"
        });
        return;
      }
      let nativeAttempted = !1;
      try {
        await this.browser.scripting.executeScript({
          target: { tabId: tabID },
          files: ["content.js"]
        });
        let response = await this.browser.tabs.sendMessage(tabID, { type: CAPTURE_MESSAGE_TYPE });
        if (!isCapturePageResponse(response)) throw new Error("content_response_invalid");
        if (response.type === "capture_error") {
          await this.showStatus(tabID, { level: "error", message: response.error.message });
          return;
        }
        if (!isConfiguredNativeIdentifier(this.nativeApplicationIdentifier))
          throw new Error("native_identifier_unconfigured");
        nativeAttempted = !0;
        let nativeValue = await this.browser.runtime.sendNativeMessage(
          this.nativeApplicationIdentifier,
          { type: "queue_capture", capture: response.capture }
        );
        await this.showStatus(tabID, nativeStatus(parseNativeQueueResult(nativeValue)));
      } catch (error) {
        let category = error instanceof Error ? error.message : "capture_failed", message = category === "native_identifier_unconfigured" ? "Capture failed locally: native app is not configured" : nativeAttempted || category === "native_result_invalid" ? "Capture status unknown \u2014 check Somacura Capture" : "Capture failed locally: extension communication failed";
        await this.showStatus(tabID, { level: "error", message });
      }
    }
    async showStatus(tabID, status) {
      let request = { type: STATUS_MESSAGE_TYPE, status };
      try {
        await this.browser.tabs.sendMessage(tabID, request);
      } catch {
      }
    }
  };
  function installBackground(browser2, nativeApplicationIdentifier) {
    let controller = new BackgroundController(browser2, nativeApplicationIdentifier);
    return browser2.action.onClicked.addListener((tab) => {
      controller.handleActionClick(tab);
    }), controller;
  }

  // src/background.ts
  installBackground(browser, NATIVE_APPLICATION_IDENTIFIER);
})();
