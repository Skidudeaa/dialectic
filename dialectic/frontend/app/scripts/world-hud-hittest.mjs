/**
 * World HUD hit test — does a click at the centre of the globe reach the globe?
 *
 * WHY THIS IS NOT A VITEST FILE: jsdom does not lay out or hit test, so
 * `elementFromPoint` there answers from nothing. The defect this guards is
 * purely a compositing question — which painted box receives the pointer —
 * and only a real engine can answer it. This loads the SHIPPED WorldHud.css
 * over the same DOM WorldHud renders and asks the browser directly.
 *
 * Run:  node scripts/world-hud-hittest.mjs
 * Exit: 0 when every probed point reaches its intended surface, 1 otherwise.
 *
 * Puppeteer is resolved from the ambient install rather than added as an app
 * dependency, so this stays out of `npm test` and off the PWA build path.
 */
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CSS = path.join(HERE, '..', 'src', 'components', 'workspace', 'world', 'WorldHud.css')

// The stage as World.css builds it, with the HUD's own DOM inside it.
const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<style>${fs.readFileSync(CSS, 'utf8')}</style>
<style>
  html,body{margin:0}
  .world-stage{position:relative}
  .world-canvas{width:100%;height:640px;background:#123}
</style></head><body>
<div class="world-view" data-style="none"><div class="world-stage">
  <div class="world-canvas" id="globe" aria-label="World globe"></div>
  <div class="world-hud" data-visible="true">
    <div class="hud-reticle" aria-hidden="true"></div>
    <div class="hud-panel hud-layers"><h4>Layers</h4><ul><li><label>
      <input type="checkbox" id="layer"><span class="hud-layer-name">Aircraft</span>
      <span class="hud-count">12</span></label></li></ul></div>
    <div class="hud-panel hud-styles"><h4>Optics</h4><ul><li>
      <button type="button" id="optic">Natural</button></li></ul></div>
    <dl class="hud-panel hud-readout"><div><dt>Lat</dt><dd>26.5</dd></div></dl>
  </div>
</div></div></body></html>`

const { default: puppeteer } = await import('puppeteer')

const server = http.createServer((_req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/html' })
  res.end(PAGE)
})
await new Promise((r) => server.listen(0, '127.0.0.1', r))

const browser = await puppeteer.launch({
  headless: 'new',
  executablePath: process.env.CHROME_BIN || '/usr/bin/google-chrome',
  args: ['--no-sandbox'],
})
try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1280, height: 800 })
  await page.goto(`http://127.0.0.1:${server.address().port}/`, { waitUntil: 'load' })

  const probes = await page.evaluate(() => {
    const box = document.getElementById('globe').getBoundingClientRect()
    const hit = (dx, dy) => {
      const el = document.elementFromPoint(
        box.left + box.width / 2 + dx, box.top + box.height / 2 + dy)
      return el ? (el.className || el.tagName).toString().split(' ')[0] : 'null'
    }
    const controls = (id) => {
      const r = document.getElementById(id).getBoundingClientRect()
      const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
      return el ? el.id || (el.className || el.tagName).toString() : 'null'
    }
    return {
      // The globe must own its own surface, centre included.
      centre: hit(0, 0),
      reticleEdge: hit(0, 30),
      offCentre: hit(120, 0),
      // ...and the HUD's real controls must still be clickable.
      layerCheckbox: controls('layer'),
      opticButton: controls('optic'),
    }
  })

  const expected = {
    centre: 'world-canvas',
    reticleEdge: 'world-canvas',
    offCentre: 'world-canvas',
    layerCheckbox: 'layer',
    opticButton: 'optic',
  }
  let failed = false
  for (const [probe, want] of Object.entries(expected)) {
    const got = probes[probe]
    const ok = got === want
    if (!ok) failed = true
    console.log(`${probe.padEnd(15)} expected=${want.padEnd(14)} got=${got.padEnd(14)} ${ok ? 'ok' : 'FAIL'}`)
  }
  console.log(failed
    ? 'FAIL: the HUD is intercepting input meant for the globe.'
    : 'PASS: the globe owns its surface and the HUD controls remain clickable.')
  process.exitCode = failed ? 1 : 0
} finally {
  await browser.close()
  server.close()
}
