import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const dist = new URL('../dist/', import.meta.url)
const html = await readFile(new URL('index.html', dist), 'utf8')

if (/<link\s+rel="modulepreload"[^>]+cesium-/i.test(html)) {
  throw new Error('Cesium must not be module-preloaded by the application shell')
}

const entryPath = html.match(/<script\s+type="module"[^>]+src="([^"]+)"/i)?.[1]
if (!entryPath) throw new Error('Production index does not name its module entry')

const entry = await readFile(new URL(entryPath.replace(/^\//, ''), dist), 'utf8')
if (/\bfrom\s*["']\.\/cesium-[^"']+["']/.test(entry)) {
  throw new Error('Application entry must not statically import the Cesium chunk')
}

const worker = await readFile(new URL('sw.js', dist), 'utf8')
if (/"url":"assets\/(?:WorldView|cesium)-[^"]+\.(?:js|css)"/.test(worker)) {
  throw new Error('The service worker must not precache the lazy World dependency graph')
}

console.log(`Lazy Cesium contract passed for ${fileURLToPath(new URL(entryPath.replace(/^\//, ''), dist))}`)
