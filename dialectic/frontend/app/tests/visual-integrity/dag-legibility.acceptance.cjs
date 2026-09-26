#!/usr/bin/env node
// Thesis graph legibility acceptance -- lead-owned, pinned before
// implementation.
//
// The Bench draws the room's causal thesis graph (ThesisDag). On production
// data (19 nodes, 16 edges) at 1440x900 its node names render at ~6px and its
// edge labels pile onto each other and onto nodes. On the Hormuz Bench at a
// desktop (1440x900), tablet (834x1194, touch) and phone (390x844, touch)
// viewport, after the page settles and with no user interaction:
//   1. no uncaught page error and no horizontal page overflow;
//   2. exactly one graph (svg.thesis-dag-svg) showing all 19 node names
//      (.thesis-dag-node-label), each name's full text or a visible
//      ellipsized prefix of it;
//   3. every node name renders at >= 11px effective size on desktop and
//      tablet, >= 10px on phone (computed font-size x the SVG's screen scale);
//      every other displayed graph text at >= 9px;
//   4. on desktop and tablet every node name lies entirely inside the graph's
//      visible box -- the whole graph is readable without panning or zooming;
//   5. no two displayed graph texts overlap (>= 3px wide and >= 40% of the
//      shorter height), and no text outside a node overlaps that node's box.
// "Displayed" = rendered with non-zero size, visible and not transparent, and
// inside the graph's visible box. Text that appears only on hover, focus or
// selection is allowed, since this check never interacts.
// Harness and fixtures: ./harness.cjs.
//
// Usage: node tests/visual-integrity/dag-legibility.acceptance.cjs
'use strict'
const { visitAll, report, HORMUZ } = require('./harness.cjs')

const NODE_COUNT = 19
const PAGES = [{ name: 'hormuz-bench', url: `/?room=${HORMUZ}&scene=bench` }]

// Runs inside the page.
function measure() {
  const svgs = [...document.querySelectorAll('svg.thesis-dag-svg')].filter((s) => s.getClientRects().length > 0)
  if (svgs.length !== 1) return { svgCount: svgs.length }
  const svg = svgs[0]
  const sr = svg.getBoundingClientRect()
  const vis = { l: sr.left, t: sr.top, r: sr.right, b: sr.bottom }
  const inter = (a, b) => ({ l: Math.max(a.l, b.l), t: Math.max(a.t, b.t), r: Math.min(a.r, b.r), b: Math.min(a.b, b.b) })
  const box = (el) => { const r = el.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom } }
  const shown = (el) => {
    if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false
    const b = box(el)
    if (b.r - b.l < 1 || b.b - b.t < 1) return false
    const v = inter(b, vis)
    return v.r - v.l >= 1 && v.b - v.t >= 1
  }
  const px = (t) => parseFloat(getComputedStyle(t).fontSize) * Math.abs(t.getScreenCTM().a)
  const labels = [...svg.querySelectorAll('.thesis-dag-node-label')]
  const texts = [...svg.querySelectorAll('text')].filter((t) => t.textContent.trim() && shown(t))
  const nodeOf = (el) => el.closest('.thesis-dag-node')
  const nodes = [...svg.querySelectorAll('.thesis-dag-node')].filter(shown)
  const overlaps = []
  for (let i = 0; i < texts.length; i++) {
    for (let j = i + 1; j < texts.length; j++) {
      const x = inter(inter(box(texts[i]), box(texts[j])), vis)
      const w = x.r - x.l, h = x.b - x.t
      const minH = Math.min(box(texts[i]).b - box(texts[i]).t, box(texts[j]).b - box(texts[j]).t)
      if (w >= 3 && h >= 0.4 * minH) overlaps.push(`text "${texts[i].textContent.trim().slice(0, 30)}" x "${texts[j].textContent.trim().slice(0, 30)}"`)
    }
  }
  for (const t of texts) {
    for (const n of nodes) {
      if (nodeOf(t) === n) continue
      const rect = n.querySelector('.thesis-dag-node-rect') || n
      const x = inter(inter(box(t), box(rect)), vis)
      if (x.r - x.l >= 3 && x.b - x.t >= 3) overlaps.push(`text "${t.textContent.trim().slice(0, 30)}" over node "${(n.querySelector('.thesis-dag-node-label') || n).textContent.trim().slice(0, 30)}"`)
    }
  }
  return {
    svgCount: 1,
    svgBox: [sr.width, sr.height].map(Math.round),
    labels: labels.map((l) => ({ text: l.textContent.trim(), shown: shown(l), px: px(l), inside: (() => { const b = box(l); return b.l >= vis.l - 0.5 && b.r <= vis.r + 0.5 && b.t >= vis.t - 0.5 && b.b <= vis.b + 0.5 })() })),
    smallText: texts.filter((t) => !t.classList.contains('thesis-dag-node-label') && px(t) < 9).map((t) => `"${t.textContent.trim().slice(0, 30)}" ${px(t).toFixed(1)}px`),
    overlaps,
    overflowX: document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth,
  }
}

async function main() {
  const rows = await visitAll(PAGES, (page) => page.evaluate(measure))
  for (const r of rows) {
    const m = r.result
    const failures = r.errors.map((e) => `page error: ${e}`)
    if (!m) { if (!failures.length) failures.push('page produced no measurement'); r.failures = failures; continue }
    if (m.svgCount !== 1) { failures.push(`expected exactly one rendered thesis graph, found ${m.svgCount}`); r.failures = failures; continue }
    if (m.overflowX > 1) failures.push(`horizontal overflow ${m.overflowX}px`)
    const minPx = r.viewport === 'phone' ? 10 : 11
    if (m.labels.length !== NODE_COUNT) failures.push(`expected ${NODE_COUNT} node names, found ${m.labels.length}`)
    for (const l of m.labels) {
      if (!l.shown) failures.push(`node name not displayed: "${l.text}"`)
      else if (l.px < minPx) failures.push(`node name "${l.text}" renders at ${l.px.toFixed(1)}px (< ${minPx}px)`)
      if (r.viewport !== 'phone' && !l.inside) failures.push(`node name "${l.text}" is not entirely inside the graph's visible box`)
    }
    for (const s of m.smallText) failures.push(`graph text below 9px: ${s}`)
    failures.push(...m.overlaps)
    r.failures = failures
    r.note = `svg=${m.svgBox.join('x')} names=${m.labels.length} min=${Math.min(...m.labels.map((l) => l.px)).toFixed(1)}px`
  }
  report('DAG-LEGIBILITY', rows)
}

main().catch((e) => { console.error(e); process.exit(2) })
