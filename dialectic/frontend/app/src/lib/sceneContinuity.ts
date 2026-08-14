import type { ImplementedWorkspaceScene, RoomDestination, UserRoom } from '../types'
import { entryDestination } from './workspaceRoute.ts'

/**
 * Device-local scene continuity (design v2 §15.2–15.5).
 *
 * ARCHITECTURE: this module PROPOSES a destination and never installs one.
 * `useRoomNavigation` remains the single destination writer — continuity that
 * wrote room or scene state itself would be exactly the second writer §5.7
 * forbids, and the two would fight at boot.
 *
 * NEVER SERVER-SIDE, never cross-device (§15.4). There is no API call in this
 * file and there must not be one: Mac state does not move Windows, and a
 * silent cross-device takeover is not allowed.
 *
 * TWO STORAGE TIERS, which is how window locality is expressed:
 *   - sessionStorage is per window and survives reload, so it IS the "stable
 *     window identity" the spec asks for. A window returns to where IT was.
 *   - localStorage is the installation's most recent scene, used when a window
 *     has no history of its own — a brand-new window or tab.
 *
 * NOT LEAKING A LOST ROOM (§E3): a restored candidate is checked against the
 * room list the caller already holds, so navigation is never ASKED for a room
 * it would have to refuse. That matters because refusal is visible — the
 * navigation hook surfaces "that room is no longer available to you" — and
 * saying that about a room the user did not request would announce that the
 * room exists and that they were removed from it. Restoration must be silent.
 *
 * PAYLOAD v2 (§15.2, Release 3 / TG-E): the stored record grew from four
 * fields (userId/roomId/threadId/scene) to include the rest of the exact
 * scene contract — selected workspace object, Focus/inspector state, scroll
 * positions, an open proposal, and the composer draft + reply target. A v1
 * blob (no `v`, written by a browser that never saw this release) restores
 * its original four fields and defaults everything else to null — NEVER a
 * parse failure. Continuity may never be the reason a boot fails; that rule
 * predates v2 (see safeRead below) and versioning must not weaken it.
 *
 * TWO WRITERS INTO THE SAME RECORD, deliberately: `rememberScene` is still
 * called by `useRoomNavigation` on every successful navigate (unchanged call
 * site, three fields) — it owns room/branch/scene, the destination axes the
 * ONE writer installs. The v2 axes below are not a *destination*; Focus
 * selection, a scroll offset or a composer draft don't move the URL, so nothing
 * about them belongs to the ONE destination writer, and threading them through
 * it would mean editing the file this module is explicitly walled off from.
 * `rememberSceneAxes` merge-patches them independently (App.tsx calls it
 * whenever one changes). `rememberScene` preserves whatever axes are already
 * on record for the SAME room+branch, and resets them to empty the moment
 * either changes — the per-room reset §5.5 asks for, enforced here as well as
 * in appStore.setRoom, so a stale draft or Focus selection can never survive
 * into a different room's restored scene.
 */

const WINDOW_KEY = 'dialectic-scene-window'
const INSTALL_KEY = 'dialectic-scene-install'

/** The non-destination half of the exact scene contract (§15.2). Every field
 *  defaults to null — both for a fresh window and for a v1 blob written
 *  before this release existed. */
export interface StoredSceneAxes {
  /** The workspace-object id selected into Focus — mirrors
   *  `RoomDestination.object` (types/index.ts, TG-B), but is not read from
   *  there: this module cannot import from the ONE destination writer's own
   *  state, so App.tsx mirrors `useRoomNavigation().objectId` in here. */
  objectId: string | null
  /** Focus/workbench mode. No writer exists yet (§7.7 will record this
   *  honestly as stored-but-not-yet-consumed) — the slot is real so a future
   *  consumer never has to touch this module again to use it. */
  focusMode: string | null
  /** Which Focus inspector panel/tab is open. Same status as focusMode. */
  inspectorTab: string | null
  /** Field scene scroll/viewport offset. Same status as focusMode. */
  fieldViewport: number | null
  /** Record scene scroll offset. Same status as focusMode. */
  recordScroll: number | null
  /** The open proposal or evidence review, if any. Same status as focusMode. */
  openProposal: string | null
  /** The composer's unsent text for this window. Restored end-to-end:
   *  App.tsx seeds it into MessageInput's `initialValue`, which the textarea
   *  consults once on first mount — so a restored draft appears in the box
   *  but can never clobber active typing. Stays local until sent (§15.5). */
  composerDraft: string | null
  /** The message id a reply is aimed at. Reconciled for free by the
   *  existing `replyTarget` lookup in App.tsx, which already drops a target
   *  that does not resolve against the loaded thread (§15.5). */
  replyToId: string | null
}

