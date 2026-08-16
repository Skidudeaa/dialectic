import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RightPanel } from './RightPanel'
import { useAppStore } from '../../stores/appStore.ts'

// Release 2 moved three panels into scenes: the trading panel became the Bench,
// memory became the Ledger, and commitments sit with the thesis on the Bench.
//
// The rail must give them up in the rooms where a scene now owns them, or the
// same panel renders twice — two trading panels, each with its own create-thesis
// form, in one room. Design v2 §19.2 forbids a duplicate navigation system for
// the same reason: two doors onto one thing is how the two disagree.
//
// Home keeps them, because Home has no workroom scenes to move them into: it
// cannot bind a thesis at all, and its facts are the household's.

const props = {
  memories: [], genealogy: [], genealogyError: false,
  onRetryGenealogy: vi.fn(), activeThreadId: null, onThreadSelect: vi.fn(),
  onForkThread: vi.fn(), onAddMemory: vi.fn(),
  onSetMemoryPromotion: vi.fn(async () => {}),
  roomId: 'r1', roomToken: 't', users: [],
  onCreateCommitment: vi.fn(), onUpdateConfidence: vi.fn(), onResolveCommitment: vi.fn(),
  canManageHome: false, onMembershipChanged: vi.fn(),
}

const tabNames = () =>
  screen.getAllByRole('tab')
    .map((b) => b.textContent?.trim())
    .filter(Boolean) as string[]

describe('RightPanel — the rail follows the scene', () => {
  it('offers the transcript\u2019s own tools while you are in the Record', () => {
    render(<RightPanel {...props} isHome={false} scene="record" />)
    const tabs = tabNames()
    // Insights and History are ABOUT the transcript — they belong where the
    // transcript is, not everywhere.
    expect(tabs).toContain('Insights')
    expect(tabs).toContain('History')
  })

  it('does not carry them into a scene they say nothing about', () => {
    const tabs = (scene: 'library' | 'bench') => {
      const { unmount } = render(<RightPanel {...props} isHome={false} scene={scene} />)
      const names = tabNames()
      unmount()
      return names
    }
    for (const scene of ['library', 'bench'] as const) {
      expect(tabs(scene)).not.toContain('Insights')
      expect(tabs(scene)).not.toContain('History')
    }
  })

  it('puts Dialectic\u2019s own papers with the Ledger, where remembered material lives', () => {
    // Design v2 7.7: the Dossier is how remembered material is presented, and
    // the identity papers are part of it.
    render(<RightPanel {...props} isHome={false} scene="ledger" />)
    expect(tabNames()).toContain('AI')
  })

  it('keeps Branches and Share in every scene — they are room-wide', () => {
    for (const scene of ['record', 'bench', 'library', 'ledger'] as const) {
      const { unmount } = render(<RightPanel {...props} isHome={false} scene={scene} />)
      expect(tabNames()).toContain('Branches')
      expect(tabNames()).toContain('Share')
      unmount()
    }
  })
})

describe('RightPanel — what the rail still owns', () => {
  it('gives up the panels a scene owns, in an ordinary room', () => {
    render(<RightPanel {...props} isHome={false} scene="record" />)
    const tabs = tabNames()
    expect(tabs).not.toContain('Trading')
    expect(tabs).not.toContain('Memory')
    expect(tabs).not.toContain('Stakes')
  })

  it('keeps what no scene has taken', () => {
    render(<RightPanel {...props} isHome={false} scene="record" />)
    const tabs = tabNames()
    // Branch navigation and sharing are room-wide, not scene-scoped.
    expect(tabs).toContain('Branches')
    expect(tabs).toContain('Share')
  })

  it('keeps every panel at Home, which has no workroom scene to hold them', () => {
    render(<RightPanel {...props} isHome scene="house" />)
    const tabs = tabNames()
    expect(tabs).toContain('Memory')
    expect(tabs).toContain('Stakes')
    expect(tabs).toContain('House')
  })

  it('renders no panel it no longer offers a tab for', () => {
    // The active tab is PERSISTED. Someone whose last tab was Memory lands in
    // an ordinary room where the Ledger now owns memory: the tab is gone from
    // the bar, but a stored value that still selects the panel renders it
    // anyway — a second memory panel with no tab to leave it by. Found in a
    // screenshot, not by a test, which is why this one exists.
    useAppStore.setState({ rightPanelTab: 'memory' })
    render(<RightPanel {...props} isHome={false} scene="record" />)
    expect(screen.queryByText(/Nothing remembered here yet/i)).not.toBeInTheDocument()
  })

  it('never offers Trading at Home — Home cannot bind a thesis', () => {
    // The API answers 409 there, so the tab would be a door onto a refusal.
    render(<RightPanel {...props} isHome scene="house" />)
    expect(tabNames()).not.toContain('Trading')
  })

  it('never offers the duplicate Users tab or falls back to it', () => {
    useAppStore.setState({ rightPanelTab: 'memory', rightPanelOpen: true })
    render(<RightPanel {...props} isHome={false} scene="record" />)
    expect(screen.queryByRole('tab', { name: 'Users' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Branches' })).toHaveClass('active')
    expect(screen.getByRole('tab', { name: 'Branches' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tabpanel', { name: 'Branches panel' })).toBeInTheDocument()
  })
})
