// ThesisDag — read-only causal-DAG viewer for the trading Bench.
//
// Port of trading/frontend's GraphCanvas (hand-rolled SVG, wheel-zoom +
// drag-pan) stripped of every editing affordance: no node drag, no ports, no
// edge-draw, no marquee. This is a viewer, not the Builder.
//
// WHY viewBox-driven pan/zoom instead of a transform group (donor's
// approach): the donor's <svg> has a fixed pixel size and never resizes, so
// a CSS transform on an inner <g> is enough. This component's canvas is
// `width:100%` and must fit any structure's extent on first paint, so pan
// and zoom instead mutate the SVG viewBox itself — screen-to-user coordinate
// conversion goes through getScreenCTM(), which stays correct regardless of
// how the browser has scaled the responsive <svg>.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  WheelEvent as ReactWheelEvent,
} from 'react'
import type { ThesisStructure, ThesisStructureNode } from '../../types/trading'
import './ThesisDag.css'

interface ThesisDagProps {
  structure: ThesisStructure
  /** LIVE states from the snapshot — override structure node.state per id. */
  nodeStates?: Record<string, string>
  /** Snapshot backing nodeStates is stale — shown, never hidden. */
  stale?: boolean
}

const NODE_W = 180
const NODE_H = 56
const PADDING = 60
const PHASE_HEADER_SPACE = 30
const MIN_ZOOM = 0.4
const MAX_ZOOM = 2.5
const ZOOM_STEP = 1.25

type ViewBox = { x: number; y: number; w: number; h: number }
type DotVariant = 'filled' | 'ring' | 'x' | 'check' | 'dim'
type StateKey = 'fired' | 'approaching' | 'monitoring' | 'resolved' | 'invalidated' | 'neutral'

// Bucketed vocabulary adapted from the donor's TYPE_COLORS/STATE_DOT maps —
// td's node.state is an open-ish set ("fired", "triggered", "approaching",
// "warming", "monitoring", "stable", "resolved", "invalidated", ...), so
// this normalizes by keyword rather than exact match. Each bucket also gets
// a DISTINCT dot shape (filled / ring / x / check / small dot) so state is
// never color-only.
const STATE_META: Record<StateKey, { label: string; dot: DotVariant }> = {
  fired: { label: 'fired', dot: 'filled' },
  approaching: { label: 'approaching', dot: 'ring' },
  monitoring: { label: 'monitoring', dot: 'dim' },
  resolved: { label: 'resolved', dot: 'check' },
  invalidated: { label: 'invalidated', dot: 'x' },
  neutral: { label: 'unclassified', dot: 'dim' },
}

const LEGEND_ORDER: StateKey[] = ['fired', 'approaching', 'monitoring', 'resolved', 'invalidated']

function normalizeState(raw: string | undefined): StateKey {
  const s = (raw || '').toLowerCase()
  if (/fire|trigger/.test(s)) return 'fired'
  if (/approach|warm|near|pending/.test(s)) return 'approaching'
  if (/invalid|fail|dead|broken/.test(s)) return 'invalidated'
  if (/resolv|confirm|complete|done/.test(s)) return 'resolved'
  if (/monitor|stable|active|watch/.test(s)) return 'monitoring'
  return 'neutral'
}

function ellipsize(text: string, max: number): string {
  return text.length > max ? text.slice(0, Math.max(0, max - 1)) + '…' : text
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return ellipsize(JSON.stringify(value), 60)
  } catch {
    return String(value)
  }
}

function formatThresholds(thresholds: unknown[] | undefined): string {
  if (!thresholds || thresholds.length === 0) return 'none'
  const primitive = thresholds.every(
    (t) => typeof t === 'string' || typeof t === 'number' || typeof t === 'boolean',
  )
  if (thresholds.length <= 4 && primitive) return thresholds.map(String).join(', ')
  return `${thresholds.length} threshold${thresholds.length === 1 ? '' : 's'}`
}

