import { type ReactNode } from 'react'
import './AppLayout.css'

interface AppLayoutProps {
  sidebar: ReactNode
  main: ReactNode
  rightPanel: ReactNode
}

export function AppLayout({ sidebar, main, rightPanel }: AppLayoutProps) {
  return (
    <div className="app-layout">
      <div className="app-sidebar">{sidebar}</div>
      <div className="app-main">{main}</div>
      <div className="app-right-panel">{rightPanel}</div>
    </div>
  )
}
