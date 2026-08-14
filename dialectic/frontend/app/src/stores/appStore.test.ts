import { afterEach, describe, expect, it } from 'vitest'
import { useAppStore } from './appStore'

const room = {
  id: 'room-1',
  name: 'Room One',
  token: 'room-token',
  is_home: false,
}

afterEach(() => {
  useAppStore.getState().logout()
})

describe('workspace scene state', () => {
  it('starts on Record before navigation resolves a destination', () => {
    expect(useAppStore.getState().workspaceScene).toBe('record')
  })

  it('stores a scene selected by the navigation transaction', () => {
    useAppStore.getState().setWorkspaceScene('house')
    expect(useAppStore.getState().workspaceScene).toBe('house')
  })

  it('resets to Record when a different room is installed', () => {
    useAppStore.getState().setWorkspaceScene('house')
    useAppStore.getState().setRoom(room, room.token)
    expect(useAppStore.getState().workspaceScene).toBe('record')
  })
})

describe('exact-restoration axes (§15.2, TG-E)', () => {
  it('start null before any restoration or interaction sets them', () => {
    const state = useAppStore.getState()
    expect(state.focusMode).toBeNull()
    expect(state.inspectorTab).toBeNull()
    expect(state.fieldViewport).toBeNull()
    expect(state.recordScroll).toBeNull()
    expect(state.openProposal).toBeNull()
  })

  it('each setter writes its own field and no other', () => {
    useAppStore.getState().setFocusMode('desktop')
    useAppStore.getState().setInspectorTab('sources')
    useAppStore.getState().setFieldViewport(240)
    useAppStore.getState().setRecordScroll(880)
    useAppStore.getState().setOpenProposal('proposal-1')
    const state = useAppStore.getState()
    expect(state.focusMode).toBe('desktop')
    expect(state.inspectorTab).toBe('sources')
    expect(state.fieldViewport).toBe(240)
    expect(state.recordScroll).toBe(880)
    expect(state.openProposal).toBe('proposal-1')
  })

  it('reset to null when a different room is installed — the bleed-across-rooms guard', () => {
    // Mutation target: remove this block of resets from setRoom's literal
    // (leave every other reset intact) and this test must go red, proving
    // the guard lives in setRoom and not somewhere these axes happen to be
    // untouched by coincidence.
    useAppStore.getState().setFocusMode('desktop')
    useAppStore.getState().setInspectorTab('sources')
    useAppStore.getState().setFieldViewport(240)
    useAppStore.getState().setRecordScroll(880)
    useAppStore.getState().setOpenProposal('proposal-1')

    useAppStore.getState().setRoom(room, room.token)

    const state = useAppStore.getState()
    expect(state.focusMode).toBeNull()
    expect(state.inspectorTab).toBeNull()
    expect(state.fieldViewport).toBeNull()
    expect(state.recordScroll).toBeNull()
    expect(state.openProposal).toBeNull()
  })

  it('are cleared on sign-out, same as every other per-room field', () => {
    useAppStore.getState().setFocusMode('desktop')
    useAppStore.getState().setOpenProposal('proposal-1')
    useAppStore.getState().logout()
    const state = useAppStore.getState()
    expect(state.focusMode).toBeNull()
    expect(state.openProposal).toBeNull()
  })
})
