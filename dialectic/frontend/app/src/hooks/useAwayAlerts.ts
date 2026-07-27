import { useEffect, useRef } from 'react'
import type { Message } from '../types'

interface AwayAlertsOptions {
  messages: Message[]
  currentUserId: string | null
  roomName: string
  /** False while the tab is in the foreground — alerts are pointless there. */
  isAway: boolean
  /** Suppresses the alert for the message currently being streamed in. */
  streamingMessageId?: string | null
}

function authorLabel(message: Message): string {
  if (message.speaker_type === 'llm_primary') return 'Claude'
  if (message.speaker_type === 'llm_provoker') return 'Claude (Provoker)'
  if (message.speaker_type === 'llm_annotator') return 'Claude (Annotator)'
  if (message.speaker_type === 'system') return 'System'
  return message.user_name ?? 'Someone'
}

function preview(content: string): string {
  const flat = content.replace(/\s+/g, ' ').trim()
  return flat.length > 120 ? `${flat.slice(0, 120)}…` : flat
}

/**
 * Tells you someone spoke while you were not looking.
 *
 * ARCHITECTURE: title badge (always) + Notification (when granted). Both are
 * driven off arrivals seen while the tab is backgrounded.
 * WHY: this room is used asynchronously — the two people in it are rarely at
 * their desks at the same time. Without this, the only way to discover that the
 * other person had replied was to go and look.
 * TRADEOFF: notifications need a permission the user may refuse; the title
 * badge is the floor that always works.
 */
export function useAwayAlerts({
  messages,
  currentUserId,
  roomName,
  isAway,
  streamingMessageId,
}: AwayAlertsOptions): void {
  // Messages already accounted for, so a re-render never re-alerts.
  const seenIdsRef = useRef<Set<string>>(new Set())
  const awayCountRef = useRef(0)
  const baseTitleRef = useRef<string>(typeof document === 'undefined' ? '' : document.title)
  const primedRef = useRef(false)

  useEffect(() => {
    // Prime with whatever is already loaded. Opening a room must not fire a
    // notification per message of existing history.
    if (!primedRef.current) {
      primedRef.current = true
      for (const message of messages) seenIdsRef.current.add(message.id)
      return
    }

    const fresh = messages.filter(
      (message) =>
        !seenIdsRef.current.has(message.id) &&
        message.id !== streamingMessageId &&
        // Your own messages are never news to you.
        message.user_id !== currentUserId,
    )
    for (const message of messages) seenIdsRef.current.add(message.id)

    if (!isAway || fresh.length === 0) return

    awayCountRef.current += fresh.length
    document.title = `(${awayCountRef.current}) ${baseTitleRef.current}`

    if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return
    const newest = fresh[fresh.length - 1]
    try {
      const notification = new Notification(`${authorLabel(newest)} · ${roomName}`, {
        body: preview(newest.content),
        // Collapses to one notification per room rather than stacking a wall of
        // them for a burst of messages.
        tag: `dialectic-${newest.thread_id}`,
        renotify: true,
      } as NotificationOptions)
      notification.onclick = () => {
        window.focus()
        notification.close()
      }
    } catch {
      // Some browsers reject constructed notifications outside a service worker.
      // The title badge above still carried the signal.
    }
  }, [messages, isAway, currentUserId, roomName, streamingMessageId])

  // Coming back clears the badge.
  useEffect(() => {
    if (isAway) return
    awayCountRef.current = 0
    document.title = baseTitleRef.current
  }, [isAway])

  // Never leave a stale badge on the tab after unmount.
  useEffect(() => () => { document.title = baseTitleRef.current }, [])
}
