import { type ReactNode, useEffect, useRef } from 'react'
import { useAppStore } from '../../stores/appStore.ts'
import type { ImplementedWorkspaceScene } from '../../types'
import './AppLayout.css'

interface AppLayoutProps {
  sidebar: ReactNode
  main: ReactNode
  rightPanel: ReactNode
  /** Home restyles the main pane around the scheme board, not a stream. */
  isHome?: boolean
  workspaceScene?: ImplementedWorkspaceScene
  /** Once Home has a conversation, the table takes the column and the house caps. */
  homeTalking?: boolean
}

/**
 * Three-column cockpit on desktop; on small screens the rails become
 * slide-over drawers (WHY: compact work surfaces used to reserve both rails,
 * no toggle at all — the PWA is the reach strategy, and every phone user
 * was locked out of memory, trading, stakes, everything).
 */
export function AppLayout({ sidebar, main, rightPanel, isHome = false, homeTalking = false, workspaceScene }: AppLayoutProps) {
  const mobileDrawer = useAppStore((s) => s.mobileDrawer)
  const setMobileDrawer = useAppStore((s) => s.setMobileDrawer)
  const rightPanelOpen = useAppStore((s) => s.rightPanelOpen)
  const layoutRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const viewport = window.visualViewport
    const layout = layoutRef.current
    if (!viewport || !layout || workspaceScene !== 'surface') return
    // Mobile keyboards can shrink the visual viewport without changing 100dvh.
    // Leave pinch zoom to the browser instead of reflowing the reading.
    const fit = () => {
      if (viewport.scale === 1) {
        layout.style.height = `${viewport.height + viewport.offsetTop}px`
        layout.classList.toggle('surface-short', viewport.height < 600)
      }
    }
    fit()
    viewport.addEventListener('resize', fit)
    viewport.addEventListener('scroll', fit)
    return () => {
      viewport.removeEventListener('resize', fit)
      viewport.removeEventListener('scroll', fit)
      layout.style.removeProperty('height')
      layout.classList.remove('surface-short')
    }
  }, [workspaceScene])

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
    <div ref={layoutRef} className={`app-layout right-panel-${rightPanelOpen ? 'open' : 'closed'}${mobileDrawer ? ` drawer-open drawer-${mobileDrawer}` : ''}`}>
      <div className="app-sidebar" id="room-list-panel">{sidebar}</div>
      <div className={`app-main${isHome ? ' app-main-home' : ''}${workspaceScene ? ` app-main-scene-${workspaceScene}` : ''}${homeTalking ? ' app-main-home-talking' : ''}`}>{main}</div>
      <div className="app-right-panel" id="context-panel">{rightPanel}</div>
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
