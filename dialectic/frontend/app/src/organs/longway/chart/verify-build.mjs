// A bounded, independent lazy-build proof while the shell is owned elsewhere.
// Does not change the trading entry, its config, or its output directory.
import { build } from 'vite'
import react from '@vitejs/plugin-react'
import { cp, mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join, resolve } from 'node:path'

const here = fileURLToPath(new URL('.', import.meta.url))
const outDir = resolve(process.argv[2] ?? '/tmp/longway-chart-preview')
const result = await build({
  configFile: false, root: join(here, 'preview'), publicDir: false, plugins: [react()],
  build: { outDir, emptyOutDir: true, manifest: true },
})
const outputs = (Array.isArray(result) ? result : [result]).flatMap(r => 'output' in r ? r.output : [])
const chunks = outputs.filter(o => o.type === 'chunk')
const chart = chunks.find(c => Object.keys(c.modules).some(m => m.endsWith('/chart/Chart.tsx')))
if (!chart || chart.isEntry || !chunks.some(c => c.dynamicImports.includes(chart.fileName))) throw new Error('Chart must be a dynamic chunk')
const eager = new Set()
function visit(file) {
  if (eager.has(file)) return
  eager.add(file)
  chunks.find(c => c.fileName === file)?.imports.forEach(visit)
}
chunks.filter(c => c.isEntry).forEach(c => visit(c.fileName))
if (eager.has(chart.fileName)) throw new Error('Chart was imported eagerly')
for (const chunk of chunks) {
  const modules = Object.keys(chunk.modules)
  if (/cesium/i.test(chunk.fileName) || modules.some(m => /node_modules\/(?:@cesium|cesium)\//.test(m))) throw new Error('Chart graph imported Cesium')
  if (eager.has(chunk.fileName) && modules.some(m => m.includes('/node_modules/maplibre-gl/'))) throw new Error('MapLibre was imported eagerly')
  if (modules.some(m => m.endsWith('/land-50m.json'))) throw new Error('Coastlines were bundled')
}
await mkdir(join(outDir, 'longway'), { recursive: true })
await cp(join(here, '../../../../public/longway/land-50m.json'), join(outDir, 'longway/land-50m.json'))
console.log(`Lazy chart contract passed: ${chart.fileName}; preview: ${outDir}/index.html`)
