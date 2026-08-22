import { useEffect, useState } from 'react'
import { CapabilityMap } from './CapabilityMap'
import { WhatsNewPanel } from './WhatsNewPanel'
import { useUnreadReleases } from '../../lib/releases.ts'
import './HelpDialog.css'

/**
 * The one place the product explains itself, in two tabs.
 *
 * WHY TWO TABS AND NOT TWO DIALOGS: they answer the same question a day apart.
 * "What can this do?" and "what changed since I last looked?" are the same
 * reader in the same moment, and a second modal would mean a second entry
 * point, a second Escape key and a second thing to discover. One door, two
 * shelves.
 *
 * WHY "What changed" CAN OPEN FIRST: the header badge counts unread entries,
 * and a badge that opens a dialog showing something else is a badge that lies
 * about what it is counting. `initialTab` is how the badge lands on its own
 * content.
 *
 * The tabs are real ARIA tabs rather than two styled links because that is what
 * they are; `role="tab"` with `aria-selected` and `aria-controls` is the whole
 * cost, and it buys the screen-reader announcement for free.
 */

export type HelpTab = 'room' | 'new'

interface HelpDialogProps {
  onClose: () => void
  /** The room whose real capabilities the map reads. */
  roomId: string
  /** Which shelf to open on. The badge passes 'new'. */
  initialTab?: HelpTab
}

const TITLES: Record<HelpTab, { heading: string; sub: string }> = {
  room: {
    heading: 'What can this room do?',
    sub: 'Read from this room, not written about it.',
  },
  new: {
    heading: 'What changed',
    sub: 'Recently shipped, and whether it is switched on.',
  },
}

export function HelpDialog({ onClose, roomId, initialTab = 'room' }: HelpDialogProps) {
  const [tab, setTab] = useState<HelpTab>(initialTab)
  const unread = useUnreadReleases()

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const title = TITLES[tab]

  return (
    <div className="help-overlay" onClick={onClose}>
      <div className="help-dialog" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="Help">
        <div className="help-dialog-header">
          <div>
            <h2>{title.heading}</h2>
            <p>{title.sub}</p>
          </div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close help">&times;</button>
        </div>

        <div className="help-tabs" role="tablist" aria-label="Help sections">
          <button
            type="button"
            role="tab"
            id="help-tab-room"
            aria-selected={tab === 'room'}
            aria-controls="help-panel-room"
            className={`help-tab${tab === 'room' ? ' is-active' : ''}`}
            onClick={() => setTab('room')}
          >
            This room
          </button>
          <button
            type="button"
            role="tab"
            id="help-tab-new"
            aria-selected={tab === 'new'}
            aria-controls="help-panel-new"
            className={`help-tab${tab === 'new' ? ' is-active' : ''}`}
            onClick={() => setTab('new')}
          >
            What changed
            {/* The count is TEXT inside the button, never a bare dot, so the
                accessible name reads "What changed 3" — the SceneSwitcher
                signal rule, for the same reason: a colour-only signal is no
                signal at all to half the people who need it. */}
            {unread > 0 && <span className="help-tab-count">{unread}</span>}
          </button>
        </div>

        <div className="help-body">
          {tab === 'room' ? (
            <div role="tabpanel" id="help-panel-room" aria-labelledby="help-tab-room">
              <CapabilityMap roomId={roomId} />
            </div>
          ) : (
            <div role="tabpanel" id="help-panel-new" aria-labelledby="help-tab-new">
              <WhatsNewPanel roomId={roomId} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