// cascadePhases shape is open ("Record<string, unknown>" in trading.ts) —
// read defensively: a bare string, an object carrying name/label/title, or
// nothing at all (fall back to "Phase N").
function getPhaseLabel(phase: number, cascadePhases: Record<string, unknown> | undefined): string {
  const raw = cascadePhases?.[String(phase)]
  if (typeof raw === 'string' && raw.trim()) return raw
  if (raw && typeof raw === 'object') {
    const obj = raw as Record<string, unknown>
    const name = obj.name ?? obj.label ?? obj.title
    if (typeof name === 'string' && name.trim()) return name
  }
  return `Phase ${phase}`
}

function describeState(node: ThesisStructureNode, nodeStates: Record<string, string> | undefined): string {
  if (nodeStates) {
    if (Object.prototype.hasOwnProperty.call(nodeStates, node.id)) {
      const live = nodeStates[node.id]
      return live === node.state ? `${live} (live, matches authored)` : `${live} (live) — authored ${node.state}`
    }
    return `${node.state} (authored, no live reading)`
  }
  return `${node.state} (authored)`
}

function StateDot({ variant }: { variant: DotVariant }) {
  const cx = 14
  const cy = 14
  const r = 5
  switch (variant) {
    case 'filled':
      return <circle className="thesis-dag-dot thesis-dag-dot--filled" cx={cx} cy={cy} r={r} />
    case 'ring':
      return <circle className="thesis-dag-dot thesis-dag-dot--ring" cx={cx} cy={cy} r={r} fill="none" />
    case 'x':
      return (
        <g className="thesis-dag-dot thesis-dag-dot--x">
          <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} />
          <line x1={cx - r} y1={cy + r} x2={cx + r} y2={cy - r} />
        </g>
      )
    case 'check':
      return (
        <path
          className="thesis-dag-dot thesis-dag-dot--check"
          d={`M ${cx - r} ${cy} L ${cx - 1} ${cy + r - 1} L ${cx + r} ${cy - r + 1}`}
          fill="none"
        />
      )
    case 'dim':
    default:
      return <circle className="thesis-dag-dot thesis-dag-dot--dim" cx={cx} cy={cy} r={3.5} />
  }
}

function LegendGlyph({ variant }: { variant: DotVariant }) {
  return (
    <svg width="14" height="14" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
      <StateDot variant={variant} />
    </svg>
  )
}