const EMPTY_AXES: StoredSceneAxes = {
  objectId: null,
  focusMode: null,
  inspectorTab: null,
  fieldViewport: null,
  recordScroll: null,
  openProposal: null,
  composerDraft: null,
  replyToId: null,
}

interface StoredScene extends StoredSceneAxes {
  v: 2
  userId: string | null
  roomId: string | null
  threadId: string | null
  scene: ImplementedWorkspaceScene | null
}

/** Coerce arbitrary parsed JSON into a v2 record, defaulting anything absent
 *  or malformed to null rather than throwing. Handles three inputs: a v1
 *  blob (no `v`), a v2 blob, and outright junk (rejected upstream by
 *  safeRead's try/catch, but a non-object survivor of JSON.parse — e.g. the
 *  literal `null` — still has to resolve to "nothing stored" here). */
function normalizeStored(raw: unknown): StoredScene | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const base = {
    userId: typeof r.userId === 'string' ? r.userId : null,
    roomId: typeof r.roomId === 'string' ? r.roomId : null,
    threadId: typeof r.threadId === 'string' ? r.threadId : null,
    scene: typeof r.scene === 'string' ? (r.scene as ImplementedWorkspaceScene) : null,
  }

  // A v1 blob (no `v`, or anything other than 2) restores its four original
  // fields and defaults the rest — never a parse failure (see module header).
  if (r.v !== 2) return { v: 2, ...base, ...EMPTY_AXES }

  const str = (value: unknown): string | null => (typeof value === 'string' ? value : null)
  const num = (value: unknown): number | null => (typeof value === 'number' ? value : null)
  return {
    v: 2,
    ...base,
    objectId: str(r.objectId),
    focusMode: str(r.focusMode),
    inspectorTab: str(r.inspectorTab),
    fieldViewport: num(r.fieldViewport),
    recordScroll: num(r.recordScroll),
    openProposal: str(r.openProposal),
    composerDraft: str(r.composerDraft),
    replyToId: str(r.replyToId),
  }
}

/** Storage throws in private modes and when quota is exhausted. Continuity is
 *  a convenience: it may never be the reason a boot fails. */
function safeRead(storage: Storage, key: string): StoredScene | null {
  try {
    const raw = storage.getItem(key)
    if (!raw) return null
    return normalizeStored(JSON.parse(raw))
  } catch {
    return null
  }
}

function safeWrite(storage: Storage, key: string, value: StoredScene): void {
  try {
    storage.setItem(key, JSON.stringify(value))
  } catch {
    // Nothing to recover: the next boot simply opens Home.
  }
}

function safeRemove(storage: Storage, key: string): void {
  try {
    storage.removeItem(key)
  } catch {
    // Nothing to recover.
  }
}

/**
 * Did the URL actually ask for something?
 *
 * A scene alone counts. `/?scene=record` is a person asking for the Record at
 * Home, and it has to outrank a restored House exactly as a room link does —
 * otherwise the one URL a user can type to override their restored scene is
 * the one URL that silently does not work. An object id counts too (§15.3
 * tier 1, "explicit object deep link" — ranked even above a room/branch
 * link): a `&object=` on the URL is a person pointing at one specific thing,
 * and restoring over it would silently discard the one axis they named.
 */
export function isExplicitDestination(parsed: RoomDestination): boolean {
  return Boolean(parsed.roomId || parsed.threadId || parsed.scene || parsed.object)
}

/**
 * The startup precedence, whole, in one place (§15.3):
 *
 *     deep link / notification  >  local restoration  >  Home → House
 *
 * `restored` must already be validated — see restoreScene.
 */
export function chooseEntryDestination(
  parsed: RoomDestination,
  restored: RoomDestination | null,
): RoomDestination {
  if (isExplicitDestination(parsed)) return entryDestination(parsed)
  if (restored) return restored
  return entryDestination(parsed)
}

/** Record what was actually installed, for this window and this installation.
 *
 *  Called by `useRoomNavigation` on every successful navigate — unchanged
 *  call site, three fields, exactly as before v2. The v2 axes are merged in
 *  from whatever is already on record for the SAME room+branch, and reset to
 *  empty the instant either changes, so a composer draft or a Focus
 *  selection can never bleed from one room's restored scene into another's
 *  (§5.5's per-room-reset rule, enforced here in storage as well as in
 *  appStore.setRoom for live state). */
