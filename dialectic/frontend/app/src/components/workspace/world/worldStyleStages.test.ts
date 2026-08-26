import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import type * as Cesium from 'cesium'
import { WorldStyles } from './worldStyleStages.ts'

/** A viewer just real enough for the stage manager: it collects the stages
 *  added to it and counts the renders it was asked for. */
/** Only what the stage manager touches. */
interface FakeStage {
  name: string
  enabled: boolean
  uniforms: Record<string, number | undefined>
}

function fakeViewer() {
  const stages: FakeStage[] = []
  const scene = {
    postProcessStages: {
      add: (stage: FakeStage) => { stages.push(stage); return stage },
      remove: (stage: FakeStage) => {
        const at = stages.indexOf(stage)
        if (at >= 0) stages.splice(at, 1)
      },
    },
    requestRender: vi.fn(),
  }
  const viewer = { scene, isDestroyed: () => false } as unknown as Cesium.Viewer
  return { viewer, stages, scene }
}

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1))
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
})
afterEach(() => vi.unstubAllGlobals())

describe('WorldStyles', () => {
  it('registers one disabled stage per shader and offers them all', () => {
    const { viewer, stages } = fakeViewer()
    const styles = new WorldStyles(viewer)
    expect(stages.length).toBe(6)  // every look but `none`
    expect(stages.every((s) => s.enabled === false)).toBe(true)
    expect(styles.available()).toContain('none')
    expect(styles.available()).toContain('thermal')
    styles.destroy()
    expect(stages.length).toBe(0)
  })

  it('keeps enabled and intensity in lockstep — a zero stage is off', () => {
    const { viewer, stages } = fakeViewer()
    const styles = new WorldStyles(viewer)
    styles.setStyle('thermal')

    const thermal = stages.find((s) => s.name === 'dialecticWorld_thermal') as FakeStage
    expect(thermal.enabled).toBe(true)
    expect(thermal.uniforms.intensity).toBe(1)
    // Every other stage must be BOTH zero and disabled: a zero-intensity
    // stage still costs a full-screen pass if it stays enabled.
    for (const other of stages.filter((s) => s !== thermal)) {
      expect(other.uniforms.intensity).toBe(0)
      expect(other.enabled).toBe(false)
    }

    styles.setStyle('none')
    expect(stages.every((s) => s.enabled === false)).toBe(true)
    styles.destroy()
  })

  it('starts the clock only for a visible animated shader, and stops it', () => {
    const { viewer } = fakeViewer()
    const styles = new WorldStyles(viewer)

    styles.setStyle('retro')  // CRT declares `uniform float time`
    expect(requestAnimationFrame).toHaveBeenCalled()

    vi.mocked(cancelAnimationFrame).mockClear()
    styles.setStyle('none')
    expect(cancelAnimationFrame).toHaveBeenCalled()
    styles.destroy()
  })

  it('never starts the clock for a reduced-motion viewer', () => {
    const { viewer } = fakeViewer()
    const styles = new WorldStyles(viewer, { reducedMotion: true })
    styles.setStyle('retro')
    expect(requestAnimationFrame).not.toHaveBeenCalled()
    // The still look is still applied — only the animation is withheld.
    expect(styles.style()).toBe('retro')
    styles.destroy()
  })

  it('drops a stage the scene refuses instead of losing the globe', () => {
    const { viewer, stages } = fakeViewer()
    const scene = viewer.scene as unknown as {
      postProcessStages: { add: (stage: FakeStage) => FakeStage }
    }
    const add = scene.postProcessStages.add
    scene.postProcessStages.add = (stage: FakeStage) => {
      if (stage.name === 'dialecticWorld_thermal') throw new Error('compile failed')
      return add(stage)
    }
    const styles = new WorldStyles(viewer)
    expect(stages.length).toBe(5)
    expect(styles.available()).not.toContain('thermal')
    // The other five looks, and the natural globe, are untouched.
    expect(styles.available()).toContain('retro')
    expect(styles.available()).toContain('none')
    styles.destroy()
  })
})
