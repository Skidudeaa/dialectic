import { lazy, Suspense } from 'react'
import type { ComponentType } from 'react'
import type { ChartProps, Journey, EvidenceRow, Season } from '../longway/types'

export interface LegCardProps {
  journey: Journey
  index: number
  sources: Record<string, EvidenceRow>
  onDiscuss?: (slug: string, index: number) => void
}
export interface SeasonStripProps { season: Season | null; sources: Record<string, EvidenceRow> }
type ChartModule = {
  default: ComponentType<ChartProps>
  LegCard: ComponentType<LegCardProps>
  SeasonStrip: ComponentType<SeasonStripProps>
}

// The chart is independently owned. Vite resolves the absent module to a
// throwing virtual module until that worker's file arrives; no chart is copied
// or fabricated here. Keep the literal import so the real chart stays bundled
// in its own lazy chunk when integrated.
const load = (): Promise<ChartModule> =>
  // eslint-disable-next-line @typescript-eslint/ban-ts-comment -- expect-error would fail after the chart arrives.
  // @ts-ignore -- the independently delivered module is allowed to be absent.
  import('./chart/Chart').catch(() => ({
    default: () => <p role="status">Chart unavailable</p>,
    LegCard: () => <p role="status">Chart unavailable</p>,
    SeasonStrip: () => null,
  }))
const LazyChart = lazy(load)
const LazyLegCard = lazy(() => load().then(module => ({ default: module.LegCard })))
const LazySeasonStrip = lazy(() => load().then(module => ({ default: module.SeasonStrip })))
export default function Chart(props: ChartProps) {
  return <Suspense fallback={<p role="status">Chart loading</p>}><LazyChart {...props} /></Suspense>
}
export function LegCard(props: LegCardProps) {
  return <Suspense fallback={<p role="status">Chart loading</p>}><LazyLegCard {...props} /></Suspense>
}
export function SeasonStrip(props: SeasonStripProps) {
  return <Suspense fallback={<p role="status">Chart loading</p>}><LazySeasonStrip {...props} /></Suspense>
}
