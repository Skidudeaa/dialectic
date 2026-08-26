import type { WorldSignal, WorldSignalSource } from '../../../types/geo.ts'
import type { WorldCamera } from './worldCamera.ts'
import { WORLD_STYLES, type WorldStyleKey } from './shaders/index.ts'
import './WorldHud.css'

/**
 * The World HUD — God's Eye View's cockpit chrome, rebuilt as ordinary DOM.
 *
 * WHY DOM AND NOT GLSL: upstream renders its readouts inside the fragment
 * shader (a seven-segment font drawn per pixel). That is beautiful and it is
 * unreadable to a screen reader, unselectable, and invisible when WebGL is
 * unavailable — which is the exact path this product must keep working. Every
 * number here is real text with a real label, sitting over the canvas.
 *
 * IT NEVER BECOMES THE ONLY COPY. Layer toggles, source states and the
 * tracked contact's telemetry all exist in the complete list below the globe
 * as well; the HUD is a second view of them, not a second source.
 */

export interface WorldLayerState {
  layer: string
  label: string
  count: number
  enabled: boolean
}

export interface WorldHudProps {
  camera: WorldCamera | null
  layers: WorldLayerState[]
  sources: WorldSignalSource[]
  styles: WorldStyleKey[]
  style: WorldStyleKey
  tracked: WorldSignal | null
  hudVisible: boolean
  onToggleLayer: (layer: string) => void
  onStyle: (style: WorldStyleKey) => void
  onRelease: () => void
}

const SOURCE_TONE: Record<string, string> = {
  ok: 'live',
  partial: 'partial',
  stale: 'stale',
  confirmed_empty: 'empty',
  unavailable: 'down',
  rate_limited: 'down',
  not_configured: 'off',
}

function degrees(value: number, positive: string, negative: string): string {
  const hemisphere = value >= 0 ? positive : negative
  return `${Math.abs(value).toFixed(4)}° ${hemisphere}`
}

function altitude(metres: number): string {
  return metres >= 10_000
    ? `${(metres / 1000).toFixed(0)} km`
    : `${metres.toFixed(0)} m`
}

/** Everything the provider told us about this contact, in its own words.
 *  Keys are rendered as given: inventing prettier names for provider fields
 *  is how a readout starts claiming more than the feed said. */
function TelemetryRows({ signal }: { signal: WorldSignal }) {
  const rows = Object.entries(signal.details)
  if (rows.length === 0) return <p className="hud-quiet">No telemetry beyond position.</p>
  return (
    <dl className="hud-telemetry">
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{key.replace(/_/g, ' ')}</dt>
          <dd>{String(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

export function WorldHud({
  camera, layers, sources, styles, style, tracked, hudVisible,
  onToggleLayer, onStyle, onRelease,
}: WorldHudProps) {
  const styleOptions = WORLD_STYLES.filter((s) => styles.includes(s.key))
  return (
    <div className="world-hud" data-visible={hudVisible ? 'true' : 'false'}>
      {hudVisible ? <div className="hud-reticle" aria-hidden="true" /> : null}

      <div className="hud-panel hud-layers" role="group" aria-label="Signal layers">
        <h4>Layers</h4>
        {layers.length === 0 ? (
          <p className="hud-quiet">No live layer is reporting into your rooms.</p>
        ) : (
          <ul>
            {layers.map((layer) => (
              <li key={layer.layer}>
                <label>
                  <input
                    type="checkbox"
                    checked={layer.enabled}
                    onChange={() => onToggleLayer(layer.layer)}
                  />
                  <span className="hud-layer-name" data-layer={layer.layer}>{layer.label}</span>
                  <span className="hud-count">{layer.count}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {sources.length > 0 ? (
          <ul className="hud-sources" aria-label="Source states">
            {sources.map((source) => (
              <li key={source.provider} data-tone={SOURCE_TONE[source.source_state] ?? 'off'}>
                <span className="hud-source-name">{source.provider}</span>
                <span className="hud-source-state">{source.source_state.replace(/_/g, ' ')}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <div className="hud-panel hud-styles" role="group" aria-label="Sensor style">
        <h4>Optics</h4>
        <ul>
          {styleOptions.map((option, index) => (
            <li key={option.key}>
              <button
                type="button"
                aria-pressed={style === option.key}
                onClick={() => onStyle(option.key)}
              >
                <span className="hud-key">{index}</span>
                {option.label}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {hudVisible && camera ? (
        <dl className="hud-panel hud-readout" aria-label="Camera">
          <div><dt>Lat</dt><dd>{degrees(camera.lat, 'N', 'S')}</dd></div>
          <div><dt>Lon</dt><dd>{degrees(camera.lon, 'E', 'W')}</dd></div>
          <div><dt>Alt</dt><dd>{altitude(camera.alt)}</dd></div>
          <div><dt>Hdg</dt><dd>{(((camera.heading % 360) + 360) % 360).toFixed(0)}°</dd></div>
          <div><dt>Pitch</dt><dd>{camera.pitch.toFixed(0)}°</dd></div>
        </dl>
      ) : null}

      {tracked ? (
        <section className="hud-panel hud-contact" aria-label="Tracked contact">
          <header>
            <span className="hud-contact-layer" data-layer={tracked.layer}>{tracked.layer}</span>
            <h4>{tracked.label || tracked.source_id}</h4>
            <button type="button" onClick={onRelease} aria-label="Release track">
              Release <span className="hud-key">Esc</span>
            </button>
          </header>
          <TelemetryRows signal={tracked} />
          <p className="hud-provenance">
            {tracked.provider} · {tracked.source_state.replace(/_/g, ' ')} ·{' '}
            {tracked.freshness}
            {tracked.provenance.url ? (
              <>
                {' · '}
                <a href={tracked.provenance.url} target="_blank" rel="noreferrer noopener">
                  source
                </a>
              </>
            ) : null}
          </p>
          <p className="hud-quiet">
            Tracking follows this contact on screen. It creates no geography —
            placing it is a separate act, in the list below.
          </p>
        </section>
      ) : null}
    </div>
  )
}
