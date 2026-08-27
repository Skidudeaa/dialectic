import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as Cesium from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import type { GeoScope, WorldSignal, WorldSignalSource } from '../../../types/geo.ts'
import type { WorldCamera } from './worldCamera.ts'
import { scopesBounds } from './worldScopes.ts'
import { addSignal, addTrail, signalHeight } from './worldSignals.ts'
import { addScope } from './worldScopeEntities.ts'
import { WorldStyles } from './worldStyleStages.ts'
import { styleForKey, type WorldStyleKey } from './shaders/index.ts'
import { WorldHud, type WorldLayerState } from './WorldHud.tsx'
import './World.css'

/**
 * WorldView — the globe, its sensors, and the contact you are following.
 *
 * LOADED ON DEMAND. This module imports Cesium statically, and AtlasScene
 * reaches it only through React.lazy, so the multi-megabyte chunk is fetched
 * the first time a person opens World and never precached (the SW's
 * globIgnores). The House list never pays for it.
 *
 * KEYLESS AND ATTRIBUTED. OpenStreetMap raster tiles (credit rides the
 * provider), Re:Earth ellipsoid terrain (CC BY 4.0) with the plain ellipsoid
 * as fallback — never Google photorealistic tiles (vision §Reject 5). The
 * credit line is OUR element (`creditContainer`), always visible, never
 * hidden by a clean-view mode.
 *
 * RENDER GOVERNOR. Cesium's requestRenderMode with `maximumRenderTimeChange =
 * Infinity` — the scene draws when something changes and otherwise the GPU
 * idles. Two things hold it awake, both bounded and both self-releasing: an
 * animated sensor style while it is visible (WorldStyles owns that clock) and
 * a tracked contact while the camera is following it.
 *
 * WHAT IT DRAWS: durable GeoScopes and the ephemeral live-signal layers, both
 * already room-fenced by the projection. A scope click reports the durable row
 * to the parent (it is a Focus object). A SIGNAL click only starts TRACKING —
 * the camera follows it and its telemetry opens in the HUD. Tracking creates
 * nothing: durable geography still requires the explicit placement action in
 * the complete text list, which is a human server write.
 *
 * CAMERA STATE goes out through `onCameraSettle`, debounced, and the parent
 * serializes it into the `view` axis with `navigate(..., 'replace')` — this
 * component owns no URL. Reduced motion → `setView` instead of `flyTo`, and no
 * animated shader clock.
 *
 * WEBGL FAILURE is a state, not a throw: the parent keeps the list, and this
 * renders a one-line note in place of the canvas.
 */

interface WorldViewProps {
  scopes: GeoScope[]
  signals: WorldSignal[]
  /** Provider snapshot states, rendered as the HUD's source lamps. */
  sources?: WorldSignalSource[]
  /** Restore this camera on mount; otherwise frame every scope. */
  initialCamera: WorldCamera | null
  /** Frame these scopes (a room's) instead of all when no camera is given. */
  focusScopes?: GeoScope[] | null
  focusSignals?: WorldSignal[] | null
  /** The one durable object selected through the shared navigation axis. */
  selectedScopeId?: string | null
  onSelect: (scope: GeoScope) => void
  onCameraSettle: (camera: WorldCamera) => void
}

const OSM_URL = 'https://tile.openstreetmap.org/'
const TERRAIN_URL = 'https://terrain.reearth.land/cesium-mesh/ellipsoid'
const NATURAL_EARTH_CREDIT = 'Made with Natural Earth'
const TERRAIN_CREDIT = 'Terrain © Re:Earth / Mapterhorn (CC BY 4.0)'
const SETTLE_MS = 1000
/** How many received fixes a tracked contact's trail keeps. Fixes, not
 *  seconds: the trail is the evidence we were handed, at whatever rate the
 *  provider handed it over. */
const TRAIL_LIMIT = 60
const LAYER_LABELS: Record<string, string> = {
  aircraft: 'Aircraft',
  earthquakes: 'Earthquakes',
  fires: 'Fires',
  satellites: 'Satellites',
  launches: 'Launches',
}

function reducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function cameraOf(viewer: Cesium.Viewer): WorldCamera | null {
  const carto = viewer.camera.positionCartographic
  if (!carto) return null
  return {
    lat: Cesium.Math.toDegrees(carto.latitude),
    lon: Cesium.Math.toDegrees(carto.longitude),
    alt: carto.height,
    heading: Cesium.Math.toDegrees(viewer.camera.heading),
    pitch: Cesium.Math.toDegrees(viewer.camera.pitch),
  }
}

function frame(
  viewer: Cesium.Viewer,
  geometry: Array<{ geometry: { coordinates: unknown } }>,
  animate: boolean,
): void {
  const bounds = scopesBounds(geometry)
  if (!bounds) {
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(30, 20, 18_000_000) })
    return
  }
  const [w, s, e, n] = bounds
  const pad = Math.max(0.3, (e - w) * 0.15, (n - s) * 0.15)
  const rect = Cesium.Rectangle.fromDegrees(w - pad, s - pad, e + pad, n + pad)
  if (animate) viewer.camera.flyTo({ destination: rect, duration: 1.2 })
  else viewer.camera.setView({ destination: rect })
}

function positionOf(signal: WorldSignal): Cesium.Cartesian3 | null {
  if (signal.geometry.type !== 'Point') return null
  const [lon, lat] = signal.geometry.coordinates as number[]
  if (typeof lon !== 'number' || typeof lat !== 'number') return null
  const height = signalHeight(signal)
  return Cesium.Cartesian3.fromDegrees(lon, lat, height ?? 0)
}

/** How far back the camera should sit to hold a contact comfortably in
 *  frame — high enough for the ISS, close enough for a taxiing aircraft. */
function trackRange(signal: WorldSignal): number {
  const height = signalHeight(signal) ?? 0
  return Math.max(30_000, height * 2.5)
}

