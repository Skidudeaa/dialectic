// Generates the PWA icon set from an inline SVG mark.
// Run: node scripts/generate-icons.mjs   (writes into public/icons/)
//
// The mark: two facing angle brackets (the two humans) around a lit diamond
// (the LLM spark), amber on void — matches the app's token palette.
import sharp from 'sharp'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const outDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'icons')
mkdirSync(outDir, { recursive: true })

const VOID = '#120C06'
const AMBER = '#E69A4C'
const AMBER_HOT = '#F0B269'

// `pad` shrinks the mark toward center — maskable icons need the mark inside
// the central 80% safe zone so launcher shapes don't clip it.
function markSvg(pad = 0) {
  const s = 1 - pad * 2
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <rect width="512" height="512" fill="${VOID}"/>
  <radialGradient id="glow" cx="50%" cy="38%" r="70%">
    <stop offset="0%" stop-color="${AMBER}" stop-opacity="0.10"/>
    <stop offset="100%" stop-color="${AMBER}" stop-opacity="0"/>
  </radialGradient>
  <rect width="512" height="512" fill="url(#glow)"/>
  <g transform="translate(${256 - 256 * s}, ${256 - 256 * s}) scale(${s})" transform-origin="256 256">
    <path d="M206 150 L114 256 L206 362" stroke="${AMBER}" stroke-width="36" fill="none" stroke-linecap="square"/>
    <path d="M306 150 L398 256 L306 362" stroke="${AMBER}" stroke-width="36" fill="none" stroke-linecap="square"/>
    <rect x="256" y="256" width="52" height="52" fill="${AMBER_HOT}" transform="rotate(45 256 256) translate(-26 -26)"/>
  </g>
</svg>`
}

const targets = [
  { file: 'pwa-192.png', size: 192, pad: 0.04 },
  { file: 'pwa-512.png', size: 512, pad: 0.04 },
  { file: 'pwa-maskable-512.png', size: 512, pad: 0.14 },
  { file: 'apple-touch-icon.png', size: 180, pad: 0.06 },
]

for (const { file, size, pad } of targets) {
  await sharp(Buffer.from(markSvg(pad))).resize(size, size).png().toFile(join(outDir, file))
  console.log(`wrote ${file}`)
}

writeFileSync(join(outDir, 'favicon.svg'), markSvg(0.02))
console.log('wrote favicon.svg')
