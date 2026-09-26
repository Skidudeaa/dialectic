// Shared browser harness for the lead-owned visual acceptance checks.
//
// WHAT: builds this checkout's PWA (`npm run build`: tsc -b, vite build and
// the lazy-Cesium gate) and opens its pages in headless Chromium. Static
// assets come from this checkout's dist/. Every API GET is replayed from HAR
// fixtures recorded read-only from production at a fixed clock
// (2026-09-26T06:00:00Z); every other request is 403/404 and every WebSocket
// is refused, so the app renders its offline state deterministically and
// nothing leaves the machine.
//
// WHY fixtures live outside the tree: they hold the owners' real room
// content. Their sha256 is pinned in fixtures.sha256.json, so a changed
// fixture fails setup instead of silently changing the verdict.
'use strict'
const { spawnSync } = require('node:child_process')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

const APP = path.resolve(__dirname, '..', '..')
const FIXTURES = '/root/scratch/20260926-qol/fixtures'
const HAR_SHA256 = require('./fixtures.sha256.json')
const PLAYWRIGHT = '/root/somaNotes/node_modules/playwright'
const CHROME = '/root/.cache/ms-playwright/chromium-1200/chrome-linux64/chrome'
const ORIGIN = 'https://dialectic.somacura.org'
const CLOCK = Date.parse('2026-09-26T06:00:00Z')
const AMO = 'de883378-a6ef-4af0-a8bc-462265ca7a54'
const HOME = 'be169da1-4b26-4c87-b602-925bef066139'
const HORMUZ = '56ba2f1e-5c70-4290-a77d-52404f0095da'
const ALIEN = 'd428ffef-1902-4f22-9771-5b5765aa73bb'
const ALIEN_THREAD = '52bbd568-e947-4186-ac30-4168d447e197'

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 }, touch: false },
  tablet: { viewport: { width: 834, height: 1194 }, touch: true },
  phone: { viewport: { width: 390, height: 844 }, touch: true },
}

const MIME = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.woff2': 'font/woff2', '.svg': 'image/svg+xml', '.png': 'image/png', '.txt': 'text/plain', '.wasm': 'application/wasm' }

function setupFailure(msg) { console.error(`SETUP FAILURE: ${msg}`); process.exit(2) }

function verifyFixtures() {
  for (const [name, want] of Object.entries(HAR_SHA256)) {
    const file = path.join(FIXTURES, name)
    if (!fs.existsSync(file)) setupFailure(`missing fixture ${file}`)
    const got = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
    if (got !== want) setupFailure(`fixture ${name} sha256 ${got} != pinned ${want}`)
  }
}

function build() {
  const r = spawnSync('npm', ['run', 'build'], { cwd: APP, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout: 600_000 })
  if (r.status !== 0) {
    console.error(r.stdout.slice(-4000)); console.error(r.stderr.slice(-4000))
    console.error('FAILURE: npm run build failed')
    process.exit(1)
  }
  return path.join(APP, 'dist')
}

// `--dist <dir>` skips the build (lead iteration only; the pinned argv never
// passes it). `--only a,b` limits pages. VI_SHOTS=<dir> saves screenshots.
function parseArgs() {
  const args = process.argv.slice(2)
  const val = (flag) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : null }
  return { dist: val('--dist'), only: val('--only') ? val('--only').split(',') : null }
}

