import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

describe("extension surface", () => {
  it("uses Manifest V3 action semantics without a popup", async () => {
    const manifest = JSON.parse(await readFile(path.join(root, "public/manifest.json"), "utf8")) as {
      manifest_version: number;
      action: Record<string, unknown>;
      background: Record<string, unknown>;
      permissions: string[];
      content_scripts?: unknown;
    };
    expect(manifest.manifest_version).toBe(3);
    expect(manifest.action.default_popup).toBeUndefined();
    expect(manifest.action.default_icon).toBeDefined();
    expect(manifest.background).toEqual({ service_worker: "background.js" });
    expect(manifest.permissions).toEqual(["activeTab", "scripting", "nativeMessaging"]);
    expect(manifest.content_scripts).toBeUndefined();
  });

  it("keeps native messaging in the background module only", async () => {
    const sourceDirectory = path.join(root, "src");
    const sourceFiles = (await readdir(sourceDirectory)).filter((name) => name.endsWith(".ts"));
    const callers: string[] = [];
    for (const file of sourceFiles) {
      const source = await readFile(path.join(sourceDirectory, file), "utf8");
      if (source.includes("sendNativeMessage")) callers.push(file);
    }
    expect(callers).toEqual(["background-controller.ts"]);
  });
});
