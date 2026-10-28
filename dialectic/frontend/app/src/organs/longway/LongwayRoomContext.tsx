import type { ComponentProps } from 'react'
import { HomeSettingsPanel } from '../../components/home/HomeSettingsPanel'
import type { Thread } from '../../types'

export function LongwayRoomContext({ threads, onSelect, home }: {
  threads: Thread[]; onSelect: (id: string) => void; home?: ComponentProps<typeof HomeSettingsPanel>
}) {
  return <aside className="longway-room-context"><h2>Branches</h2>{threads.map(thread => <p key={thread.id}><button onClick={() => onSelect(thread.id)}>{thread.title ?? 'Record'}</button></p>)}{home && <HomeSettingsPanel {...home} />}</aside>
}
