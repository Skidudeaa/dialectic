import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import { feature } from 'topojson-client'
import type { Topology, GeometryCollection } from 'topojson-specification'
import type { ChartProps } from '../types'
import { colors, style } from './mapStyle'
import { mountMap } from './mapRuntime'
import 'maplibre-gl/dist/maplibre-gl.css'
import './chart.css'

export { LegCard, SeasonStrip, JourneyStrip } from './Cards'

// Shared across StrictMode's effect replay and later chart mounts; never bundled.
let coastlines: ReturnType<typeof loadLand> | undefined
async function loadLand() {
  const response = await fetch(`${import.meta.env.BASE_URL}longway/land-50m.json`)
  if (!response.ok) throw new Error(`Coastlines: HTTP ${response.status}`)
  const topology = await response.json() as Topology<{ land: GeometryCollection }>
  return feature(topology, topology.objects.land)
}

export default function Chart(props: ChartProps) {
  const container = useRef<HTMLDivElement>(null)
  const latest = useRef(props)
  const runtime = useRef<ReturnType<typeof mountMap> | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    latest.current = props
    runtime.current?.update(props)
  }, [props])
  useEffect(() => {
    const element = container.current
    if (!element) return
    let disposed = false
    // Read inherited shell tokens once at mount, including a room-local theme.
    const palette = colors(element)
    coastlines ??= loadLand().catch(error => { coastlines = undefined; throw error })
    void coastlines.then(land => {
      if (disposed) return
      const size = Math.max(1, Math.min(element.clientWidth, element.clientHeight))
      const map = new maplibregl.Map({
        container: element, center: [45, 22], zoom: Math.log2(size * 0.45 * 2 * Math.PI / 512),
        attributionControl: false, dragRotate: false, pitchWithRotate: false, touchPitch: false,
        style: style(land, latest.current, palette, window.matchMedia('(prefers-color-scheme: dark)').matches),
      })
      runtime.current = mountMap(map, element, () => latest.current)
    }).catch((reason: unknown) => {
      if (!disposed) setError(reason instanceof Error ? reason.message : 'The globe could not load.')
    })
    return () => { disposed = true; runtime.current?.destroy(); runtime.current = null }
  }, [])
  const unheard = props.data.vehicles.filter(v => !v.heard)
  return <div className="longway-chart-ui longway-chart">
    <div ref={container} className="longway-map" role="region" aria-label="Globe of candidate journeys" />
    {error && <p role="status">The globe could not load. {error}</p>}
    {(props.data.fixes_state.stale || unheard.length > 0) && <div className="vehicle-list">
      {props.data.fixes_state.stale && <p>Listener silent since {props.data.fixes_state.written ?? 'an unknown time'}</p>}
      {unheard.length > 0 && <details>
        <summary>{unheard.length === 1 ? '1 vehicle' : `${unheard.length} vehicles`} never heard</summary>
        <ul aria-label="Vehicles never heard">{unheard.map((v, i) => <li key={`${v.journey}-${v.name}-${i}`} style={{ opacity: props.focus && props.focus !== v.journey ? 0.25 : 1 }}>{v.name}, never heard</li>)}</ul>
      </details>}
    </div>}
  </div>
}
