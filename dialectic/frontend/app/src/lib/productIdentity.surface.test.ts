import { describe, expect, it } from 'vitest'

/**
 * The regression fence for the identity pass.
 *
 * Task Group A5 established Dialectic as the one visible participant name, but
 * the rename reached only the surfaces someone happened to open. THREE separate
 * copies of the speaker-name mapping (MessageList, SearchOverlay, useAwayAlerts)
 * kept returning a provider name for provoker and annotator turns, and a dozen
 * pieces of copy — the composer placeholder, the room settings, the trading
 * panel, the memory panel, the help modal — still named the provider outright.
 *
 * WHY a source scan rather than a render assertion: a per-component test fences
 * only the components someone thought to write a test for, and this defect is
 * defined by the ones nobody did.
 *
 * WHY import.meta.glob rather than node:fs: the app builds with
 * `types: ["vite/client"]` and no node types, on purpose — browser code has no
 * business reaching the filesystem. Using node:fs here type-checked fine under
 * vitest and broke `tsc -b`, which is the A2 failure mode exactly: tests and
 * lint green, build red. This form is typed by vite/client, needs no cwd
 * anchor, and cannot drift from where the files actually are.
 *
 * The scan's two failure modes are both mutation-checked below: that it might
 * miss a real provider name in copy, and that it might flag a comment ABOUT the
 * rename. Verified in both directions against the real files.
 *
 * DELIBERATELY ALLOWED:
 *   @Claude    a documented compatibility summon alias (A5 keeps it working)
 *   isClaude   an internal prop name; Release 1 explicitly did not rename it
 *   is-claude  a CSS compatibility class name, same reason
 */

const sources = import.meta.glob('../**/*.{ts,tsx}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const ALLOWED = /(@Claude|isClaude|is-claude)/g

/** Remove block and line comments so prose ABOUT the rename cannot fail this. */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
}

function offendingLines(source: string): string[] {
  return stripComments(source)
    .split('\n')
    .filter((line) => /\bClaude\b/.test(line.replace(ALLOWED, '')))
    .map((line) => line.trim())
}

describe('no surface names the provider', () => {
  it('holds across every non-test source file', () => {
    const offenders: Record<string, string[]> = {}
    for (const [path, source] of Object.entries(sources)) {
      if (/\.test\.tsx?$/.test(path)) continue
      const lines = offendingLines(source)
      if (lines.length) offenders[path] = lines
    }
    expect(offenders).toEqual({})
  })

  it('is scanning a real, non-trivial set of files', () => {
    // Guards the whole fence against silently matching nothing: a bad glob
    // would make the assertion above pass on an empty map forever.
    const scanned = Object.keys(sources).filter((p) => !/\.test\.tsx?$/.test(p))
    expect(scanned.length).toBeGreaterThan(30)
    expect(scanned.some((p) => p.includes('components/chat/MessageInput'))).toBe(true)
  })

  it('detects a provider name in copy, and spares comments and aliases', () => {
    expect(offendingLines('const p = "ask Claude about it"')).toHaveLength(1)
    expect(offendingLines('// Claude used to be named here')).toHaveLength(0)
    expect(offendingLines('/* renamed from Claude */')).toHaveLength(0)
    expect(offendingLines('say @Claude to summon')).toHaveLength(0)
    expect(offendingLines('p.isClaude ? a : b')).toHaveLength(0)
  })
})
