import { useState } from 'react'
import type { Attachment } from '../../types'
import { useAttachmentUrl } from '../../hooks/useAttachmentUrl'
import { useInView } from '../../hooks/useInView'
import { downloadAttachment, formatBytes } from '../../lib/attachments'
import './MessageAttachments.css'

/**
 * ARCHITECTURE: media rendered from authenticated blob: URLs, never from a
 * direct src on /attachments/{id} — that endpoint requires the room token and
 * the JWT, so a bare <img src> renders a broken image for everyone.
 *
 * WHY images load on approach and video loads on demand: an image is bounded at
 * 25MB and is the thing you scrolled here to look at; a video is bounded at
 * 300MB and is not. Autoplaying a download of that size because a bubble
 * happened to scroll past is how a phone burns a data plan.
 */

/** Roughly the tallest an inline image gets before it owns the screen. */
const MAX_IMAGE_HEIGHT_PX = 360

interface Props {
  attachments: Attachment[]
}

export function MessageAttachments({ attachments }: Props) {
  if (attachments.length === 0) return null
  return (
    <div className="msg-attachments">
      {attachments.map((attachment) => {
        if (attachment.kind === 'image') {
          return <ImageAttachment key={attachment.id} attachment={attachment} />
        }
        if (attachment.kind === 'video') {
          return <VideoAttachment key={attachment.id} attachment={attachment} />
        }
        return <FileAttachment key={attachment.id} attachment={attachment} />
      })}
    </div>
  )
}

function ImageAttachment({ attachment }: { attachment: Attachment }) {
  const [ref, inView] = useInView<HTMLDivElement>()
  const { url, error, retry } = useAttachmentUrl(attachment.id, inView)

  // Reserve the space the image will occupy so arrival does not shove the
  // conversation down. Only possible when the server parsed the dimensions —
  // it returns null for an exotic or truncated header, and guessing is worse
  // than a placeholder that resizes once.
  const aspect = attachment.width && attachment.height
    ? attachment.width / attachment.height
    : null
  const placeholderStyle = aspect
    ? { aspectRatio: String(aspect), maxHeight: MAX_IMAGE_HEIGHT_PX, width: Math.min(MAX_IMAGE_HEIGHT_PX * aspect, 480) }
    : undefined

  return (
    <div className="attachment attachment-image" ref={ref}>
      {url ? (
        <a href={url} target="_blank" rel="noopener noreferrer" className="attachment-image-link">
          <img src={url} alt={attachment.original_name} className="attachment-image-img" />
        </a>
      ) : error ? (
        <button className="attachment-error" onClick={retry}>
          Couldn&rsquo;t load {attachment.original_name} — retry
        </button>
      ) : (
        <div className="attachment-placeholder" style={placeholderStyle} aria-busy="true">
          <span className="attachment-placeholder-label">{attachment.original_name}</span>
        </div>
      )}
    </div>
  )
}

function VideoAttachment({ attachment }: { attachment: Attachment }) {
  const [requested, setRequested] = useState(false)
  const { url, error, retry } = useAttachmentUrl(attachment.id, requested)

  if (!requested) {
    return (
      <button className="attachment attachment-video-poster" onClick={() => setRequested(true)}>
        <span className="attachment-glyph" aria-hidden="true">&#9654;</span>
        <span className="attachment-name">{attachment.original_name}</span>
        <span className="attachment-size">{formatBytes(attachment.bytes)} &middot; tap to load</span>
      </button>
    )
  }

  if (error) {
    return (
      <button className="attachment attachment-error" onClick={retry}>
        Couldn&rsquo;t load {attachment.original_name} — retry
      </button>
    )
  }

  if (!url) {
    return (
      <div className="attachment attachment-video-poster" aria-busy="true">
        <span className="attachment-glyph" aria-hidden="true">&#9654;</span>
        <span className="attachment-name">Loading {attachment.original_name}&hellip;</span>
      </div>
    )
  }

  return (
    <div className="attachment attachment-video">
      {/* preload="metadata" is nominal here — the bytes are already local by the
          time this mounts — but it keeps the element from decoding the whole
          file to show a first frame. */}
      <video className="attachment-video-el" src={url} controls preload="metadata" />
      <span className="attachment-caption">{attachment.original_name} &middot; {formatBytes(attachment.bytes)}</span>
    </div>
  )
}

function FileAttachment({ attachment }: { attachment: Attachment }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await downloadAttachment(attachment.id, attachment.original_name)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Download failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      className={`attachment attachment-file${error ? ' attachment-file-failed' : ''}`}
      onClick={() => { void save() }}
      disabled={busy}
      title={`Download ${attachment.original_name}`}
    >
      <span className="attachment-glyph" aria-hidden="true">&#9112;</span>
      <span className="attachment-name">{attachment.original_name}</span>
      <span className="attachment-size">
        {error ?? (busy ? 'saving…' : formatBytes(attachment.bytes))}
      </span>
    </button>
  )
}
