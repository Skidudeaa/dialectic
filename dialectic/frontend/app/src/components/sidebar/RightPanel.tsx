import { useEffect, useRef, useState } from 'react'
import type { ImplementedWorkspaceScene, Memory, ThreadNode } from '../../types'
import { useAppStore } from '../../stores/appStore.ts'
import { MemoryPanel } from './MemoryPanel'
import { ThreadPanel } from './ThreadPanel'
import { UsersPanel } from './UsersPanel'
import { SharePanel } from './SharePanel'
import { AnalyticsPanel } from '../analytics/AnalyticsPanel'
import { IdentityViewer } from '../analytics/IdentityViewer'
import { ReplayTimeline } from '../replay/ReplayTimeline'
import { CommitmentDashboard } from '../stakes/CommitmentDashboard'
import { HomeSettingsPanel } from '../home/HomeSettingsPanel'
import './RightPanel.css'

type TabId = 'users' | 'memory' | 'threads' | 'analytics' | 'stakes' | 'history' | 'identity' | 'share' | 'home'

interface RightPanelProps {
  memories: Memory[]
  genealogy: ThreadNode[]
  genealogyError: boolean
  onRetryGenealogy: () => void
  activeThreadId: string | null
  onThreadSelect: (threadId: string) => void
  onForkThread: () => void
  onAddMemory: (key: string, content: string) => void
  onSetMemoryPromotion: (memoryId: string, promoted: boolean) => Promise<void>
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
  isHome: boolean
  /** Which scene is open — the rail offers what that scene needs. */
  scene?: ImplementedWorkspaceScene
  canManageHome: boolean
  onMembershipChanged: () => void
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
  genealogy,
  genealogyError,
  onRetryGenealogy,
  activeThreadId,
  onThreadSelect,
  onForkThread,
  onAddMemory,
  onSetMemoryPromotion,
  roomId,
  roomToken,
  users,
  onCreateCommitment,
  onUpdateConfidence,
  onResolveCommitment,
  isHome,
  scene = 'record',
  canManageHome,
  onMembershipChanged,
}: RightPanelProps) {
  // WHY the tab lives in the store: a chat card (propose_thesis) has to be
  // able to open the Trading tab from outside this component.
  const storedTab = useAppStore((s) => s.rightPanelTab) as TabId
  const setActiveTab = useAppStore((s) => s.setRightPanelTab)
  const [prevHome, setPrevHome] = useState(isHome)
  const [picked, setPicked] = useState<TabId | null>(null)
  if (prevHome !== isHome) {
    setPrevHome(isHome)
    setPicked(null)
  }
  const chooseTab = (tab: TabId) => {
    if (isHome) setPicked(tab)
    setActiveTab(tab)
  }
  const requestedTab: TabId = isHome
    ? (picked ?? (storedTab === 'memory' || storedTab === 'share' ? 'home' : storedTab))
    : (storedTab === 'home' ? 'share' : storedTab)

  // WHAT THE RAIL GIVES UP, and why it is not a deletion.
  //
  // Release 2 moved three panels into the scenes that own them: the trading
  // panel became the Bench, memory became the Ledger, and commitments sit with
  // the thesis on the Bench. Leaving them here as well would render each twice
  // in one room — two trading panels, each with its own create-thesis form.
  // Design v2 §19.2 forbids a duplicate navigation system for exactly this
  // reason: two doors onto one thing is how the two come to disagree.
  //
  // Home keeps all of them, because Home has no workroom scenes to move them
  // into. It cannot bind a thesis (the API answers 409), so Trading is not
  // offered there at all — it never was, and a tab onto a refusal would be
  // worse than its absence.
  const OWNED_BY_A_SCENE: TabId[] = ['memory', 'stakes']

  // THE RAIL FOLLOWS THE SCENE. Some panels are about the room (who is here,
  // how to invite someone) and belong everywhere; others are about ONE scene
  // and were previously offered in all of them.
  //
  // Insights and History read the transcript, so they belong where the
  // transcript is. Dialectic's own papers are remembered material, which is the
  // Dossier's business (v2 7.7), so they sit with the Ledger. Branches is
  // navigation and stays room-wide alongside the left rail's tree.
  const SCENE_TABS: Partial<Record<ImplementedWorkspaceScene, TabId[]>> = {
    record: ['analytics', 'history'],
    ledger: ['identity'],
  }
  const ROOM_WIDE: TabId[] = ['users', 'threads', 'share']

  const roomTabs = isHome
    ? [
        { id: 'home' as TabId, label: 'House' },
        ...BASE_TABS.filter((tab) => tab.id !== 'share'),
      ]
    : BASE_TABS.filter((tab) => {
        if (OWNED_BY_A_SCENE.includes(tab.id)) return false
        if (ROOM_WIDE.includes(tab.id)) return true
        return (SCENE_TABS[scene] ?? []).includes(tab.id)
      })
  // Trading lives on the Bench now, and the Bench exists only outside Home.
  const tabs = roomTabs

  // The selected tab is PERSISTED, so it can name a panel this room no longer
  // offers — someone whose last tab was Memory arrives in an ordinary room
  // where the Ledger owns memory. Without this the tab vanishes from the bar
  // while its panel keeps rendering: a second memory panel, with no tab to
  // leave it by. Found in a screenshot; every assertion had passed.
  const activeTab: TabId = tabs.some((tab) => tab.id === requestedTab)
    ? requestedTab
    : (tabs[0]?.id ?? 'users')

  // Nine tabs overflow the rail, and the active one can sit clipped out of
  // sight (a card can select Trading from outside). Keep it in view.
  const activeTabRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    activeTabRef.current?.scrollIntoView({ inline: 'nearest', block: 'nearest' })
  }, [activeTab])

  return (
    <>
      <div className="sidebar-tabs">
        {tabs.map((tab, index) => (
          <span key={tab.id} className="sidebar-tab-slot">
            {isHome && index === 1 && <span className="sidebar-tab-break" aria-hidden="true" />}
            <button
              ref={tab.id === activeTab ? activeTabRef : null}
              className={`sidebar-tab-btn ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => chooseTab(tab.id)}
            >
              {tab.label}
            </button>
          </span>
        ))}
      </div>
      <div className="sidebar-panel active">
        {activeTab === 'users' && <UsersPanel users={users} />}
        {activeTab === 'memory' && (
          <MemoryPanel
            memories={memories}
            onAddMemory={onAddMemory}
            onSetMemoryPromotion={onSetMemoryPromotion}
            onOpenIdentity={() => chooseTab('identity')}
          />
        )}
        {activeTab === 'threads' && (
          <ThreadPanel
            genealogy={genealogy}
            genealogyError={genealogyError}
            onRetryGenealogy={onRetryGenealogy}
            activeThreadId={activeThreadId}
            onThreadSelect={onThreadSelect}
            onForkThread={onForkThread}
          />
        )}
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
        {activeTab === 'share' && !isHome && <SharePanel roomId={roomId} roomToken={roomToken} />}
        {activeTab === 'home' && isHome && (
          <HomeSettingsPanel
            canManageHome={canManageHome}
            onMembershipChanged={onMembershipChanged}
            residents={users}
            facts={memories.filter((memory) => memory.status === 'active' && !isSystemPaper(memory.key))}
            onOpenMemory={() => chooseTab('memory')}
          />
        )}
      </div>
    </>
  )
}

function isSystemPaper(key: string): boolean {
  const lower = key.toLowerCase()
  return lower.startsWith('llm_identity:')
    || lower.startsWith('user_model:')
    || lower === 'thesis_state_current'
    || lower.startsWith('thesis_state')
}
