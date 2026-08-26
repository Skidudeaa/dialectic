import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('cesium', () => {
  const color = { withAlpha: () => color }
  return {
    Color: {
      fromCssColorString: () => color,
      BLACK: color,
    },
    ImageryLayer: class {},
    OpenStreetMapImageryProvider: class {},
    Viewer: class {
      constructor(container: Element) {
        const panel = document.createElement('div')
        panel.className = 'cesium-widget-errorPanel'
        panel.textContent = 'Error constructing CesiumWidget.'
        container.append(panel)
        throw new Error('WebGL is unavailable')
      }
    },
  }
})

import WorldView from './WorldView.tsx'

describe('WorldView WebGL fallback', () => {
  it('removes Cesium partial error UI before exposing the complete text fallback', async () => {
    const { container } = render(
      <WorldView
        scopes={[]}
        signals={[]}
        initialCamera={null}
        onSelect={vi.fn()}
        onCameraSettle={vi.fn()}
      />,
    )

    expect(await screen.findByRole('status')).toHaveTextContent('The list below is the same map, in full.')
    expect(container.querySelector('.cesium-widget-errorPanel')).toBeNull()
    expect(container.querySelector('.world-canvas')).toBeEmptyDOMElement()
    expect(container.querySelector('.world-canvas')).toHaveAttribute('hidden')
  })
})
