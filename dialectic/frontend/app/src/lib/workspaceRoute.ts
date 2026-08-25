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
    // Unlike scene, an object id has no closed vocabulary to validate against
    // here — resolving whether it exists is a room-scoped question this pure
    // module cannot answer. An id that does not resolve is Focus's own
    // unavailable state (§1.18), never dropped silently like an unknown scene.
    object: params.get('object'),
    messageId: params.get('message'),
    // Like `object`, no closed vocabulary here: a view the scene cannot
    // decode is the scene's own default, never a 404.
    view: params.get('view'),
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
 * Every scene this destination may show, in switcher order, default first.
 *
 * THE ONE DEFINITION. The router (resolveWorkspaceScene) and the frame
 * (WorkspaceSceneFrame) both read it, because they used to answer the same
 * question separately -- the router rejected `house` outside Home root and the
 * frame independently hardcoded the same rule. Two copies of one rule is
 * exactly how the participant name drifted three ways; the router must never
 * accept a scene the switcher will not offer, or a URL can install a place with
 * no way back to it.
 *
 * WHY Home root gets only House and Record: Home coordinates, scheme rooms own
 * scheme work (design v2 §5.5). Home cannot bind a thesis -- the API answers
 * 409 -- so a Bench there would be a door onto a refusal. A branch off Home is
 * an ordinary conversation and carries no household at all.
 *
 * WHY an ordinary room offers all five even when empty: a Bench with no thesis
 * is where a thesis is CREATED, and a Library with no readings is where the
 * first one is explained. Hiding a scene until it has content is how the
 * trading panel once made its own create flow unreachable. The Field is the
 * same shape: an empty Field teaches what lands there (SceneEmpty's contract)
 * rather than staying unreachable until the inference job has something to
 * show. Home root does not get it — Home holds no Field (§5.2).
 */
export function scenesForDestination(
  room: Pick<UserRoom, 'is_home'>,
  thread: Pick<Thread, 'parent_thread_id'>,
): readonly ImplementedWorkspaceScene[] {
  if (room.is_home) {
    return thread.parent_thread_id === null
      ? (['house', 'atlas', 'mirror', 'record'] as const)
      : (['record'] as const)
  }
  return ['record', 'bench', 'field', 'library', 'ledger'] as const
}

/**
 * Resolve a requested scene against what this destination can actually show.
 *
 * Two distinct rejections, both landing on the destination's default: an
 * approved-but-unimplemented scene (`field`), and an implemented scene that
 * does not belong here (`bench` at Home root).
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
  if (!scenesForDestination(room, thread).includes(candidate)) return fallback
  return candidate
}

export function destinationUrl(
  room: Pick<UserRoom, 'id' | 'is_home'>,
  thread: Pick<Thread, 'id' | 'parent_thread_id'>,
  scene: ImplementedWorkspaceScene = defaultWorkspaceScene(room, thread),
  object: string | null = null,
  message: string | null = null,
  view: string | null = null,
): string {
  // Only Home's root canonicalizes to bare `/`; a Home branch carries both ids,
  // and an ordinary room root is `/?room=<id>`. The default scene is OMITTED so
  // every URL that worked before this change still serializes identically.
  const rootHome = room.is_home && thread.parent_thread_id === null
  const defaultScene = defaultWorkspaceScene(room, thread)
  const params = new URLSearchParams()

  if (!rootHome || message) params.set('room', room.id)
  // A message makes even the root thread an explicit destination. Omitting it
  // loses the message axis when the URL is reloaded or traversed via history.
  if (thread.parent_thread_id !== null || message) params.set('thread', thread.id)
  if (scene !== defaultScene) params.set('scene', scene)
  if (object) params.set('object', object)
  if (message) params.set('message', message)
  if (view) params.set('view', view)

  const query = params.toString()
  return query ? `/?${query}` : '/'
}

/**
 * Normalize a parsed URL into the destination that entry paths install.
 *
 * WHY this exists as a named function: boot and popstate both fell back to a
 * literal `{ roomId: null, threadId: null }` for the Home root, which silently
 * DROPPED a requested scene — so `/?scene=record` reloaded into House and
 * Back/Forward could not return to Record. The scene has to survive the
 * fallback, and both call sites have to agree on that.
 */
export function entryDestination(parsed: RoomDestination): RoomDestination {
  if (parsed.roomId) return parsed
  return {
    roomId: null,
    threadId: null,
    scene: parsed.scene ?? null,
    object: parsed.object ?? null,
    messageId: parsed.messageId ?? null,
    view: parsed.view ?? null,
  }
}
