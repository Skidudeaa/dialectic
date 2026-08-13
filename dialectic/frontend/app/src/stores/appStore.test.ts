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
