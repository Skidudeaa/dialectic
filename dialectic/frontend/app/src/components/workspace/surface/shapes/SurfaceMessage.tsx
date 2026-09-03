import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { MessageAnchor, MessageRef } from '../../../../types'
import { refGlyph, refKindLabel, type SurfaceMsg } from '../surfaceModel'
import './shapes.css'

export interface SurfaceMessageProps {
  msg: SurfaceMsg
  onOpenRef?: (ref: MessageRef) => void
  onReply?: (messageId: string) => void
  /** Tapping the anchor chip focuses that node on the graph. */
  onAnchor?: (anchor: MessageAnchor) => void
  /** Lanes: clamp body to ~3 lines, smaller type. */
  compact?: boolean
  dimmed?: boolean
}

const ROLE_WORD: Record<string, string> = { provoker: 'PROVOKER', annotator: 'ANNOTATOR' }

/**
 * One message on the working surface, shared by every shape (stream, tree,
 * lanes). Renders the SurfaceMsg view model directly — see surfaceModel.ts
 * for why the shapes never touch a raw Message.
 */
export function SurfaceMessage({ msg, onOpenRef, onReply, onAnchor, compact, dimmed }: SurfaceMessageProps) {
  // Same three-line idiom as MessageBubble.tsx: parse, then sanitize. No
  // mention decoration here — that context (room roster) is not part of the
  // surface view model.
  const html = useMemo(
    () => DOMPurify.sanitize(marked.parse(msg.text, { async: false }) as string),
    [msg.text],
  )
  const roleWord = msg.author.role ? ROLE_WORD[msg.author.role] : undefined

  return (
    <article
      className={`surf-msg${compact ? ' surf-msg-compact' : ''}${dimmed ? ' surf-msg-dimmed' : ''}`}
      data-mid={msg.id}
    >
      <div className="surf-meta">
        <span className="surf-glyph" aria-hidden="true">{msg.author.glyph}</span>
        <span className="surf-author">{msg.author.name}</span>
        {roleWord && <span className="surf-role">· {roleWord}</span>}
        <span className="surf-time">{msg.time}</span>
        {msg.isNew && <span className="surf-new">new</span>}
        {msg.anchor && (
          onAnchor ? (
            <button
              type="button"
              className="surf-anchor-chip"
              onClick={() => onAnchor(msg.anchor as MessageAnchor)}
            >
              ON {msg.anchor.label}
            </button>
          ) : (
            <span className="surf-anchor-chip">ON {msg.anchor.label}</span>
          )
        )}
        {onReply && (
          <button type="button" className="surf-reply-btn" onClick={() => onReply(msg.id)}>
            reply
          </button>
        )}
      </div>
      <div
        className={`surf-body${msg.isStreaming ? ' surf-body-streaming' : ''}`}
        dangerouslySetInnerHTML={{ __html: html }}
      />
      {msg.tools.length > 0 && (
        <div className="surf-tools">
          checked: {msg.tools.map((t) => `${t.label}${t.ok ? '' : ' (failed)'}`).join(' · ')}
        </div>
      )}
      {msg.refs.length > 0 && (
        <div className="surf-refs">
          {msg.refs.map((ref) => (
            <button
              key={`${ref.entity}:${ref.id}`}
              type="button"
              className="surf-ref-chip"
              title={refKindLabel(ref.entity)}
              onClick={() => onOpenRef?.(ref)}
            >
              {refGlyph(ref.entity)} {ref.label}
            </button>
          ))}
        </div>
      )}
    </article>
  )
}
