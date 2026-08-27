import type { WorldShader } from './contract.ts'
import { retroShader } from './retro.ts'
import { nightVisionShader } from './surveillance.ts'
import { thermalShader } from './thermal.ts'
import { noirShader } from './noir.ts'
import { snowShader } from './snow.ts'
import { animeShader } from './anime.ts'

/** The sensor looks, in keyboard order. `none` is the absence of a stage, not
 *  a stage at zero — index 0 is the natural globe. */
export const WORLD_STYLES = [
  { key: 'none', label: 'Natural', shader: null },
  { key: 'retro', label: 'CRT', shader: retroShader },
  { key: 'surveillance', label: 'Night vision', shader: nightVisionShader },
  { key: 'thermal', label: 'FLIR / thermal', shader: thermalShader },
  { key: 'noir', label: 'Noir', shader: noirShader },
  { key: 'snow', label: 'Snow', shader: snowShader },
  { key: 'anime', label: 'Illustrated', shader: animeShader },
] as const

export type WorldStyleKey = (typeof WORLD_STYLES)[number]['key']
export const WORLD_STYLE_KEYS = WORLD_STYLES.map((s) => s.key) as readonly WorldStyleKey[]

export function isWorldStyle(value: string | null | undefined): value is WorldStyleKey {
  return typeof value === 'string' && (WORLD_STYLE_KEYS as readonly string[]).includes(value)
}

/** Which style a keystroke selects, or null for every key that selects none.
 *
 * ONLY A SINGLE ASCII DIGIT COUNTS. `Number(' ')` is 0, not NaN, so a guard
 * built on `Number.isInteger(Number(key))` accepts the Space bar as style 0 —
 * and Space is how a person scrolls the list under the globe, so their chosen
 * optics would silently revert to Natural while they read. The digit test is
 * the guard; the conversion happens only after it passes.
 *
 * `available` is what this GPU actually compiled, so a shader that failed to
 * build cannot be selected by keyboard either.
 */
export function styleForKey(
  key: string, available: readonly WorldStyleKey[],
): WorldStyleKey | null {
  if (!/^[0-9]$/.test(key)) return null
  const index = Number(key)
  if (index >= WORLD_STYLES.length) return null
  const style = WORLD_STYLES[index].key
  return available.includes(style) ? style : null
}

export type { WorldShader }