export function rememberScene(
  userId: string | null,
  destination: {
    roomId: string | null
    threadId: string | null
    scene: ImplementedWorkspaceScene | null
  },
): void {
  const prior = safeRead(window.sessionStorage, WINDOW_KEY)
  const sameStop = Boolean(
    prior
    && prior.userId === userId
    && prior.roomId === destination.roomId
    && prior.threadId === destination.threadId,
  )
  const axes: StoredSceneAxes = sameStop && prior ? prior : EMPTY_AXES
  const entry: StoredScene = { v: 2, userId, ...destination, ...axes }
  safeWrite(window.sessionStorage, WINDOW_KEY, entry)
  safeWrite(window.localStorage, INSTALL_KEY, entry)
}

/**
 * Merge-patch one or more of the v2 axes onto whatever is currently
 * remembered for this window/installation, without touching room, branch or
 * scene — `rememberScene` above (called from the ONE destination writer)
 * still owns those. A no-op before anything has been remembered at all
 * (nothing to attach the patch to yet — `rememberScene` fires at least once
 * before ChatLayout, which is the only place App.tsx calls this from, can
 * mount).
 */
export function rememberSceneAxes(
  userId: string | null,
  patch: Partial<StoredSceneAxes>,
): void {
  const prior = safeRead(window.sessionStorage, WINDOW_KEY)
  if (!prior || prior.userId !== userId) return
  const entry: StoredScene = { ...prior, ...patch }
  safeWrite(window.sessionStorage, WINDOW_KEY, entry)
  safeWrite(window.localStorage, INSTALL_KEY, entry)
}

/**
 * The destination to restore, or null to fall through to Home → House.
 *
 * `rooms` is the caller's own loaded room list. A stored room absent from it
 * is dropped silently — see the leak note at the top of this file. A stored
 * Home root is still worth restoring, because the SCENE is part of it: Home +
 * Record is a place the user chose, and returning them to Home + House would
 * undo that choice on every reload.
 *
 * `object` rides along in the returned RoomDestination (TG-B already extended
 * the type and `useRoomNavigation.navigate` already installs whatever it is
 * given for this axis) — an unresolved object renders Focus's own
 * unavailable state rather than erroring (§15.5's "falls back to the nearest
 * valid parent"), so no extra validation belongs here.
 */
export function restoreScene(
  userId: string | null,
  rooms: UserRoom[],
): RoomDestination | null {
  const stored = safeRead(window.sessionStorage, WINDOW_KEY)
    ?? safeRead(window.localStorage, INSTALL_KEY)
  if (!stored) return null
  // A different signed-in identity on the same profile restores nothing: the
  // rooms would be refused anyway, and landing in someone else's last room is
  // not a thing to attempt.
  if ((stored.userId ?? null) !== (userId ?? null)) return null

  if (stored.roomId === null) {
    return {
      roomId: null, threadId: null, scene: stored.scene ?? null,
      object: stored.objectId ?? null,
    }
  }
  // Restoration is only ever offered for a room the caller can already see.
  if (!rooms.some((candidate) => candidate.id === stored.roomId)) return null
  return {
    roomId: stored.roomId,
    threadId: stored.threadId ?? null,
    scene: stored.scene ?? null,
    object: stored.objectId ?? null,
  }
}

/**
 * The v2 axes that are not part of a destination (§15.2) — Focus mode,
 * inspector tab, scroll positions, the open proposal, the composer draft and
 * reply target. Read independently of `restoreScene`: these ride alongside a
 * destination rather than being part of one, and `RoomDestination` (TG-B's
 * type) stays the pure room/branch/scene/object shape `useRoomNavigation`
 * installs. `objectId` is intentionally omitted — it already comes back
 * through `restoreScene`'s `object` field, and returning it twice would give
 * a caller two sources of truth for the same axis.
 */
export function restoreSceneAxes(
  userId: string | null,
): Omit<StoredSceneAxes, 'objectId'> | null {
  const stored = safeRead(window.sessionStorage, WINDOW_KEY)
    ?? safeRead(window.localStorage, INSTALL_KEY)
  if (!stored) return null
  if ((stored.userId ?? null) !== (userId ?? null)) return null
  return {
    focusMode: stored.focusMode,
    inspectorTab: stored.inspectorTab,
    fieldViewport: stored.fieldViewport,
    recordScroll: stored.recordScroll,
    openProposal: stored.openProposal,
    composerDraft: stored.composerDraft,
    replyToId: stored.replyToId,
  }
}

/** Sign-out, on a device someone else may pick up next. Clears every v2
 *  field along with the original four — both tiers hold ONE record each, so
 *  removing the keys removes the whole thing; there is no separate axes
 *  entry that could survive this. */
export function forgetScene(): void {
  safeRemove(window.sessionStorage, WINDOW_KEY)
  safeRemove(window.localStorage, INSTALL_KEY)
}
