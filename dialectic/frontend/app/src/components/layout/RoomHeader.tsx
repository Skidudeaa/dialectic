import type { Thread } from '../../types'
import { useAppStore } from '../../stores/appStore.ts'
import './RoomHeader.css'

interface RoomHeaderProps {
  roomName: string
  threads: Thread[]
  activeThreadId: string | null
  onThreadChange: (threadId: string) => void
  onProtocolClick: () => void
  onSettingsClick: () => void
  onSearchClick: () => void
  onHelpClick: () => void
  connected: boolean
  /** True when the current room IS Home — hides the Go Home action. */
  isHome: boolean
  onHomeClick: () => void
}

export function RoomHeader({ roomName, threads, activeThreadId, onThreadChange, onProtocolClick, onSettingsClick, onSearchClick, onHelpClick, connected, isHome, onHomeClick }: RoomHeaderProps) {
  // Drawer toggles only render on small screens (CSS) — they are the whole
  // route into the rails there, so they live on the store, not on props.
  const setMobileDrawer = useAppStore((s) => s.setMobileDrawer)
  const mobileDrawer = useAppStore((s) => s.mobileDrawer)
  // Home's root is the place, not a branch. The crumb returns once Home
  // actually has a fork — same control as every other room.
  const showBranchCrumb = !isHome || threads.length > 1
  return (
    <div className={`room-header${isHome ? ' room-header-home' : ''}`}>
      <div className="room-header-left">
        <button
          className="btn btn-ghost btn-sm drawer-toggle"
          onClick={() => setMobileDrawer(mobileDrawer === 'rooms' ? null : 'rooms')}
          title="Rooms"
          aria-label="Open room list"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 6h18M3 12h18M3 18h18"/>
          </svg>
        </button>
        {!isHome && (
          <button
            className="btn btn-ghost btn-sm home-action"
            onClick={onHomeClick}
            title="Go Home"
            aria-label="Go Home"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
            </svg>
            <span className="btn-label">Home</span>
          </button>
        )}
        {/* Room / Branch breadcrumb: the select IS the branch crumb, kept
            as the keyboard-friendly control. Both labels truncate
            independently instead of pushing the drawer toggles offscreen. */}
        <span className="room-title">{isHome ? 'Home' : roomName}</span>
        {showBranchCrumb && (
          <>
            <span className="crumb-sep" aria-hidden="true">/</span>
            <div className="thread-breadcrumb">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 01-9 9"/>
              </svg>
              <select
                value={activeThreadId ?? ''}
                onChange={e => onThreadChange(e.target.value)}
                aria-label="Branch"
              >
                {threads.map(t => (
                  <option key={t.id} value={t.id}>
                    {t.title ?? `Thread ${t.id.slice(0, 6)}`} ({t.message_count})
                  </option>
                ))}
              </select>
            </div>
          </>
        )}
      </div>
      <div className="room-header-right">
        <button className="btn btn-secondary btn-sm" onClick={onProtocolClick} title="Start a structured reasoning protocol" aria-label="Protocol">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 3v18M3 12h18"/>
          </svg>
          <span className="btn-label">Protocol</span>
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onSearchClick} title="Search this room (Cmd/Ctrl+K)">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/>
          </svg>
        </button>
        <button className="btn btn-ghost btn-sm" onClick={onSettingsClick} title="Settings">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
          </svg>
        </button>
        <button className="btn btn-secondary btn-sm" onClick={onHelpClick} title="Help — what can this room do?" aria-label="Help">
          <span className="btn-label">Help</span>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <path d="M6 9l6 6 6-6"/>
          </svg>
        </button>
        <div className="conn-status">
          <span className={`conn-dot ${connected ? 'connected' : ''}`} />
          <span className="conn-label">{connected ? 'Connected' : 'Offline'}</span>
        </div>
        <button
          className="btn btn-ghost btn-sm drawer-toggle"
          onClick={() => setMobileDrawer(mobileDrawer === 'panel' ? null : 'panel')}
          title="Cockpit — memory, trading, stakes"
          aria-label="Open cockpit panel"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="1"/><path d="M14 3v18"/>
          </svg>
        </button>
      </div>
    </div>
  )
}
