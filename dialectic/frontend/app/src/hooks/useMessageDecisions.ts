import { useCallback, useSyncExternalStore } from 'react'
import { api, type MessageDecisionExplain } from '../lib/api.ts'

/**
 * Decision provenance for every machine message in ONE thread — why the
 * participant produced it, never what it says.
 *
 * ARCHITECTURE: MessageBubble renders once per MESSAGE, and a thread can
 * hold dozens of machine messages, so a naive per-bubble fetch would be
 * dozens of round trips on every thread open — exactly what
 * GET /rooms/{room_id}/threads/{thread_id}/decisions is batched to avoid
 * (api/decisions.py). But nothing above MessageBubble in this build's
 * ownership fetches on its behalf the way App/MessageList do for field
 * marks (`marksByMessage` — "App builds it"), so the dedup has to live
 * INSIDE this hook: a module-level cache keyed by `${roomId}:${threadId}`,
 * with AT MOST one in-flight request per key. However many MessageBubbles
 * for the same thread call this hook, the network sees ONE request — the
 * first caller starts it, every other caller subscribes to the same
 * result.
 *
 * WHY useSyncExternalStore and not useState+useEffect: the cache is
 * mutated from OUTSIDE any single component's own lifecycle — a sibling
 * bubble's effect can populate it before this bubble's effect even runs —
 * and useSyncExternalStore is the API React ships for subscribing to a
 * store that changes off the render path, without reaching for the
 * set-state-in-effect pattern this repo already has one lint violation of
 * elsewhere (MessageList.tsx:247, unrelated to this work). Every write
 * REPLACES the per-key snapshot with a new object (setEntry below) rather
 * than mutating an existing one in place — useSyncExternalStore compares
 * snapshots by reference, so an in-place mutation would leave subscribers
 * unnotified.
 *
 * WHY per-thread and not per-room: a room can hold long-lived threads with
 * hundreds of messages; scoping the fetch to the thread actually open
 * keeps the response bounded to what is on screen.
 */

export type MessageDecisionsState =
  | { status: 'loading' }
  | { status: 'unavailable' }
  | { status: 'ready'; decisions: Record<string, MessageDecisionExplain> }

const LOADING: MessageDecisionsState = { status: 'loading' }
const UNAVAILABLE: MessageDecisionsState = { status: 'unavailable' }

interface CacheSlot {
  entry: MessageDecisionsState
  listeners: Set<() => void>
}

const cache = new Map<string, CacheSlot>()
const inFlight = new Set<string>()

function cacheKey(roomId: string, threadId: string): string {
  return `${roomId}:${threadId}`
}

function setEntry(key: string, entry: MessageDecisionsState): void {
  const slot = cache.get(key)
  if (!slot) return
  slot.entry = entry
  slot.listeners.forEach((listen) => listen())
}

/** Starts the request for `key` if (and only if) it has never resolved AND
 * nothing already has one outstanding. Always returns the slot so the
 * caller can subscribe to it regardless of which of those is true.
 *
 * WHY BOTH checks, not just `inFlight`: `.then().catch().finally()` is
 * three separate microtask ticks — `setEntry` (in `.then`/`.catch`) can
 * flip the slot to 'ready' one or two ticks BEFORE `.finally` clears
 * `inFlight`. A late-mounting bubble whose subscribe call lands in that
 * gap would see `inFlight` already empty and — with only that guard —
 * fire a second, wasted request for data the cache already has. Gating on
 * `slot.entry.status === 'loading'` too closes the gap: once a key
 * resolves (ready or unavailable) it is done for good, matching this
 * hook's contract that it never retries on its own.
 */
function ensureFetch(roomId: string, threadId: string): CacheSlot {
  const key = cacheKey(roomId, threadId)
  let slot = cache.get(key)
  if (!slot) {
    slot = { entry: LOADING, listeners: new Set() }
    cache.set(key, slot)
  }
  if (slot.entry.status === 'loading' && !inFlight.has(key)) {
    inFlight.add(key)
    api.getThreadDecisions(roomId, threadId)
      .then((decisions) => setEntry(key, { status: 'ready', decisions }))
      .catch(() => setEntry(key, UNAVAILABLE))
      .finally(() => inFlight.delete(key))
  }
  return slot
}

/**
 * @param roomId the current room, or null/undefined before one is known.
 * @param threadId the thread this message belongs to.
 * @param enabled pass `message.speaker_type !== 'human'` — a human message
 *   never has provenance to explain, and gating here (rather than at the
 *   call site conditionally invoking the hook) keeps the Rules of Hooks
 *   intact while still skipping the subscribe/fetch entirely for a thread
 *   that turns out to hold no machine messages at all.
 */
export function useMessageDecisions(
  roomId: string | null | undefined,
  threadId: string | null | undefined,
  enabled: boolean,
): MessageDecisionsState {
  const key = enabled && roomId && threadId ? cacheKey(roomId, threadId) : null

  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (!key || !roomId || !threadId) return () => {}
      const slot = ensureFetch(roomId, threadId)
      slot.listeners.add(onStoreChange)
      return () => {
        slot.listeners.delete(onStoreChange)
      }
    },
    // roomId/threadId are already folded into `key`; re-listed only so a
    // change to either without a `key` change (impossible today) still
    // resubscribes.
    [key, roomId, threadId],
  )

  const getSnapshot = useCallback((): MessageDecisionsState => {
    if (!key) return LOADING
    return cache.get(key)?.entry ?? LOADING
  }, [key])

  return useSyncExternalStore(subscribe, getSnapshot)
}

/**
 * Test-only escape hatch: drop every cached entry so one test's fetch
 * cannot leak into the next through the module-level cache. Same reason
 * llm/self_model.py exports reset_track_record_cache() and
 * llm/tradingdesk_client.py exports reset().
 */
export function __resetMessageDecisionsCacheForTests(): void {
  cache.clear()
  inFlight.clear()
}
