import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { WorldSignal, WorldSignalSource } from '../../../types/geo.ts'
import { WorldHud, type WorldHudProps } from './WorldHud.tsx'

const aircraft: WorldSignal = {
  id: 'world_signal:adsb:a1b2c3',
  provider: 'adsb',
  source_id: 'a1b2c3',
  room_id: 'room-h',
  layer: 'aircraft',
  kind: 'point',
  geometry: { type: 'Point', coordinates: [56.3, 26.5] },
  provenance: {
    provider: 'adsb', acquisition: 'adapter:adsb', source_id: 'a1b2c3',
    url: 'https://globe.adsb.lol/?icao=a1b2c3', credit: 'Data from adsb.lol (ODbL)',
  },
  source_state: 'ok',
  freshness: 'current',
  coverage: 'receivers within 250 NM',
  observed_at: null,
  retrieved_at: '2026-08-26T17:59:00Z',
  expires_at: '2026-08-26T18:02:00Z',
  label: 'UAE201',
  details: { altitude_ft: 37000, track_deg: 118.4 },
}

const sources: WorldSignalSource[] = [
  {
    provider: 'adsb', configured_room_ids: ['room-h'], source_state: 'ok',
    freshness: 'current', coverage: 'receivers', retrieved_at: '2026-08-26T17:59:00Z',
    signal_count: 1,
  },
  {
    provider: 'firms', configured_room_ids: ['room-h'], source_state: 'not_configured',
    freshness: 'not_applicable', coverage: 'set FIRMS_MAP_KEY',
    retrieved_at: '2026-08-26T17:59:00Z', signal_count: 0,
  },
]

function hud(overrides: Partial<WorldHudProps> = {}) {
  const props: WorldHudProps = {
    camera: { lat: 26.5, lon: 56.3, alt: 420_000, heading: -30, pitch: -45 },
    layers: [{ layer: 'aircraft', label: 'Aircraft', count: 12, enabled: true }],
    sources,
    styles: ['none', 'thermal'],
    style: 'none',
    tracked: null,
    hudVisible: true,
    onToggleLayer: vi.fn(),
    onStyle: vi.fn(),
    onRelease: vi.fn(),
    ...overrides,
  }
  render(<WorldHud {...props} />)
  return props
}

describe('WorldHud', () => {
  it('names an unconfigured provider rather than showing it as empty', () => {
    hud()
    // The distinction the whole evidence vocabulary exists for: "we have no
    // key for this" must never read the same as "there is nothing there".
    expect(screen.getByText('not configured')).toBeInTheDocument()
    expect(screen.getByText('ok')).toBeInTheDocument()
  })

  it('reports the camera as readable text, not pixels in a shader', () => {
    hud()
    expect(screen.getByText('26.5000° N')).toBeInTheDocument()
    expect(screen.getByText('56.3000° E')).toBeInTheDocument()
    expect(screen.getByText('420 km')).toBeInTheDocument()
    // A negative heading is a compass bearing, not a minus sign.
    expect(screen.getByText('330°')).toBeInTheDocument()
  })

  it('puts southern and western hemispheres on the right side of zero', () => {
    hud({ camera: { lat: -33.9, lon: -70.6, alt: 900, heading: 0, pitch: -90 } })
    expect(screen.getByText('33.9000° S')).toBeInTheDocument()
    expect(screen.getByText('70.6000° W')).toBeInTheDocument()
    expect(screen.getByText('900 m')).toBeInTheDocument()
  })

  it('toggles a layer through the caller, owning no visibility state itself', () => {
    const props = hud()
    fireEvent.click(screen.getByRole('checkbox', { name: /Aircraft/ }))
    expect(props.onToggleLayer).toHaveBeenCalledWith('aircraft')
  })

  it('shows a tracked contact’s telemetry and says tracking places nothing', () => {
    hud({ tracked: aircraft })
    expect(screen.getByRole('heading', { name: 'UAE201' })).toBeInTheDocument()
    expect(screen.getByText('altitude ft')).toBeInTheDocument()
    expect(screen.getByText('37000')).toBeInTheDocument()
    expect(screen.getByText(/creates no geography/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'source' }))
      .toHaveAttribute('href', 'https://globe.adsb.lol/?icao=a1b2c3')
  })

  it('offers only the styles that compiled', () => {
    hud({ styles: ['none'] })
    expect(screen.getByRole('button', { name: /Natural/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /FLIR/ })).toBeNull()
  })

  it('hides the readout when the HUD is off but keeps the optics reachable', () => {
    hud({ hudVisible: false })
    expect(screen.getByRole('button', { name: /Natural/ })).toBeInTheDocument()
    expect(screen.queryByText('26.5000° N')).toBeNull()
  })
})
