import { type ReactNode, useEffect } from 'react'
import { useAppStore } from '../../stores/appStore.ts'
import './AppLayout.css'

interface AppLayoutProps {
  sidebar: ReactNode
  main: ReactNode
  rightPanel: ReactNode
  /** Home restyles the main pane around the scheme board, not a stream. */
  isHome?: boolean
  /** Once Home has a conversation, the table takes the column and the house caps. */
  homeTalking?: boolean
}

/**
 * Three-column cockpit on desktop; on small screens the rails become
 * slide-over drawers (WHY: below 1024px they used to be display:none with
 * no toggle at all — the PWA is the reach strategy, and every phone user
 * was locked out of memory, trading, stakes, everything).
 */
export function AppLayout({ sidebar, main, rightPanel, isHome = false, homeTalking = false }: AppLayoutProps) {
  const mobileDrawer = useAppStore((s) => s.mobileDrawer)
  const setMobileDrawer = useAppStore((s) => s.setMobileDrawer)

  // Destination-driven close lives in useRoomNavigation's successful
  // install (including branch changes); Escape and the scrim stay here.
  useEffect(() => {
    if (!mobileDrawer) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileDrawer(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileDrawer, setMobileDrawer])

  return (
    <div className={`app-layout${mobileDrawer ? ` drawer-open drawer-${mobileDrawer}` : ''}`}>
      <div className="app-sidebar">{sidebar}</div>
      <div className={`app-main${isHome ? ' app-main-home' : ''}${homeTalking ? ' app-main-home-talking' : ''}`}>{main}</div>
      <div className="app-right-panel">{rightPanel}</div>
      {mobileDrawer && (
        <div
          className="app-drawer-scrim"
          onClick={() => setMobileDrawer(null)}
          aria-hidden="true"
        />
      )}
    </div>
  )
}
