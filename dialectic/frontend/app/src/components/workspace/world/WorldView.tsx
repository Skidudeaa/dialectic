import { useEffect, useRef, useState } from 'react'
import * as Cesium from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import type { GeoScope } from '../../../types/geo.ts'
import type { WorldCamera } from './worldCamera.ts'
import { isProvisional, scopesBounds } from './worldScopes.ts'
import './World.css'

/**
 * WorldView — the globe, and nothing but the globe (World Lens, 2026-08-25).
 *
 * LOADED ON DEMAND. This module imports Cesium statically, and AtlasScene
 * reaches it only through React.lazy, so the ~3 MB chunk (vite.config.ts
 * `manualChunks.cesium`) is fetched the first time a person opens World and
 * never precached (the SW's globIgnores). The House list never pays for it.
 *
 * KEYLESS AND ATTRIBUTED. OpenStreetMap raster tiles (credit rides the
 * provider), Re:Earth ellipsoid terrain (CC BY 4.0) with the plain ellipsoid
 * as fallback — never Google photorealistic tiles (vision §Reject 5). The
 * credit line is OUR element (`creditContainer`), always visible, never
 * hidden by a clean-view mode; "Made with Natural Earth" is added as a
 * static credit because the region rings come from that pack.
 *
 * RENDER GOVERNOR, the small port. Cesium's requestRenderMode with
 * `maximumRenderTimeChange = Infinity` — the scene draws when something
 * changes and otherwise the GPU idles. GEV's `renderGovernor.js` kept a
 * ref-counted set of "hold continuous" owners for animated layers; nothing
 * here animates, so the hold set is deliberately absent (add it with the
 * first moving contact, not before).
 *
 * WHAT IT DRAWS: GeoScope rows only — the fenced geometry the projection
 * already carries. Polygons as translucent fills, routes as lines, points
 * as pins; a machine_proposed scope is dashed and dim, because authority is
 * a column and the style merely agrees with it. Selecting an entity reports
 * the scope to the parent, which navigates through the ONE writer.
 *
 * CAMERA STATE goes out through `onCameraSettle`, debounced, and the parent
 * serializes it into the `view` axis with `navigate(..., 'replace')` — this
 * component owns no URL. Reduced motion → `setView` instead of `flyTo`.
 *
 * WEBGL FAILURE is a state, not a throw: the parent keeps the list, and this
 * renders a one-line note in place of the canvas.
 */

interface WorldViewProps {
  scopes: GeoScope[]
  /** Restore this camera on mount; otherwise frame every scope. */
  initialCamera: WorldCamera | null
  /** Frame these scopes (a room's) instead of all when no camera is given. */
  focusScopes?: GeoScope[] | null
  onSelect: (scope: GeoScope) => void
  onCameraSettle: (camera: WorldCamera) => void
}

const OSM_URL = 'https://tile.openstreetmap.org/'
const TERRAIN_URL = 'https://terrain.reearth.land/cesium-mesh/ellipsoid'
const NATURAL_EARTH_CREDIT = 'Made with Natural Earth'
const TERRAIN_CREDIT = 'Terrain © Re:Earth / Mapterhorn (CC BY 4.0)'
const SETTLE_MS = 1000

const FILL = Cesium.Color.fromCssColorString('#F2A24A').withAlpha(0.18)
const LINE = Cesium.Color.fromCssColorString('#F2A24A')
const PROVISIONAL = Cesium.Color.fromCssColorString('#A38865')
const PIN = Cesium.Color.fromCssColorString('#54D8C6')

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

