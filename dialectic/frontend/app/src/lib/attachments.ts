import { api } from './api.ts'
import type { Attachment, AttachmentKind } from '../types/index.ts'

/**
 * ARCHITECTURE: client-side mirror of the server's upload policy, plus a
 * process-wide cache of object URLs for fetched attachment bytes.
 *
 * WHY mirror the policy: rejecting a 400MB .mov before it is uploaded is the
 * difference between an instant "too big" and four minutes of progress bar
 * ending in a 413. The server remains authoritative — everything here is a
 * courtesy, and a mismatch surfaces as the server's own error.
 *
 * WHY a module-level URL cache: /attachments/{id} needs both the room token and
 * the JWT, so the bytes must be fetched with headers and handed to the DOM as a
 * blob: URL. Those URLs leak for the lifetime of the document unless revoked,
 * and the same image appears in the bubble, in the lightbox, and again after a
 * re-render — one fetch per attachment, revoked when the room changes.
 */

// Mirrors MIME_POLICY in api/attachments.py.
const IMAGE_MIMES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'] as const
const VIDEO_MIMES = ['video/mp4', 'video/webm', 'video/quicktime'] as const
const FILE_MIMES = [
  'application/pdf', 'text/plain', 'text/csv', 'application/json', 'application/zip',
] as const

// Mirrors MIME_ALIASES: spellings browsers emit that mean an allowed type.
const MIME_ALIASES: Record<string, string> = {
  'image/jpg': 'image/jpeg',
  'image/pjpeg': 'image/jpeg',
  'application/x-zip-compressed': 'application/zip',
  'text/json': 'application/json',
}

const KIND_BY_MIME = new Map<string, AttachmentKind>([
  ...IMAGE_MIMES.map((m) => [m, 'image'] as const),
  ...VIDEO_MIMES.map((m) => [m, 'video'] as const),
  ...FILE_MIMES.map((m) => [m, 'file'] as const),
])

const MAX_BYTES: Record<AttachmentKind, number> = {
  image: 25 * 1024 * 1024,
  file: 25 * 1024 * 1024,
  video: 300 * 1024 * 1024,
}

/** The accept attribute for the file picker — same set, in the same order. */
export const ACCEPTED_MIME_ATTRIBUTE = [...IMAGE_MIMES, ...VIDEO_MIMES, ...FILE_MIMES].join(',')

export function normalizeMime(raw: string | undefined | null): string {
  if (!raw) return ''
  const mime = raw.split(';')[0].trim().toLowerCase()
  return MIME_ALIASES[mime] ?? mime
}

export function kindForMime(raw: string | undefined | null): AttachmentKind | null {
  return KIND_BY_MIME.get(normalizeMime(raw)) ?? null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

/**
 * Why this file cannot be uploaded, or null if it can.
 *
 * An empty `file.type` is a rejection rather than a maybe: the browser sends
 * exactly that value as the part's Content-Type, and the server has no sniffing
 * fallback for non-images — it would 415 after the whole body was sent.
 */
export function rejectionReason(file: File): string | null {
  const kind = kindForMime(file.type)
  if (!kind) {
    const label = file.type ? file.type : 'unrecognized type'
    return `${label} isn't supported`
  }
  if (file.size === 0) return 'File is empty'
  if (file.size > MAX_BYTES[kind]) {
    return `Too large — ${formatBytes(file.size)}, limit is ${formatBytes(MAX_BYTES[kind])}`
  }
  return null
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/**
 * Whether an id is safe to put in a message_ids query.
 *
 * WHY this matters more than it looks: the list endpoint 400s on a single
 * non-UUID, and it takes the WHOLE batch with it. One synthetic id — the
 * streaming placeholder, say — would silently cost every real message in the
 * window its attachments.
 */
export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value)
}

/**
 * Fold the endpoint's flat list into the shape the store keeps.
 *
 * The server returns records ordered created_at ASC, and pushing in that order
 * preserves it — several images on one message render in upload order.
 */
export function groupAttachmentsByMessage(records: Attachment[]): Record<string, Attachment[]> {
  const byMessage: Record<string, Attachment[]> = {}
  for (const record of records) {
    // Unbound rows are the uploader's in-flight state and are never returned
    // here; skipping defensively keeps a null out of the keyed map.
    if (!record.message_id) continue
    ;(byMessage[record.message_id] ??= []).push(record)
  }
  return byMessage
}

// --- object URL cache -------------------------------------------------------

const objectUrls = new Map<string, string>()
const inFlight = new Map<string, Promise<string>>()

/**
 * A blob: URL for an attachment's bytes, fetched once per attachment id.
 *
 * Concurrent callers (bubble + lightbox opening in the same frame) share the
 * one request rather than each downloading the file.
 */
export function attachmentObjectUrl(attachmentId: string): Promise<string> {
  const cached = objectUrls.get(attachmentId)
  if (cached) return Promise.resolve(cached)

  const pending = inFlight.get(attachmentId)
  if (pending) return pending

  const request = api.fetchAttachmentBlob(attachmentId)
    .then((blob) => {
      const url = URL.createObjectURL(blob)
      objectUrls.set(attachmentId, url)
      inFlight.delete(attachmentId)
      return url
    })
    .catch((error: unknown) => {
      // Not cached: a failure here is usually a transient auth or network
      // problem, and a retry should be allowed to succeed.
      inFlight.delete(attachmentId)
      throw error
    })

  inFlight.set(attachmentId, request)
  return request
}

/**
 * Release every cached URL. Called when the room changes or the session ends —
 * the bubbles holding these URLs unmount in the same commit, so nothing on
 * screen is left pointing at a revoked blob.
 */
export function revokeAttachmentUrls(): void {
  for (const url of objectUrls.values()) URL.revokeObjectURL(url)
  objectUrls.clear()
  inFlight.clear()
}

/** Save an attachment to disk under its original name. */
export async function downloadAttachment(attachmentId: string, fileName: string): Promise<void> {
  const url = await attachmentObjectUrl(attachmentId)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}