// Opens every (viewport, page) pair and calls `inspect(page, viewportName, pg)`
// after the page settles; collects page errors. Returns rows of
// {viewport, page, errors, result}.
async function visitAll(pages, inspect) {
  const opts = parseArgs()
  verifyFixtures()
  const dist = opts.dist ? path.resolve(opts.dist) : build()
  if (!fs.existsSync(path.join(dist, 'index.html'))) setupFailure(`no index.html in ${dist}`)
  const { chromium } = require(PLAYWRIGHT)
  const browser = await chromium.launch({ headless: true, executablePath: CHROME, args: ['--disable-gpu'] })
  const state = {
    user: { id: AMO, display_name: 'Amo' }, accessToken: 'fixture-token', refreshToken: null, isAuthenticated: true,
    currentRoom: { id: HOME, name: 'Home', token: 'fixture-room-token', is_home: true }, roomToken: 'fixture-room-token',
  }
  const rows = []
  for (const [vname, vp] of Object.entries(VIEWPORTS)) {
    const context = await browser.newContext({ viewport: vp.viewport, hasTouch: vp.touch, isMobile: vp.touch, colorScheme: 'dark', serviceWorkers: 'block', reducedMotion: 'reduce' })
    await context.addInitScript((s) => { localStorage.setItem('dialectic-auth', JSON.stringify({ state: s, version: 0 })) }, state)
    await context.routeWebSocket(/.*/, (ws) => ws.close())
    // Routes run last-registered-first: static dist -> HAR replay -> 404.
    await context.route('**/*', (route) => route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"not in fixture"}' }))
    await context.routeFromHAR(path.join(FIXTURES, `${vname}.har`), { notFound: 'fallback' })
    await context.route('**/*', (route) => {
      const req = route.request(); const url = new URL(req.url())
      if (url.origin !== ORIGIN) return route.fulfill({ status: 404, body: '' })
      if (!['GET', 'HEAD'].includes(req.method())) return route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"read-only fixture"}' })
      const p = url.pathname === '/' ? '/index.html' : url.pathname
      if (p === '/index.html' || /^\/(assets|fonts|icons|cesium)\//.test(p) || ['/sw.js', '/manifest.webmanifest', '/registerSW.js'].includes(p) || /^\/workbox-[\w-]+\.js$/.test(p)) {
        const local = path.join(dist, p)
        if (!local.startsWith(dist) || !fs.existsSync(local) || !fs.statSync(local).isFile()) return route.fulfill({ status: 404, body: '' })
        return route.fulfill({ status: 200, contentType: MIME[path.extname(local)] || 'application/octet-stream', body: fs.readFileSync(local) })
      }
      return route.fallback()
    })
    for (const pg of pages) {
      if (opts.only && !opts.only.includes(pg.name)) continue
      const page = await context.newPage()
      const errors = []
      page.on('pageerror', (e) => errors.push(e.message.slice(0, 300)))
      await page.clock.setFixedTime(CLOCK)
      let result = null
      try {
        await page.goto(ORIGIN + pg.url, { waitUntil: 'networkidle', timeout: 60_000 })
        await page.waitForTimeout(2500)
        result = await inspect(page, vname, pg)
        if (process.env.VI_SHOTS) await page.screenshot({ path: path.join(process.env.VI_SHOTS, `${vname}-${pg.name}.png`) })
      } catch (e) {
        errors.push(`navigation/inspect: ${String(e.message || e).slice(0, 300)}`)
      }
      rows.push({ viewport: vname, page: pg.name, errors, result })
      await page.close()
    }
    await context.close()
  }
  await browser.close()
  return rows
}

// Prints one line per page plus its failures; exits 1 if any page failed.
function report(label, rows) {
  let bad = 0
  for (const r of rows) {
    const f = r.failures
    console.log(`${f.length ? 'FAIL' : 'ok  '} ${r.viewport.padEnd(7)} ${r.page.padEnd(15)} ${r.note || ''} failures=${f.length}`)
    for (const x of f) console.log(`       - ${x}`)
    if (f.length) bad++
  }
  if (!rows.length) { console.log(`${label} FAILURE: no pages were checked`); process.exit(1) }
  console.log(bad ? `${label} FAILURE: ${bad}/${rows.length} pages fail` : `${label} PASS: ${rows.length} pages`)
  process.exit(bad ? 1 : 0)
}

module.exports = { visitAll, report, HORMUZ, ALIEN, ALIEN_THREAD }
