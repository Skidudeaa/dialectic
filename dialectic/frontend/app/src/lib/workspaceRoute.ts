// The room-and-scene route grammar, extracted from useRoomNavigation so scenes
// have a pure, testable seam.
//
// WHY it lives alone: `useRoomNavigation` remains the ONE destination writer, but
// the URL grammar itself is pure and must be provable without mounting a hook.
// Scene is the third axis here -- never in a second route module, which is how a
// second destination writer gets introduced by accident.
import type {
  ImplementedWorkspaceScene,
  RoomDestination,
  Thread,
  UserRoom,
  WorkspaceScene,
} from '../types'
import {
  isImplementedWorkspaceScene,
  isWorkspaceScene,
} from '../types'

export function destinationFromSearch(search: string): RoomDestination {
  const params = new URLSearchParams(search)
  const requestedScene = params.get('scene')
  return {
    roomId: params.get('room'),
    threadId: params.get('thread'),
    // An unknown scene name is dropped to null, not preserved: a typo or a
    // stale link resolves to the destination's default instead of 404-ing.
    scene: isWorkspaceScene(requestedScene) ? requestedScene : null,
  }
}

export function destinationFromLocation(
  location: Pick<Location, 'search'>,
): RoomDestination {
  return destinationFromSearch(location.search)
}

/** Home's root is the House; everywhere else the conversation is the default. */
export function defaultWorkspaceScene(
  room: Pick<UserRoom, 'is_home'>,
  thread: Pick<Thread, 'parent_thread_id'>,
): ImplementedWorkspaceScene {
  return room.is_home && thread.parent_thread_id === null
    ? 'house'
    : 'record'
}

/**
 * Resolve a requested scene against what this destination can actually show.
 *
 * Two distinct rejections, both landing on the destination's default:
 * an approved-but-unimplemented scene (`field`), and a scene that exists but
 * does not belong here (`house` outside Home's root -- the House is the
 * household view and an ordinary room has no house to show).
 */
export function resolveWorkspaceScene(
  room: Pick<UserRoom, 'is_home'>,
  thread: Pick<Thread, 'parent_thread_id'>,
  requested: WorkspaceScene | null | undefined,
): ImplementedWorkspaceScene {
  const fallback = defaultWorkspaceScene(room, thread)
  // Narrow a local, not the parameter: a type guard applied to the expression
  // `requested ?? null` narrows that expression, leaving `requested` itself the
  // full WorkspaceScene union — which does not satisfy the return type.
  const candidate = requested ?? null
  if (!isImplementedWorkspaceScene(candidate)) return fallback
  if (candidate === 'house' && fallback !== 'house') return fallback
  return candidate
}

export function destinationUrl(
  room: Pick<UserRoom, 'id' | 'is_home'>,
  thread: Pick<Thread, 'id' | 'parent_thread_id'>,
  scene: ImplementedWorkspaceScene = defaultWorkspaceScene(room, thread),
): string {
  // Only Home's root canonicalizes to bare `/`; a Home branch carries both ids,
  // and an ordinary room root is `/?room=<id>`. The default scene is OMITTED so
  // every URL that worked before this change still serializes identically.
  const rootHome = room.is_home && thread.parent_thread_id === null
  const defaultScene = defaultWorkspaceScene(room, thread)
  const params = new URLSearchParams()

  if (!rootHome) params.set('room', room.id)
  if (thread.parent_thread_id !== null) params.set('thread', thread.id)
  if (scene !== defaultScene) params.set('scene', scene)

  const query = params.toString()
  return query ? `/?${query}` : '/'
}
