import { useState } from 'react'
import type { Memory, Thread } from '../../types'
import { MemoryPanel } from './MemoryPanel'
import { ThreadPanel } from './ThreadPanel'
import { UsersPanel } from './UsersPanel'
import { SharePanel } from './SharePanel'
import './RightPanel.css'

type TabId = 'users' | 'memory' | 'threads' | 'share'

interface RightPanelProps {
  memories: Memory[]
  threads: Thread[]
  activeThreadId: string | null
  onThreadSelect: (threadId: string) => void
  onForkThread: () => void
  onAddMemory: (key: string, content: string) => void
  roomToken: string
  users: { id: string; name: string; status: string }[]
}

const TABS: { id: TabId; label: string }[] = [
  { id: 'users', label: 'Users' },
  { id: 'memory', label: 'Memory' },
  { id: 'threads', label: 'Threads' },
  { id: 'share', label: 'Share' },
]

export function RightPanel({ memories, threads, activeThreadId, onThreadSelect, onForkThread, onAddMemory, roomToken, users }: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('memory')

  return (
    <>
      <div className="sidebar-tabs">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`sidebar-tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="sidebar-panel active">
        {activeTab === 'users' && <UsersPanel users={users} />}
        {activeTab === 'memory' && <MemoryPanel memories={memories} onAddMemory={onAddMemory} />}
        {activeTab === 'threads' && <ThreadPanel threads={threads} activeThreadId={activeThreadId} onThreadSelect={onThreadSelect} onForkThread={onForkThread} />}
        {activeTab === 'share' && <SharePanel roomToken={roomToken} />}
      </div>
    </>
  )
}
