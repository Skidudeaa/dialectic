import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { IDENTITY, ORGAN } from '../../organ'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import type { RoomNavigation } from '../../hooks/useRoomNavigation'
import { LongwayRoomAccess } from './LongwayRoomAccess'
if (ORGAN === 'longway') void import('./theme.css')

export function LongwayShell({ children }: { children: ReactNode }) {
  const [serverOrgan, setServerOrgan] = useState<string | null>(null)
  useEffect(() => {
    document.documentElement.dataset.organ = 'longway'
    const controller = new AbortController()
    void fetch('/organ', { signal: controller.signal }).then(r => r.ok ? r.json() : null)
      .then(data => { if (!controller.signal.aborted && typeof data?.organ === 'string') setServerOrgan(data.organ) }).catch(() => undefined)
    return () => { controller.abort(); delete document.documentElement.dataset.organ }
  }, [])
  return <>{serverOrgan && serverOrgan !== ORGAN && <p role="alert">This shell and server use different organs. Reload the matching app.</p>}{children}</>
}

export function LongwayRoomSelector({ nav }: { nav: RoomNavigation }) {
  const logout = useAppStore(s => s.logout)
  const refreshToken = useAppStore(s => s.refreshToken)
  return <div className="room-screen"><div className="room-card"><h1>{IDENTITY.name}</h1><p>{IDENTITY.lede}</p>
    <button onClick={() => { if (refreshToken) void api.logoutSession(refreshToken).catch(() => undefined); logout() }}>Sign Out</button>
    {(nav.error || nav.accessError) && <p role="alert">{nav.error ?? nav.accessError}</p>}
    <LongwayRoomAccess mode="screen" rooms={nav.rooms} onRoomSelect={destination => nav.navigate(destination)} onRoomGranted={nav.enterGrantedRoom} />
  </div></div>
}
