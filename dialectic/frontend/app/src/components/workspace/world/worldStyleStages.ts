import * as Cesium from 'cesium'
import { WORLD_STYLES, type WorldStyleKey } from './shaders/index.ts'

/**
 * The sensor-style post-process pipeline (God's Eye View's `_initStages`,
 * recast as an instance-scoped service — vision §take-and-adapt 1).
 *
 * WHY instance-scoped rather than upstream's global singleton: World mounts
 * and unmounts with a React route, and a globaled stage set outlives the
 * viewer it was added to. Every stage here is owned by one `WorldStyles`,
 * destroyed with it, and unreachable afterwards.
 *
 * A ZERO-INTENSITY STAGE IS DISABLED, not merely transparent — upstream
 * learned that six stacked identity passes cost real frames. `enabled` and
 * `intensity` move together through `setStyle` alone.
 *
 * THE CLOCK ONLY TICKS FOR A VISIBLE ANIMATED SHADER. `requestRenderMode` is
 * on, so an always-running rAF that calls `requestRender` would silently
 * convert the idle globe into a continuously drawn one. The loop starts when
 * an animated style becomes visible and stops the moment it is not.
 * Reduced-motion clients never start it: the still frame is the whole look.
 */
export class WorldStyles {
  private viewer: Cesium.Viewer
  private stages = new Map<WorldStyleKey, Cesium.PostProcessStage>()
  private current: WorldStyleKey = 'none'
  private frame: number | undefined
  private startedAt = 0
  private reducedMotion: boolean

  constructor(viewer: Cesium.Viewer, { reducedMotion = false } = {}) {
    this.viewer = viewer
    this.reducedMotion = reducedMotion
    for (const style of WORLD_STYLES) {
      if (!style.shader) continue
      const uniforms: Record<string, number> = { intensity: 0 }
      if (style.shader.fragmentShader.includes('uniform float time')) uniforms.time = 0
      for (const [name, meta] of Object.entries(style.shader.uniforms ?? {})) {
        uniforms[name] = meta.default
      }
      try {
        const stage = new Cesium.PostProcessStage({
          name: `dialecticWorld_${style.key}`,
          fragmentShader: style.shader.fragmentShader,
          uniforms,
        })
        stage.enabled = false
        viewer.scene.postProcessStages.add(stage)
        this.stages.set(style.key, stage)
      } catch {
        // A driver that refuses to compile one shader must not cost the globe.
        // The style simply will not be offered by `available()`.
      }
    }
  }

  /** Which looks this GPU actually compiled. `none` is always available. */
  available(): WorldStyleKey[] {
    return WORLD_STYLES
      .filter((s) => !s.shader || this.stages.has(s.key))
      .map((s) => s.key)
  }

  style(): WorldStyleKey {
    return this.current
  }

  setStyle(key: WorldStyleKey): void {
    if (this.viewer.isDestroyed()) return
    this.current = key
    let animated = false
    for (const [name, stage] of this.stages) {
      const on = name === key
      stage.uniforms.intensity = on ? 1 : 0
      stage.enabled = on
      if (on && stage.uniforms.time !== undefined) animated = true
    }
    if (animated && !this.reducedMotion) this.startClock()
    else this.stopClock()
    this.viewer.scene.requestRender()
  }

  private startClock(): void {
    if (this.frame !== undefined) return
    this.startedAt = performance.now()
    const tick = () => {
      if (this.viewer.isDestroyed()) return
      const seconds = (performance.now() - this.startedAt) / 1000
      let live = false
      for (const stage of this.stages.values()) {
        if (!stage.enabled || stage.uniforms.time === undefined) continue
        stage.uniforms.time = seconds
        live = true
      }
      if (!live) {
        this.frame = undefined
        return
      }
      this.viewer.scene.requestRender()
      this.frame = requestAnimationFrame(tick)
    }
    this.frame = requestAnimationFrame(tick)
  }

  private stopClock(): void {
    if (this.frame === undefined) return
    cancelAnimationFrame(this.frame)
    this.frame = undefined
  }

  destroy(): void {
    this.stopClock()
    if (this.viewer.isDestroyed()) {
      this.stages.clear()
      return
    }
    for (const stage of this.stages.values()) {
      this.viewer.scene.postProcessStages.remove(stage)
    }
    this.stages.clear()
  }
}
