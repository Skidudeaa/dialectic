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
 */

const WINDOW_KEY = 'dialectic-scene-window'
const INSTALL_KEY = 'dialectic-scene-install'

interface StoredScene {
  userId: string | null
  roomId: string | null
  threadId: string | null
  scene: ImplementedWorkspaceScene | null
}

/** Storage throws in private modes and when quota is exhausted. Continuity is
 *  a convenience: it may never be the reason a boot fails. */
function safeRead(storage: Storage, key: string): StoredScene | null {
  try {
    const raw = storage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredScene | null
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
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
 * the one URL that silently does not work.
 */
export function isExplicitDestination(parsed: RoomDestination): boolean {
  return Boolean(parsed.roomId || parsed.threadId || parsed.scene)
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

/** Record what was actually installed, for this window and this installation. */
export function rememberScene(
  userId: string | null,
  destination: {
    roomId: string | null
    threadId: string | null
    scene: ImplementedWorkspaceScene | null
  },
): void {
  const entry: StoredScene = { userId, ...destination }
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
    return { roomId: null, threadId: null, scene: stored.scene ?? null }
  }
  // Restoration is only ever offered for a room the caller can already see.
  if (!rooms.some((candidate) => candidate.id === stored.roomId)) return null
  return {
    roomId: stored.roomId,
    threadId: stored.threadId ?? null,
    scene: stored.scene ?? null,
  }
}

/** Sign-out, on a device someone else may pick up next. */
export function forgetScene(): void {
  safeRemove(window.sessionStorage, WINDOW_KEY)
  safeRemove(window.localStorage, INSTALL_KEY)
}
