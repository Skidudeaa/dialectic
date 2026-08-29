export const CAPTURE_MESSAGE_TYPE = "capture_page" as const;
export const STATUS_MESSAGE_TYPE = "show_status" as const;
export const QUEUE_MESSAGE_TYPE = "queue_capture" as const;

export type CaptureMode = "selection" | "article" | "page_fallback";
export type DeliveryStatus = "pending" | "filing" | "filed" | "needs_attention";

export interface CaptureExtraction {
  engine: string;
  engine_version: string;
  client_version: string;
  fallback_reason: string | null;
}

export interface CaptureEnvelope {
  capture_id: string;
  url: string;
  canonical_url: string | null;
  title: string;
  author: string | null;
  site: string | null;
  published: string | null;
  description: string | null;
  language: string | null;
  word_count: number;
  capture_mode: CaptureMode;
  markdown: string;
  content_sha256: string;
  captured_at: string;
  note: null;
  extraction: CaptureExtraction;
}

export interface CapturePageRequest {
  type: typeof CAPTURE_MESSAGE_TYPE;
}

export interface PublicCaptureError {
  category: string;
  message: string;
}

export interface CaptureReadyResponse {
  type: "capture_ready";
  capture: CaptureEnvelope;
}

export interface CaptureErrorResponse {
  type: "capture_error";
  error: PublicCaptureError;
}

export type CapturePageResponse = CaptureReadyResponse | CaptureErrorResponse;

export type ToastLevel = "busy" | "success" | "warning" | "error";

export interface ToastStatus {
  level: ToastLevel;
  message: string;
  dismiss_after_ms?: number;
}

export interface ShowStatusRequest {
  type: typeof STATUS_MESSAGE_TYPE;
  status: ToastStatus;
}

export interface NativeQueueRequest {
  type: typeof QUEUE_MESSAGE_TYPE;
  capture: CaptureEnvelope;
}

export interface NativeQueueResult {
  local_durable: boolean;
  delivery_status: DeliveryStatus;
  room_name?: string | null;
  error_category?: string | null;
  error_message?: string | null;
}

export type ContentMessage = CapturePageRequest | ShowStatusRequest;

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isCapturePageResponse(value: unknown): value is CapturePageResponse {
  if (!isRecord(value)) return false;
  if (value.type === "capture_ready") {
    return isRecord(value.capture) && typeof value.capture.markdown === "string";
  }
  return value.type === "capture_error"
    && isRecord(value.error)
    && typeof value.error.category === "string"
    && typeof value.error.message === "string";
}

export function parseNativeQueueResult(value: unknown): NativeQueueResult {
  if (!isRecord(value)
      || typeof value.local_durable !== "boolean"
      || typeof value.delivery_status !== "string"
      || !["pending", "filing", "filed", "needs_attention"].includes(value.delivery_status)) {
    throw new Error("native_result_invalid");
  }

  return {
    local_durable: value.local_durable,
    delivery_status: value.delivery_status as DeliveryStatus,
    room_name: typeof value.room_name === "string" ? value.room_name : null,
    error_category: typeof value.error_category === "string" ? value.error_category : null,
    error_message: typeof value.error_message === "string" ? value.error_message : null,
  };
}
