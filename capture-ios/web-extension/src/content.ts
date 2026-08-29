import { installContentController, type ContentRuntime } from "./content-controller";

declare const browser: { runtime: ContentRuntime };

const installationKey = "__somacuraCaptureContentInstalled";
const scope = globalThis as typeof globalThis & Record<string, unknown>;
if (!scope[installationKey]) {
  installContentController(browser.runtime, document);
  scope[installationKey] = true;
}