export default function WorldView({
  scopes, signals, sources = [], initialCamera, focusScopes, focusSignals,
  selectedScopeId = null, onSelect, onCameraSettle,
}: WorldViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const creditRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Cesium.Viewer | null>(null)
  const stylesRef = useRef<WorldStyles | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [style, setStyle] = useState<WorldStyleKey>('none')
  const [availableStyles, setAvailableStyles] = useState<WorldStyleKey[]>(['none'])
  const [hudVisible, setHudVisible] = useState(true)
  const [hiddenLayers, setHiddenLayers] = useState<ReadonlySet<string>>(new Set())
  const [trackedId, setTrackedId] = useState<string | null>(null)
  const [camera, setCamera] = useState<WorldCamera | null>(initialCamera)
  // Received fixes for the tracked contact, oldest first.
  const trailRef = useRef<{ id: string; positions: Cesium.Cartesian3[] }>({ id: '', positions: [] })
  // Latest callbacks, read by the Cesium handlers registered once below.
  const selectRef = useRef(onSelect)
  const settleRef = useRef(onCameraSettle)
  useEffect(() => {
    selectRef.current = onSelect
    settleRef.current = onCameraSettle
  }, [onSelect, onCameraSettle])

  const visibleSignals = useMemo(
    () => signals.filter((s) => !hiddenLayers.has(s.layer)),
    [signals, hiddenLayers],
  )
  const tracked = useMemo(
    () => visibleSignals.find((s) => s.id === trackedId) ?? null,
    [visibleSignals, trackedId],
  )
  const layers = useMemo<WorldLayerState[]>(() => {
    const counts = new Map<string, number>()
    for (const signal of signals) counts.set(signal.layer, (counts.get(signal.layer) ?? 0) + 1)
    return [...counts.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([layer, count]) => ({
        layer,
        label: LAYER_LABELS[layer] ?? layer,
        count,
        enabled: !hiddenLayers.has(layer),
      }))
  }, [signals, hiddenLayers])

  const toggleLayer = useCallback((layer: string) => {
    setHiddenLayers((current) => {
      const next = new Set(current)
      if (next.has(layer)) next.delete(layer)
      else next.add(layer)
      return next
    })
  }, [])

  const applyStyle = useCallback((key: WorldStyleKey) => {
    setStyle(key)
    stylesRef.current?.setStyle(key)
  }, [])

  // Create the viewer once. Scopes/camera are applied in the effects below.
  useEffect(() => {
    const container = containerRef.current
    const credit = creditRef.current
    if (!container || !credit) return
    let viewer: Cesium.Viewer
    try {
      viewer = new Cesium.Viewer(container, {
        baseLayer: new Cesium.ImageryLayer(new Cesium.OpenStreetMapImageryProvider({ url: OSM_URL })),
        creditContainer: credit,
        animation: false,
        timeline: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        baseLayerPicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
        requestRenderMode: true,
        maximumRenderTimeChange: Infinity,
        msaaSamples: 2,
        // A preserved buffer is what lets a screenshot (browser acceptance,
        // a human's share) capture the frame instead of a cleared canvas.
        // requestRenderMode keeps the cost to the frames actually drawn.
        contextOptions: { webgl: { preserveDrawingBuffer: true } },
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'WebGL is unavailable'
      // Cesium may append its own modal error panel before Viewer throws.
      // The complete text list is our usable fallback; remove the abandoned
      // partial widget so it cannot cover or trap interaction with that list.
      container.replaceChildren()
      // Deferred one tick: the set-state-in-effect rule (rightly) refuses a
      // synchronous write inside the effect body — same idiom as useAtlas.
      void Promise.resolve().then(() => setFailure(message))
      return
    }
    viewerRef.current = viewer
    // A probe handle for browser acceptance (the harness reads tile and
    // render state through it); nothing in the app reads it.
    ;(window as unknown as { __dialecticWorld?: Cesium.Viewer }).__dialecticWorld = viewer
    viewer.scene.globe.enableLighting = false
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#150D07')
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#0A0603')
    if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = true
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = false
    // Credits ON SCREEN, in our own line: OSM's tile policy asks for visible
    // attribution, Natural Earth's ring provenance rides with it, and the
    // engine credit is the engine's name — not the ion service we do not use.
    Cesium.CreditDisplay.cesiumCredit = new Cesium.Credit('CesiumJS', true)
    viewer.creditDisplay.addStaticCredit(new Cesium.Credit('© OpenStreetMap contributors', true))
    viewer.creditDisplay.addStaticCredit(new Cesium.Credit(NATURAL_EARTH_CREDIT, true))

    const styleManager = new WorldStyles(viewer, { reducedMotion: reducedMotion() })
    stylesRef.current = styleManager
    void Promise.resolve().then(() => setAvailableStyles(styleManager.available()))

    // Keyless terrain with a plain-ellipsoid fallback; never throws, and a
    // late failure leaves the globe drawn on the ellipsoid it started on.
    void Cesium.CesiumTerrainProvider.fromUrl(TERRAIN_URL, { credit: TERRAIN_CREDIT })
      .then((provider) => { if (viewerRef.current === viewer) viewer.terrainProvider = provider })
      .catch(() => { /* ellipsoid terrain stands */ })

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas)
    handler.setInputAction((movement: { position: Cesium.Cartesian2 }) => {
      const picked = viewer.scene.pick(movement.position)
      const id = picked?.id
      const entityId = id instanceof Cesium.Entity ? String(id.id) : null
      if (!entityId) return
      const store = viewer as unknown as { __scopes?: GeoScope[]; __signals?: WorldSignal[] }
      const scope = store.__scopes?.find((s) => s.id === entityId)
      if (scope) {
        selectRef.current(scope)
        return
      }
      // A signal is trackable, never selectable: it opens no Focus object and
      // writes nothing. The authority ladder starts at explicit placement.
      const signal = store.__signals?.find((s) => s.id === entityId)
      if (signal) void Promise.resolve().then(() => setTrackedId(signal.id))
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK)

    let timer: number | undefined
    const onMoveEnd = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        const cam = cameraOf(viewer)
        if (!cam) return
        settleRef.current(cam)
        setCamera(cam)
      }, SETTLE_MS)
    }
    viewer.camera.moveEnd.addEventListener(onMoveEnd)

    return () => {
      window.clearTimeout(timer)
      viewer.camera.moveEnd.removeEventListener(onMoveEnd)
      handler.destroy()
      styleManager.destroy()
      stylesRef.current = null
      viewerRef.current = null
      delete (window as unknown as { __dialecticWorld?: Cesium.Viewer }).__dialecticWorld
      viewer.destroy()
    }
  }, [])

  // Redraw both layers whenever the projection changes. Only scopes and
  // signals the pick handler may resolve are copied onto the viewer.
  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed()) return
    viewer.entities.removeAll()
    for (const scope of scopes) addScope(viewer, scope, scope.id === selectedScopeId)
    for (const signal of visibleSignals) addSignal(viewer, signal, signal.id === trackedId)
    if (tracked) addTrail(viewer, tracked, trailRef.current.positions)
    const store = viewer as unknown as { __scopes?: GeoScope[]; __signals?: WorldSignal[] }
    store.__scopes = scopes
    store.__signals = visibleSignals
    viewer.scene.requestRender()
  }, [scopes, visibleSignals, selectedScopeId, trackedId, tracked])

  // Follow the tracked contact: extend its trail with each received fix and
  // move the camera onto it. A contact that leaves the projection (expired,
  // out of coverage, layer switched off) releases the track rather than
  // leaving the camera parked on a ghost.
  useEffect(() => {
    const viewer = viewerRef.current
    // A contact that has left the projection (expired, out of coverage, its
    // layer switched off) simply stops being followed -- the id is KEPT so
    // that the same aircraft on the next poll resumes its track rather than
    // needing to be found and clicked again.
    if (!viewer || viewer.isDestroyed() || !tracked) return
    const position = positionOf(tracked)
    if (!position) return
    const trail = trailRef.current
    if (trail.id !== tracked.id) {
      trail.id = tracked.id
      trail.positions = []
    }
    const last = trail.positions[trail.positions.length - 1]
    if (!last || !Cesium.Cartesian3.equalsEpsilon(last, position, 0, 1)) {
      trail.positions.push(position)
      if (trail.positions.length > TRAIL_LIMIT) trail.positions.shift()
    }
    const range = trackRange(tracked)
    const orientation = new Cesium.HeadingPitchRange(
      viewer.camera.heading, Cesium.Math.toRadians(-35), range,
    )
    if (reducedMotion()) {
      viewer.camera.lookAt(position, orientation)
      viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY)
    } else {
      void viewer.camera.flyToBoundingSphere(
        new Cesium.BoundingSphere(position, range * 0.4),
        { duration: 1.0 },
      )
    }
    viewer.scene.requestRender()
  }, [tracked, trackedId])

  // Initial camera: restore, or frame the focus set, or frame everything.
  const framedRef = useRef(false)
  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed() || framedRef.current) return
    if (scopes.length === 0 && signals.length === 0 && !initialCamera) return
    framedRef.current = true
    if (initialCamera) {
      viewer.camera.setView({
        destination: Cesium.Cartesian3.fromDegrees(initialCamera.lon, initialCamera.lat, initialCamera.alt),
        orientation: {
          heading: Cesium.Math.toRadians(initialCamera.heading),
          pitch: Cesium.Math.toRadians(initialCamera.pitch),
          roll: 0,
        },
      })
    } else {
      const focused = [
        ...(focusScopes ?? []),
        ...(focusSignals ?? []),
      ]
      frame(viewer, focused.length > 0 ? focused : [...scopes, ...signals], !reducedMotion())
    }
    viewer.scene.requestRender()
  }, [scopes, signals, initialCamera, focusScopes, focusSignals])

  // The cockpit keys, God's Eye View's own: digits pick the optics, H hides
  // the HUD, Esc releases the track. Ignored while a person is typing.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      if (target && (target.isContentEditable
        || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      if (event.key === 'Escape') {
        setTrackedId(null)
        return
      }
      if (event.key === 'h' || event.key === 'H') {
        setHudVisible((visible) => !visible)
        return
      }
      const style = styleForKey(event.key, availableStyles)
      if (style) applyStyle(style)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [availableStyles, applyStyle])

  return (
    <div className="world-view" data-testid="world-view" data-style={style}>
      {failure ? (
        <p className="world-fallback" role="status">
          The globe could not start here ({failure}). The list below is the
          same map, in full.
        </p>
      ) : null}
      <div className="world-stage" hidden={Boolean(failure)}>
        <div
          ref={containerRef}
          className="world-canvas"
          aria-label="World globe"
        />
        {failure ? null : (
          <WorldHud
            camera={camera}
            layers={layers}
            sources={sources}
            styles={availableStyles}
            style={style}
            tracked={tracked}
            hudVisible={hudVisible}
            onToggleLayer={toggleLayer}
            onStyle={applyStyle}
            onRelease={() => setTrackedId(null)}
          />
        )}
      </div>
      <div ref={creditRef} className="world-credits" />
    </div>
  )
}
