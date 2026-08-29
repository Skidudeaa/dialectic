export const CLIENT_VERSION = "0.1.0";
export const DEFUDDLE_VERSION = "0.19.3";
export const MAX_MARKDOWN_BYTES = 2_000_000;
export const MAX_ERROR_MESSAGE_LENGTH = 180;
export const TOAST_HOST_ID = "somacura-capture-status";

declare const __SOMACURA_NATIVE_APPLICATION_IDENTIFIER_BUILD__: string | undefined;

// Replaced by the containing-app integration once its bundle identifier exists.
// The background controller refuses to call native messaging while this sentinel remains.
export const NATIVE_APPLICATION_IDENTIFIER =
  typeof __SOMACURA_NATIVE_APPLICATION_IDENTIFIER_BUILD__ === "string"
    ? __SOMACURA_NATIVE_APPLICATION_IDENTIFIER_BUILD__
    : "__SOMACURA_NATIVE_APPLICATION_IDENTIFIER__";

export function isConfiguredNativeIdentifier(identifier: string): boolean {
  return identifier.length > 0 && !identifier.startsWith("__");
}
