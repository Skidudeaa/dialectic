import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SceneMasthead } from './SceneMasthead'
import { SCENE_HINTS, SCENE_PRIMER } from './sceneIdentity'
import { IMPLEMENTED_WORKSPACE_SCENES } from '../../types/workspace.ts'

/**
 * The masthead's job doubled on 2026-08-21: it still says WHERE you are, and
 * now also answers WHAT YOU DO HERE — behind a disclosure, so a returning user
 * is not re-taught on every scene switch.
 *
 * What can actually break here, in order of cost:
 *  1. The primer opening on one scene and staying open on the next, because
 *     `<details open>` is DOM state React does not own. That silently pushes
 *     the transcript down on Record forever after — the exact thing the
 *     compact variant exists to prevent.
 *  2. The closed state costing a line. The compact contract is that Record and
 *     House get ONE quiet row; if the affordance is not inside the summary
 *     that already carries the name, the row count is two.
 *  3. A scene added to the union with no primer. Totality is a build error,
 *     not a runtime blank — but only if nothing widens the type.
 */

/** The <details> the masthead wraps everything in. */
function disclosure(): HTMLDetailsElement {
  const el = document.querySelector('details.scene-masthead-primer')
  if (!el) throw new Error('the masthead is not a disclosure any more')
  return el as HTMLDetailsElement
}

describe('SceneMasthead', () => {
  it('names the place and states its purpose without being opened', () => {
    render(<SceneMasthead scene="ledger" />)
    expect(screen.getByRole('heading', { name: 'Ledger' })).toBeInTheDocument()
    expect(screen.getByText(SCENE_HINTS.ledger)).toBeInTheDocument()
  })

  it('keeps the primer closed until asked, on every scene', () => {
    for (const scene of IMPLEMENTED_WORKSPACE_SCENES) {
      const { unmount } = render(<SceneMasthead scene={scene} />)
      expect(disclosure().open).toBe(false)
      // Present in the DOM and not shown: jest-dom knows a closed <details>
      // hides its body, so this is a real visibility assertion.
      expect(screen.getByText(SCENE_PRIMER[scene])).not.toBeVisible()
      unmount()
    }
  })

  it('shows the primer once opened', () => {
    render(<SceneMasthead scene="field" />)
    fireEvent.click(screen.getByText('What is this?'))
    // jsdom does not implement summary's activation behaviour, so drive the
    // state the platform would. What is under test is the RENDER of the open
    // state, not the browser's toggle.
    disclosure().open = true
    expect(screen.getByText(SCENE_PRIMER.field)).toBeVisible()
  })

  it('closes again when the scene changes', () => {
    // The regression that costs the most: `open` is DOM state React does not
    // own, so without a per-scene key the node is reused and the next scene
    // opens already-taught. On Record that permanently shortens the transcript.
    const { rerender } = render(<SceneMasthead scene="field" />)
    disclosure().open = true
    expect(screen.getByText(SCENE_PRIMER.field)).toBeVisible()

    rerender(<SceneMasthead scene="ledger" />)
    expect(disclosure().open).toBe(false)
    expect(screen.getByText(SCENE_PRIMER.ledger)).not.toBeVisible()
  })

  it('puts the affordance INSIDE the row that already carries the name', () => {
    // The compact contract (Record, House): one quiet line. The trigger may
    // not be a second row of its own — so the summary has to be the masthead
    // row itself, name and all.
    render(<SceneMasthead scene="record" />)
    const summary = document.querySelector('summary.scene-masthead-inner')
    expect(summary).not.toBeNull()
    expect(summary).toContainElement(screen.getByRole('heading', { name: 'Record' }))
    expect(summary).toContainElement(screen.getByText('What is this?'))
  })

  it('keeps the compact variant on the transcript scenes only', () => {
    for (const scene of IMPLEMENTED_WORKSPACE_SCENES) {
      const { container, unmount } = render(<SceneMasthead scene={scene} />)
      const header = container.querySelector('.scene-masthead')
      const isCompact = header?.classList.contains('scene-masthead-compact')
      expect(isCompact).toBe(scene === 'record' || scene === 'house')
      unmount()
    }
  })
})

describe('SCENE_PRIMER', () => {
  it('names every implemented scene — a blank primer is a build error, not a blank panel', () => {
    for (const scene of IMPLEMENTED_WORKSPACE_SCENES) {
      expect(SCENE_PRIMER[scene], `no primer for ${scene}`).toBeTruthy()
    }
    expect(Object.keys(SCENE_PRIMER).sort()).toEqual([...IMPLEMENTED_WORKSPACE_SCENES].sort())
  })

  it('answers more than the one-clause hint already does', () => {
    for (const scene of IMPLEMENTED_WORKSPACE_SCENES) {
      const primer = SCENE_PRIMER[scene]
      // Two sentences minimum: "what do I DO here" and "what will I find"
      // cannot both fit in one, which is why the hint could not carry this.
      expect(primer.split(/[.?] /).length, `${scene} primer is one clause`)
        .toBeGreaterThanOrEqual(2)
      expect(primer, `${scene} primer merely repeats its hint`).not.toBe(SCENE_HINTS[scene])
    }
  })

  it('carries no deployment state — rules are told, facts are read', () => {
    // The split api/capabilities.py and CapabilityMap.tsx enforce. The help
    // modal's "five live theses" is the scar: authored prose that claimed a
    // COUNT drifted away from the running system with no way for a reader to
    // tell. A digit in this table is that mistake starting again.
    for (const scene of IMPLEMENTED_WORKSPACE_SCENES) {
      expect(SCENE_PRIMER[scene], `${scene} primer states a number`).not.toMatch(/\d/)
    }
  })
})