function NodeDetailCard({
  node,
  stateDisplay,
  onClose,
}: {
  node: ThesisStructureNode
  stateDisplay: string
  onClose: () => void
}) {
  return (
    <div className="thesis-dag-detail" role="region" aria-label={`${node.label} detail`}>
      <div className="thesis-dag-detail-header">
        <h3 className="thesis-dag-detail-title">{node.label}</h3>
        <button type="button" className="thesis-dag-detail-close" aria-label="Close detail" onClick={onClose}>
          &times;
        </button>
      </div>
      <dl className="thesis-dag-detail-fields">
        <div className="thesis-dag-detail-row">
          <dt>Type</dt>
          <dd>{node.type}</dd>
        </div>
        <div className="thesis-dag-detail-row">
          <dt>Phase</dt>
          <dd>{node.phase}</dd>
        </div>
        <div className="thesis-dag-detail-row">
          <dt>State</dt>
          <dd>{stateDisplay}</dd>
        </div>
        {node.probability != null && (
          <div className="thesis-dag-detail-row">
            <dt>Probability</dt>
            <dd>{formatValue(node.probability)}</dd>
          </div>
        )}
        {node.current !== undefined && (
          <div className="thesis-dag-detail-row">
            <dt>Current</dt>
            <dd>{formatValue(node.current)}</dd>
          </div>
        )}
        <div className="thesis-dag-detail-row">
          <dt>Thresholds</dt>
          <dd>{formatThresholds(node.thresholds)}</dd>
        </div>
        {node.gatedBy && node.gatedBy.length > 0 && (
          <div className="thesis-dag-detail-row">
            <dt>Gated by</dt>
            <dd>{node.gatedBy.join(', ')}</dd>
          </div>
        )}
        {node.deadline && (
          <div className="thesis-dag-detail-row">
            <dt>Deadline</dt>
            <dd>
              {node.deadline}
              {node.countdown ? ' · counting down' : ''}
            </dd>
          </div>
        )}
        {node.context && (
          <div className="thesis-dag-detail-row thesis-dag-detail-row--context">
            <dt>Context</dt>
            <dd>{node.context}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}

export function ThesisDag({ structure, nodeStates, stale }: ThesisDagProps) {
  const nodes = useMemo(() => structure.nodes ?? [], [structure.nodes])
  const edges = useMemo(() => structure.edges ?? [], [structure.edges])
  const svgRef = useRef<SVGSVGElement>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const nodesById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  const { baseViewBox, graphMinY } = useMemo(() => {
    if (nodes.length === 0) {
      return { baseViewBox: { x: 0, y: 0, w: 400, h: 200 } as ViewBox, graphMinY: 0 }
    }
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    for (const n of nodes) {
      minX = Math.min(minX, n.x)
      minY = Math.min(minY, n.y)
      maxX = Math.max(maxX, n.x + NODE_W)
      maxY = Math.max(maxY, n.y + NODE_H)
    }
    return {
      baseViewBox: {
        x: minX - PADDING,
        y: minY - PADDING - PHASE_HEADER_SPACE,
        w: maxX - minX + PADDING * 2,
        h: maxY - minY + PADDING * 2 + PHASE_HEADER_SPACE,
      },
      graphMinY: minY,
    }
  }, [nodes])

  const [viewBox, setViewBox] = useState<ViewBox>(baseViewBox)

  // Re-fit whenever a different thesis is loaded (not on every position
  // tweak of the same structure — that would fight the user's own pan/zoom).
  useEffect(() => {
    setViewBox(baseViewBox)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [structure.id])

  const zoomBy = useCallback(
    (factor: number, anchor?: { x: number; y: number }) => {
      setViewBox((vb) => {
        const currentScale = baseViewBox.w / vb.w
        const nextScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, currentScale * factor))
        if (Math.abs(nextScale - currentScale) < 1e-6) return vb
        const newW = baseViewBox.w / nextScale
        const newH = baseViewBox.h / nextScale
        const ax = anchor ? anchor.x : vb.x + vb.w / 2
        const ay = anchor ? anchor.y : vb.y + vb.h / 2
        const newX = ax - (ax - vb.x) * (newW / vb.w)
        const newY = ay - (ay - vb.y) * (newH / vb.h)
        return { x: newX, y: newY, w: newW, h: newH }
      })
    },
    [baseViewBox],
  )

  const clientToUser = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current
    if (!svg) return { x: clientX, y: clientY }
    try {
      const ctm = svg.getScreenCTM()
      if (!ctm) return { x: clientX, y: clientY }
      const pt = svg.createSVGPoint()
      pt.x = clientX
      pt.y = clientY
      const transformed = pt.matrixTransform(ctm.inverse())
      return { x: transformed.x, y: transformed.y }
    } catch {
      return { x: clientX, y: clientY }
    }
  }, [])

  const handleWheel = useCallback(
    (e: ReactWheelEvent<SVGSVGElement>) => {
      e.preventDefault()
      const anchor = clientToUser(e.clientX, e.clientY)
      zoomBy(e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP, anchor)
    },
    [clientToUser, zoomBy],
  )

  // Drag state lives in a ref (not React state) so pointermove doesn't
  // re-render on every pixel; `moved` distinguishes a pan from a background
  // click (which should deselect).
  const dragRef = useRef<{ startX: number; startY: number; startVB: ViewBox; moved: boolean } | null>(null)

  const handleBackgroundPointerDown = useCallback(
    (e: ReactPointerEvent<SVGRectElement>) => {
      if (e.button !== 0) return
      ;(e.target as Element).setPointerCapture?.(e.pointerId)
      dragRef.current = { startX: e.clientX, startY: e.clientY, startVB: viewBox, moved: false }
    },
    [viewBox],
  )

  const handleBackgroundPointerMove = useCallback((e: ReactPointerEvent<SVGRectElement>) => {
    const d = dragRef.current
    if (!d) return
    const rect = svgRef.current?.getBoundingClientRect()
    const pxToUserX = rect && rect.width ? d.startVB.w / rect.width : 0
    const pxToUserY = rect && rect.height ? d.startVB.h / rect.height : 0
    const ddx = e.clientX - d.startX
    const ddy = e.clientY - d.startY
    if (Math.abs(ddx) > 2 || Math.abs(ddy) > 2) d.moved = true
    setViewBox({ ...d.startVB, x: d.startVB.x - ddx * pxToUserX, y: d.startVB.y - ddy * pxToUserY })
  }, [])

  const handleBackgroundPointerUp = useCallback((e: ReactPointerEvent<SVGRectElement>) => {
    const d = dragRef.current
    dragRef.current = null
    if (d && !d.moved) setSelectedId(null)
    ;(e.target as Element).releasePointerCapture?.(e.pointerId)
  }, [])

  const handleNodeKeyDown = useCallback((e: ReactKeyboardEvent<SVGGElement>, id: string) => {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
      e.preventDefault()
      setSelectedId(id)
    }
  }, [])

  // Escape closes the detail card from anywhere, not just while a node has
  // focus — the card itself has no focusable trap.
  useEffect(() => {
    if (!selectedId) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedId(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId])

  const phaseColumns = useMemo(() => {
    const byPhase = new Map<number, { minX: number; maxX: number }>()
    for (const n of nodes) {
      const cur = byPhase.get(n.phase)
      const minX = n.x
      const maxX = n.x + NODE_W
      if (!cur) byPhase.set(n.phase, { minX, maxX })
      else byPhase.set(n.phase, { minX: Math.min(cur.minX, minX), maxX: Math.max(cur.maxX, maxX) })
    }
    return Array.from(byPhase.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([phase, extent]) => ({
        phase,
        label: getPhaseLabel(phase, structure.cascadePhases),
        cx: (extent.minX + extent.maxX) / 2,
      }))
  }, [nodes, structure.cascadePhases])

  const edgePaths = useMemo(
    () =>
      edges
        .map((edge, i) => {
          const src = nodesById.get(edge.source)
          const tgt = nodesById.get(edge.target)
          if (!src || !tgt) return null
          const x1 = src.x + NODE_W
          const y1 = src.y + NODE_H / 2
          const x2 = tgt.x
          const y2 = tgt.y + NODE_H / 2
          const dx = Math.abs(x2 - x1) * 0.5
          const d = `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`
          const strength = typeof edge.strength === 'number' ? edge.strength : 0.5
          return { key: `${edge.source}->${edge.target}-${i}`, d, mx: (x1 + x2) / 2, my: (y1 + y2) / 2, strength, edge }
        })
        .filter((e): e is NonNullable<typeof e> => e !== null),
    [edges, nodesById],
  )

  const unknownLiveIds = useMemo(() => {
    if (!nodeStates) return [] as string[]
    return Object.keys(nodeStates).filter((id) => !nodesById.has(id))
  }, [nodeStates, nodesById])

  const selectedNode = selectedId ? nodesById.get(selectedId) ?? null : null

  return (
    <div className="thesis-dag" role="group" aria-label={`Causal DAG for ${structure.meta?.title ?? 'thesis'}`}>
      <div className="thesis-dag-toolbar">
        <div className="thesis-dag-legend">
          {LEGEND_ORDER.map((k) => (
            <span key={k} className="thesis-dag-legend-item">
              <LegendGlyph variant={STATE_META[k].dot} /> {STATE_META[k].label}
            </span>
          ))}
          {nodeStates && (
            <span className="thesis-dag-legend-item thesis-dag-legend-item--dimmed">
              <LegendGlyph variant="dim" /> no live reading
            </span>
          )}
        </div>
        <div className="thesis-dag-controls">
          <button type="button" className="thesis-dag-btn" aria-label="Zoom in" onClick={() => zoomBy(ZOOM_STEP)}>
            +
          </button>
          <button
            type="button"
            className="thesis-dag-btn"
            aria-label="Zoom out"
            onClick={() => zoomBy(1 / ZOOM_STEP)}
          >
            &minus;
          </button>
          <button
            type="button"
            className="thesis-dag-btn thesis-dag-btn--reset"
            aria-label="Reset view"
            onClick={() => setViewBox(baseViewBox)}
          >
            &#10021;
          </button>
        </div>
      </div>

      <div className="thesis-dag-canvas">
        {stale && <div className="thesis-dag-stale-badge">live colors from a stale snapshot</div>}
        <svg
          ref={svgRef}
          className="thesis-dag-svg"
          viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
          preserveAspectRatio="xMidYMid meet"
          onWheel={handleWheel}
        >
          <defs>
            <marker
              id="thesis-dag-arrow"
              markerWidth="10"
              markerHeight="8"
              refX="9"
              refY="4"
              orient="auto"
              markerUnits="userSpaceOnUse"
            >
              <polygon points="0 0, 10 4, 0 8" className="thesis-dag-arrow-head" />
            </marker>
          </defs>

          <rect
            className="thesis-dag-background"
            x={baseViewBox.x - 10000}
            y={baseViewBox.y - 10000}
            width={20000}
            height={20000}
            onPointerDown={handleBackgroundPointerDown}
            onPointerMove={handleBackgroundPointerMove}
            onPointerUp={handleBackgroundPointerUp}
            onPointerLeave={handleBackgroundPointerUp}
          />

          {phaseColumns.map(({ phase, label, cx }) => (
            <text key={phase} x={cx} y={graphMinY - 12} textAnchor="middle" className="thesis-dag-phase-label">
              {label}
            </text>
          ))}

          <g className="thesis-dag-edges">
            {edgePaths.map(({ key, d, mx, my, strength, edge }) => (
              <g key={key}>
                <path
                  d={d}
                  className="thesis-dag-edge-path"
                  strokeWidth={1 + strength * 2}
                  markerEnd="url(#thesis-dag-arrow)"
                />
                <title>
                  {edge.mechanism}
                  {edge.lag ? ` (${edge.lag})` : ''}
                </title>
                {edge.mechanism && (
                  <text x={mx} y={my - 6} textAnchor="middle" className="thesis-dag-edge-label">
                    {ellipsize(edge.mechanism, 30)}
                    {edge.lag ? ` · ${edge.lag}` : ''}
                  </text>
                )}
              </g>
            ))}
          </g>

          <g className="thesis-dag-nodes">
            {nodes.map((node) => {
              const hasLive = nodeStates ? Object.prototype.hasOwnProperty.call(nodeStates, node.id) : true
              const dimmed = nodeStates != null && !hasLive
              const effectiveRaw = hasLive && nodeStates ? nodeStates[node.id] : node.state
              const stateKey = normalizeState(effectiveRaw)
              const meta = STATE_META[stateKey]
              const isSelected = selectedId === node.id
              const label = ellipsize(node.label, 24)
              const ariaLabel = `${node.label}, ${meta.label}${dimmed ? ', authored only, no live reading' : ''}`
              return (
                <g
                  key={node.id}
                  role="button"
                  tabIndex={0}
                  aria-label={ariaLabel}
                  aria-pressed={isSelected}
                  transform={`translate(${node.x}, ${node.y})`}
                  className={[
                    'thesis-dag-node',
                    `thesis-dag-node--${stateKey}`,
                    dimmed ? 'thesis-dag-node--dimmed' : '',
                    isSelected ? 'thesis-dag-node--selected' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={(e) => {
                    e.stopPropagation()
                    setSelectedId(node.id)
                  }}
                  onKeyDown={(e) => handleNodeKeyDown(e, node.id)}
                >
                  <title>{node.label}</title>
                  <rect className="thesis-dag-node-rect" width={NODE_W} height={NODE_H} rx={4} />
                  <StateDot variant={meta.dot} />
                  <text className="thesis-dag-node-type" x={NODE_W - 8} y={14} textAnchor="end">
                    {node.type}
                  </text>
                  <text className="thesis-dag-node-label" x={NODE_W / 2} y={30} textAnchor="middle">
                    {label}
                  </text>
                  <text className="thesis-dag-node-phase" x={NODE_W / 2} y={46} textAnchor="middle">
                    P{node.phase} &middot; {meta.label}
                  </text>
                </g>
              )
            })}
          </g>
        </svg>
      </div>

      {unknownLiveIds.length > 0 && (
        <p className="thesis-dag-footnote">
          live state for {unknownLiveIds.length} unknown node{unknownLiveIds.length === 1 ? '' : 's'}:{' '}
          {unknownLiveIds.join(', ')} &mdash; structure may be mid-edit
        </p>
      )}

      {selectedNode && (
        <NodeDetailCard
          node={selectedNode}
          stateDisplay={describeState(selectedNode, nodeStates)}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  )
}
