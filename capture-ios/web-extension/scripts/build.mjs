import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { build } from "esbuild";
import sharp from "sharp";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const iconSource = path.join(root, "public/icons/icon.svg");
const unresolvedNativeIdentifier = "__SOMACURA_NATIVE_APPLICATION_IDENTIFIER__";
const configuredNativeIdentifier = process.env.SOMACURA_NATIVE_APPLICATION_IDENTIFIER?.trim();
if (configuredNativeIdentifier
    && !/^[A-Za-z0-9][A-Za-z0-9.-]{2,254}$/u.test(configuredNativeIdentifier)) {
  throw new Error("SOMACURA_NATIVE_APPLICATION_IDENTIFIER is not a valid bundle identifier");
}
const nativeApplicationIdentifier = configuredNativeIdentifier || unresolvedNativeIdentifier;
const define = {
  __SOMACURA_NATIVE_APPLICATION_IDENTIFIER_BUILD__: JSON.stringify(nativeApplicationIdentifier),
};

await rm(dist, { recursive: true, force: true });
await mkdir(path.join(dist, "icons"), { recursive: true });

await Promise.all([
  build({
    entryPoints: [path.join(root, "src/background.ts")],
    outfile: path.join(dist, "background.js"),
    bundle: true,
    format: "iife",
    platform: "browser",
    target: ["safari18"],
    legalComments: "eof",
    minifySyntax: true,
    define,
  }),
  build({
    entryPoints: [path.join(root, "src/content.ts")],
    outfile: path.join(dist, "content.js"),
    bundle: true,
    format: "iife",
    platform: "browser",
    target: ["safari18"],
    legalComments: "eof",
    minifySyntax: true,
    define,
  }),
  cp(path.join(root, "public/manifest.json"), path.join(dist, "manifest.json")),
]);

for (const output of ["background.js", "content.js"]) {
  const outputPath = path.join(dist, output);
  const source = await readFile(outputPath, "utf8");
  await writeFile(outputPath, source.replace(/[\t ]+$/gmu, ""));
}

const svg = await readFile(iconSource);
await Promise.all([16, 32, 48, 128].map(async (size) => {
  const png = await sharp(svg).resize(size, size).png().toBuffer();
  await writeFile(path.join(dist, `icons/${size}.png`), png);
}));

console.log(`Built Safari WebExtension at ${dist}`);
console.log(`Native application identifier: ${nativeApplicationIdentifier}`);
