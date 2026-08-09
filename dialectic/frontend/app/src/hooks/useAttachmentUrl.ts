import { useCallback, useEffect, useState } from 'react'
import { attachmentObjectUrl } from '../lib/attachments.ts'

interface AttachmentUrlState {
  url: string | null
  error: string | null
  /** Re-attempt after a failure; the cache does not memoize rejections. */
  retry: () => void
}

/**
 * The blob: URL for an attachment's bytes, fetched when `enabled` turns true.
 *
 * WHY the gate: a bubble scrolled past off-screen, and a 200MB video nobody
 * asked to watch, should not each cost a download. Callers pass visibility (for
 * images) or an explicit click (for video).
 */
export function useAttachmentUrl(attachmentId: string, enabled = true): AttachmentUrlState {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    attachmentObjectUrl(attachmentId)
      .then((next) => { if (!cancelled) setUrl(next) })
      .catch((cause: unknown) => {
        if (cancelled) return
        setError(cause instanceof Error ? cause.message : 'Could not load this attachment')
      })
    return () => { cancelled = true }
  }, [attachmentId, enabled, attempt])

  // Clearing the error here rather than in the effect keeps the write in an
  // event handler — a setState in the effect body cascades a render on every
  // attachment that mounts.
  const retry = useCallback(() => {
    setError(null)
    setAttempt((n) => n + 1)
  }, [])

  return { url, error, retry }
}
