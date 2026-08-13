// The room-route grammar, extracted whole from useRoomNavigation so scenes have
// a pure seam to extend. Behaviour is unchanged by this extraction: these are the
// same two functions the navigation transaction already used.
//
// WHY it lives alone: `useRoomNavigation` remains the ONE destination writer, but
// the URL grammar itself is pure and must be testable without mounting a hook.
// Later tasks add the scene axis to these exact functions -- never to a second
// route module, which is how two writers get introduced by accident.
import type { RoomDestination, Thread, UserRoom } from '../types'

export function destinationFromSearch(search: string): RoomDestination {
  const params = new URLSearchParams(search)
  return {
    roomId: params.get('room'),
    threadId: params.get('thread'),
  }
}

export function destinationFromLocation(
  location: Pick<Location, 'search'>,
): RoomDestination {
  return destinationFromSearch(location.search)
}

export function destinationUrl(
  room: Pick<UserRoom, 'id' | 'is_home'>,
  thread: Pick<Thread, 'id' | 'parent_thread_id'>,
): string {
  // Only Home's root canonicalizes to bare `/`; a Home branch carries both
  // ids, and an ordinary room root is `/?room=<id>`.
  const rootHome = room.is_home && thread.parent_thread_id === null
  if (rootHome) return '/'

  const params = new URLSearchParams({ room: room.id })
  if (thread.parent_thread_id !== null) params.set('thread', thread.id)
  return `/?${params.toString()}`
}
