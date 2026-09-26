#!/usr/bin/env node
// Visual integrity acceptance -- lead-owned, pinned before implementation.
//
// On Home and room scenes at a desktop (1440x900), tablet (834x1194, touch)
// and phone (390x844, touch) viewport, every page must show:
//   1. no uncaught page error;
//   2. no horizontal page overflow;
//   3. no two visible HTML text runs overlapping. A run is a text line box,
//      measured after clipping by every overflow-clipping ancestor (itself
//      included) and the viewport. Collision = >= 3px horizontal overlap and
//      >= 40% of the shorter line's height. SVG text and aria-hidden
//      decoration are out of scope here (the thesis graph has its own check);
//   4. no raw participant ids (llm_primary / llm_provoker / llm_annotator);
//   5. its key content, by name -- hiding content is not a fix for it
//      overlapping something.
// Harness and fixtures: ./harness.cjs.
//
// Usage: node tests/visual-integrity/visual-integrity.acceptance.cjs
'use strict'
const { visitAll, report, HORMUZ, ALIEN, ALIEN_THREAD } = require('./harness.cjs')

// Key content: case-insensitive, whitespace-collapsed substrings of
// document.body.innerText.
const PAGES = [
  { name: 'home-house', url: '/', keys: ['No open question waits on you', 'Nothing pending', 'Morning brief'] },
  { name: 'home-atlas', url: '/?scene=atlas', keys: ['Persian Gulf', 'Hormuz Closure'] },
  { name: 'home-mirror', url: '/?scene=mirror', keys: ['Thinking Style'] },
  { name: 'home-record', url: '/?scene=record', keys: [] },
  { name: 'hormuz-surface', url: `/?room=${HORMUZ}`, keys: ['Iran/Hormuz Thesis', 'BBC326'] },
  { name: 'hormuz-record', url: `/?room=${HORMUZ}&scene=record`, keys: ['Key moments'] },
  { name: 'hormuz-bench', url: `/?room=${HORMUZ}&scene=bench`, keys: ['Hormuz Closure'] },
  { name: 'hormuz-field', url: `/?room=${HORMUZ}&scene=field`, keys: ['Cascade phase-3 amplification claim'] },
  { name: 'hormuz-library', url: `/?room=${HORMUZ}&scene=library`, keys: ['US military strikes Iranian tankers in Strait of Hormuz'] },
  { name: 'hormuz-ledger', url: `/?room=${HORMUZ}&scene=ledger`, keys: ['Track record', 'Phase 3 cascade status'] },
  { name: 'hormuz-atlas', url: `/?room=${HORMUZ}&scene=atlas`, keys: ['Persian Gulf'] },
  { name: 'alien-surface', url: `/?room=${ALIEN}&thread=${ALIEN_THREAD}&scene=surface`, keys: ['An Alien Mind', 'reminds me of a paper from anthropic'] },
]
// Every page keeps the room list.
const COMMON_KEYS = ['Iran/Hormuz Trading Room']

// Runs inside the page.
function measure() {
  const vw = innerWidth, vh = innerHeight
  const inter = (a, b) => ({ l: Math.max(a.l, b.l), t: Math.max(a.t, b.t), r: Math.min(a.r, b.r), b: Math.min(a.b, b.b) })
  const empty = (x) => x.r - x.l < 1 || x.b - x.t < 1
  const clipCache = new Map()
  const clipOf = (el) => {
    if (clipCache.has(el)) return clipCache.get(el)
    let box = { l: 0, t: 0, r: vw, b: vh }
    for (let a = el; a && a !== document.documentElement; a = a.parentElement) {
      const s = getComputedStyle(a)
      if (s.overflowX !== 'visible' || s.overflowY !== 'visible' || s.contain.includes('paint')) {
        const r = a.getBoundingClientRect()
        const bl = parseFloat(s.borderLeftWidth) || 0, bt = parseFloat(s.borderTopWidth) || 0
        const inner = { l: r.left + bl, t: r.top + bt, r: r.left + bl + a.clientWidth, b: r.top + bt + a.clientHeight }
        box = inter(box, {
          l: s.overflowX === 'visible' ? -1e9 : inner.l, r: s.overflowX === 'visible' ? 1e9 : inner.r,
          t: s.overflowY === 'visible' ? -1e9 : inner.t, b: s.overflowY === 'visible' ? 1e9 : inner.b,
        })
      }
      if (s.position === 'fixed') break
    }
    clipCache.set(el, box)
    return box
  }
  const runs = []
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  let n
  while ((n = walker.nextNode())) {
    const text = n.nodeValue.replace(/\s+/g, ' ').trim()
    if (!text) continue
    const el = n.parentElement
    if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'OPTION'].includes(el.tagName)) continue
    if (el.closest('[aria-hidden="true"], svg')) continue
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) continue
    const range = document.createRange(); range.selectNodeContents(n)
    const clip = clipOf(el)
    for (const rc of range.getClientRects()) {
      if (rc.width < 2 || rc.height < 4) continue
      const v = inter({ l: rc.left, t: rc.top, r: rc.right, b: rc.bottom }, clip)
      if (empty(v)) continue
      runs.push({ node: n, el, box: v, h: rc.height, text: text.slice(0, 48) })
    }
  }
  const sel = (e) => e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '')
  const overlaps = []
  for (let i = 0; i < runs.length; i++) {
    for (let j = i + 1; j < runs.length; j++) {
      const a = runs[i], b = runs[j]
      if (a.node === b.node) continue
      const x = inter(a.box, b.box)
      const w = x.r - x.l, h = x.b - x.t
      if (w >= 3 && h >= 0.4 * Math.min(a.h, b.h)) {
        overlaps.push(`overlap "${a.text}" (${sel(a.el)}) x "${b.text}" (${sel(b.el)}) at ${[x.l, x.t, w, h].map(Math.round).join(',')}`)
      }
    }
  }
  const body = document.body.innerText
  return {
    runs: runs.length,
    overlaps,
    overflowX: document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth,
    rawIds: [...new Set(body.match(/\bllm_(?:primary|provoker|annotator)\b/g) || [])],
    text: body.replace(/\s+/g, ' ').toLowerCase(),
  }
}

async function main() {
  const rows = await visitAll(PAGES, (page) => page.evaluate(measure))
  for (const r of rows) {
    const m = r.result, pg = PAGES.find((p) => p.name === r.page)
    const failures = r.errors.map((e) => `page error: ${e}`)
    if (m) {
      if (m.overflowX > 1) failures.push(`horizontal overflow ${m.overflowX}px`)
      failures.push(...m.overlaps)
      if (m.rawIds.length) failures.push(`raw participant ids on screen: ${m.rawIds.join(', ')}`)
      for (const k of [...COMMON_KEYS, ...pg.keys]) {
        if (!m.text.includes(k.replace(/\s+/g, ' ').toLowerCase())) failures.push(`key content missing: "${k}"`)
      }
    } else if (!failures.length) failures.push('page produced no measurement')
    r.failures = failures
    r.note = m ? `runs=${m.runs}` : ''
  }
  report('VISUAL-INTEGRITY', rows)
}

main().catch((e) => { console.error(e); process.exit(2) })
