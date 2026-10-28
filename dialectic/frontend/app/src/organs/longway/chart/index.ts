import { lazy } from 'react'

// The shell may import the cards eagerly without pulling MapLibre into its entry.
export { LegCard, SeasonStrip, JourneyStrip } from './Cards'
export default lazy(() => import('./Chart'))
