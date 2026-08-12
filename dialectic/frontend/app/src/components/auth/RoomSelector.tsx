import { useCallback } from 'react'
import { useAppStore } from '../../stores/appStore.ts'
import { api } from '../../lib/api.ts'
import type { RoomNavigation } from '../../hooks/useRoomNavigation.ts'
import { RoomAccess } from './RoomAccess.tsx'
import './RoomSelector.css'

/**
 * Terminal full-screen wrapper around the shared RoomAccess surface —
 * rendered when no Home membership and no usable room exists (including
 * the guest invite path). Selection and grants both resolve through the
 * navigation hook passed in from AuthenticatedWorkspace.
 */
export function RoomSelector({ nav }: { nav: RoomNavigation }) {
  const user = useAppStore((s) => s.user)
  const refreshToken = useAppStore((s) => s.refreshToken)
  const logout = useAppStore((s) => s.logout)

  const handleLogout = useCallback(() => {
    if (refreshToken) void api.logoutSession(refreshToken).catch(() => undefined)
    logout()
  }, [refreshToken, logout])

  return (
    <div className="room-screen">
      <div className="room-card">
        <div className="room-header">
          <div>
            <h1 className="room-title">&#9671; Dialectic</h1>
            <p className="room-subtitle">
              Welcome, {user?.display_name ?? 'Guest'}
            </p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={handleLogout}>
            Sign Out
          </button>
        </div>

        {nav.error && <div className="room-error">{nav.error}</div>}
        {nav.accessError && <div className="room-error">{nav.accessError}</div>}
        {nav.loading && <p className="room-empty">Loading rooms...</p>}

        <RoomAccess
          mode="screen"
          rooms={nav.rooms}
          onRoomSelect={(destination) => nav.navigate(destination)}
          onRoomGranted={nav.enterGrantedRoom}
        />
      </div>
    </div>
  )
}
