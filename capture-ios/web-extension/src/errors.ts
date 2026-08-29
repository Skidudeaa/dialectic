import { MAX_ERROR_MESSAGE_LENGTH } from "./config";
import type { PublicCaptureError } from "./contracts";

export class CaptureError extends Error {
  constructor(
    readonly category: string,
    readonly publicMessage: string,
  ) {
    super(category);
    this.name = "CaptureError";
  }
}

export function boundedText(value: string, maximum = MAX_ERROR_MESSAGE_LENGTH): string {
  const normalized = value.replace(/[\r\n\t]+/gu, " ").replace(/\s{2,}/gu, " ").trim();
  if (normalized.length <= maximum) return normalized;
  return `${normalized.slice(0, Math.max(0, maximum - 1)).trimEnd()}…`;
}

export function publicCaptureError(error: unknown): PublicCaptureError {
  if (error instanceof CaptureError) {
    return {
      category: boundedText(error.category, 64),
      message: boundedText(error.publicMessage),
    };
  }
  return {
    category: "capture_failed",
    message: "Capture failed locally: extraction could not be completed",
  };
}