function addScope(viewer: Cesium.Viewer, scope: GeoScope): void {
  const provisional = isProvisional(scope)
  const line = provisional ? PROVISIONAL : LINE
  const g = scope.geometry
  const base = { id: scope.id, name: scope.label || scope.kind, description: undefined }
  if (g.type === 'Point') {
    const [lon, lat] = g.coordinates as number[]
    viewer.entities.add({
      ...base,
      position: Cesium.Cartesian3.fromDegrees(lon, lat),
      point: {
        pixelSize: 9,
        color: provisional ? PROVISIONAL : PIN,
        outlineColor: Cesium.Color.BLACK.withAlpha(0.6),
        outlineWidth: 1,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      label: {
        text: scope.label,
        font: '12px sans-serif',
        fillColor: Cesium.Color.fromCssColorString('#E3D2B4'),
        pixelOffset: new Cesium.Cartesian2(0, -16),
        showBackground: true,
        backgroundColor: Cesium.Color.fromCssColorString('#150D07').withAlpha(0.8),
      },
    })
    return
  }
  if (g.type === 'LineString') {
    const flat = (g.coordinates as number[][]).flatMap(([lon, lat]) => [lon, lat])
    viewer.entities.add({
      ...base,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: provisional ? 2 : 3,
        material: provisional
          ? new Cesium.PolylineDashMaterialProperty({ color: line, dashLength: 12 })
          : line,
        clampToGround: true,
      },
    })
    return
  }
  if (g.type === 'Polygon') {
    const outer = (g.coordinates as number[][][])[0] ?? []
    const flat = outer.flatMap(([lon, lat]) => [lon, lat])
    viewer.entities.add({
      ...base,
      polygon: {
        hierarchy: new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(flat)),
        material: provisional ? PROVISIONAL.withAlpha(0.08) : FILL,
        outline: true,
        outlineColor: line,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray(flat),
        width: provisional ? 1.5 : 2,
        material: provisional
          ? new Cesium.PolylineDashMaterialProperty({ color: line, dashLength: 10 })
          : line,
        clampToGround: true,
      },
    })
  }
}

function frame(viewer: Cesium.Viewer, scopes: GeoScope[], animate: boolean): void {
  const bounds = scopesBounds(scopes)
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

export default function WorldView({ scopes, initialCamera, focusScopes, onSelect, onCameraSettle }: WorldViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const creditRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Cesium.Viewer | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  // Latest callbacks, read by the Cesium handlers registered once below.
  const selectRef = useRef(onSelect)
  const settleRef = useRef(onCameraSettle)
  useEffect(() => {
    selectRef.current = onSelect
    settleRef.current = onCameraSettle
  }, [onSelect, onCameraSettle])

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
        // a human's share) capture the frame instead of a cleared canvas;
        // GEV sets it for the same reason. requestRenderMode keeps the cost
        // to the frames actually drawn.
        contextOptions: { webgl: { preserveDrawingBuffer: true } },
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'WebGL is unavailable'
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
      const scope = (viewer as unknown as { __scopes?: GeoScope[] }).__scopes?.find((s) => s.id === entityId)
      if (scope) selectRef.current(scope)
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK)

    let timer: number | undefined
    const onMoveEnd = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        const cam = cameraOf(viewer)
        if (cam) settleRef.current(cam)
      }, SETTLE_MS)
    }
    viewer.camera.moveEnd.addEventListener(onMoveEnd)

    return () => {
      window.clearTimeout(timer)
      viewer.camera.moveEnd.removeEventListener(onMoveEnd)
      handler.destroy()
      viewerRef.current = null
      delete (window as unknown as { __dialecticWorld?: Cesium.Viewer }).__dialecticWorld
      viewer.destroy()
    }
  }, [])

  // Redraw the scopes whenever the projection changes.
  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed()) return
    viewer.entities.removeAll()
    for (const scope of scopes) addScope(viewer, scope)
    ;(viewer as unknown as { __scopes?: GeoScope[] }).__scopes = scopes
    viewer.scene.requestRender()
  }, [scopes])

  // Initial camera: restore, or frame the focus set, or frame everything.
  const framedRef = useRef(false)
  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed() || framedRef.current) return
    if (scopes.length === 0 && !initialCamera) return
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
      frame(viewer, focusScopes && focusScopes.length > 0 ? focusScopes : scopes, !reducedMotion())
    }
    viewer.scene.requestRender()
  }, [scopes, initialCamera, focusScopes])

  return (
    <div className="world-view" data-testid="world-view">
      {failure ? (
        <p className="world-fallback" role="status">
          The globe could not start here ({failure}). The list below is the
          same map, in full.
        </p>
      ) : null}
      <div ref={containerRef} className="world-canvas" aria-label="World globe" />
      <div ref={creditRef} className="world-credits" />
    </div>
  )
}
