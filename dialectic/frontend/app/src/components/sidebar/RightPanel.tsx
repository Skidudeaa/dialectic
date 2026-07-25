import { useState, useMemo } from 'react'
import type { Memory, Thread } from '../../types'
import { useAppStore } from '../../stores/appStore.ts'
import { MemoryPanel } from './MemoryPanel'
import { ThreadPanel } from './ThreadPanel'
import { UsersPanel } from './UsersPanel'
import { SharePanel } from './SharePanel'
import { TradingPanel } from '../trading/TradingPanel'
import { AnalyticsPanel } from '../analytics/AnalyticsPanel'
import { IdentityViewer } from '../analytics/IdentityViewer'
import { ReplayTimeline } from '../replay/ReplayTimeline'
import { CommitmentDashboard } from '../stakes/CommitmentDashboard'
import './RightPanel.css'

type TabId = 'users' | 'memory' | 'threads' | 'analytics' | 'stakes' | 'history' | 'identity' | 'share' | 'trading'

interface RightPanelProps {
  memories: Memory[]
  threads: Thread[]
  activeThreadId: string | null
  onThreadSelect: (threadId: string) => void
  onForkThread: () => void
  onAddMemory: (key: string, content: string) => void
  roomId: string
  roomToken: string
  users: { id: string; name: string; status: string }[]
  onCreateCommitment: (
    claim: string,
    criteria: string,
    category?: string,
    deadline?: string,
    initialConfidence?: number,
  ) => void
  onUpdateConfidence: (commitmentId: string, confidence: number) => void
  onResolveCommitment: (commitmentId: string) => void
}

const BASE_TABS: { id: TabId; label: string }[] = [
  { id: 'users', label: 'Users' },
  { id: 'memory', label: 'Memory' },
  { id: 'threads', label: 'Branches' },
  { id: 'analytics', label: 'Insights' },
  { id: 'stakes', label: 'Stakes' },
  { id: 'history', label: 'History' },
  { id: 'identity', label: 'AI' },
  { id: 'share', label: 'Share' },
]

export function RightPanel({
  memories,
  threads,
  activeThreadId,
  onThreadSelect,
  onForkThread,
  onAddMemory,
  roomId,
  roomToken,
  users,
  onCreateCommitment,
  onUpdateConfidence,
  onResolveCommitment,
}: RightPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>('memory')
  const tradingConfig = useAppStore((s) => s.tradingConfig)

  const tabs = useMemo(() => {
    if (tradingConfig) {
      return [...BASE_TABS, { id: 'trading' as TabId, label: 'Trading' }]
    }
    return BASE_TABS
  }, [tradingConfig])

  return (
    <>
      <div className="sidebar-tabs">
        {tabs.map(tab => (
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
        {activeTab === 'analytics' && activeThreadId && <AnalyticsPanel key={activeThreadId} threadId={activeThreadId} roomId={roomId} />}
        {activeTab === 'stakes' && (
          <CommitmentDashboard
            key={roomId}
            roomId={roomId}
            onCreateCommitment={onCreateCommitment}
            onUpdateConfidence={onUpdateConfidence}
            onResolve={onResolveCommitment}
          />
        )}
        {activeTab === 'history' && <ReplayTimeline key={roomId} roomId={roomId} />}
        {activeTab === 'identity' && <IdentityViewer key={roomId} roomId={roomId} />}
        {activeTab === 'share' && <SharePanel roomId={roomId} roomToken={roomToken} />}
        {activeTab === 'trading' && <TradingPanel />}
      </div>
    </>
  )
}
