import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { JSDOM } from "jsdom";

const testRoot = path.dirname(fileURLToPath(import.meta.url));

export async function fixtureDOM(name: string, url = "https://fixture.test/story"): Promise<JSDOM> {
  const html = await readFile(path.join(testRoot, "fixtures", name), "utf8");
  return new JSDOM(html, { url });
}

export function installDOMGlobals(dom: JSDOM): () => void {
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, "document");
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "document", {
    configurable: true,
    value: dom.window.document,
  });
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: dom.window,
  });
  return () => {
    if (previousDocument) Object.defineProperty(globalThis, "document", previousDocument);
    else Reflect.deleteProperty(globalThis, "document");
    if (previousWindow) Object.defineProperty(globalThis, "window", previousWindow);
    else Reflect.deleteProperty(globalThis, "window");
  };
}
