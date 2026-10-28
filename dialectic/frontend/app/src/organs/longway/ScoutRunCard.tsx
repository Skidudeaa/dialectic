import type { ScoutRunMetadata } from './types'

export function ScoutRunCard({ run, roomId }: { run: ScoutRunMetadata; roomId: string }) {
  return <p className="longway-scout-run">Scout read {run.pages_read} pages, filed {run.proposals} proposals, {run.counter_proposals} contrary findings · <a href={`/?${new URLSearchParams({ room: roomId, scene: 'field' })}`}>Open Field</a></p>
}
