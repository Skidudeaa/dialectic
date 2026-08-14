import { useCallback, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from 'react'
import type { Attachment, Message } from '../../types'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import { api } from '../../lib/api'
import { ACCEPTED_MIME_ATTRIBUTE, formatBytes, rejectionReason } from '../../lib/attachments'
import { ProposeMenu } from './ProposeMenu'
import './MessageInput.css'

type MessageType = Message['message_type']

/**
 * One file the composer is holding: picked, uploading, or uploaded and waiting
 * for the message that will carry it.
 *
 * WHY upload on selection rather than on send: the bytes take as long as they
 * take, and doing it while the user is still typing their caption is free
 * latency. By the time they hit Enter the blob is usually already on disk, and
 * all that remains is the bind.
 */
interface ComposerUpload {
  key: string
  file: File
  status: 'uploading' | 'ready' | 'failed'
  progress: number
  error?: string
  record?: Attachment
  controller?: AbortController
}

let uploadKeySeed = 0
const nextUploadKey = () => `upload-${++uploadKeySeed}`

interface MessageInputProps {
  onSend: (content: string, messageType: MessageType, attachments: Attachment[]) => boolean
  roomId: string
  onTypingStart?: () => void
  onTypingStop?: () => void
  onTypingContent?: (content: string) => void
  /** Research mode: sends the composer's text as a deep_dive question. When
   *  absent, no Research button renders. */
  onResearch?: (question: string) => boolean
  /** A dive is in flight for this room — the server refuses a second. */
  researchActive?: boolean
  disabled?: boolean
  replyTo?: { author: string; content: string } | null
  onCancelReply?: () => void
  placeholder?: string
  /** Home hides claim/question/definition — those are scheme-room speech acts. */
  quiet?: boolean
}

const MESSAGE_TYPES: { value: MessageType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'claim', label: 'Claim' },
  { value: 'question', label: 'Question' },
  { value: 'definition', label: 'Definition' },
]

export function MessageInput({ onSend, roomId, onTypingStart, onTypingStop, onTypingContent, onResearch, researchActive = false, disabled, replyTo, onCancelReply, placeholder = `Think out loud... paste a link and ${PARTICIPANT_NAME} reads it`, quiet = false }: MessageInputProps) {
  const [content, setContent] = useState('')
  const [messageType, setMessageType] = useState<MessageType>('text')
  const [sendError, setSendError] = useState(false)
  const [uploads, setUploads] = useState<ComposerUpload[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const typingRef = useRef(false)
  // Drag events fire for every child element crossed, so a plain leave handler
  // flickers the highlight off while the pointer is still over the composer.
  const dragDepthRef = useRef(0)

  const patchUpload = useCallback((key: string, patch: Partial<ComposerUpload>) => {
    setUploads((list) => list.map((entry) => (entry.key === key ? { ...entry, ...patch } : entry)))
  }, [])

  const startUpload = useCallback((key: string, file: File) => {
    const controller = new AbortController()
    patchUpload(key, { controller, status: 'uploading', progress: 0, error: undefined })

    api.uploadAttachment(roomId, file, {
      signal: controller.signal,
      onProgress: (percent) => patchUpload(key, { progress: percent }),
    })
      .then((record) => patchUpload(key, { status: 'ready', progress: 100, record }))
      .catch((cause: unknown) => {
        // An abort is the user removing the chip; the row is already gone.
        if (controller.signal.aborted) return
        patchUpload(key, {
          status: 'failed',
          error: cause instanceof Error ? cause.message : 'Upload failed',
        })
      })
  }, [patchUpload, roomId])

  const addFiles = useCallback((files: File[]) => {
    if (files.length === 0) return
    const accepted: ComposerUpload[] = []
    const refused: string[] = []

    for (const file of files) {
      // Pre-flight against the same policy the server enforces, so a 300MB
      // wrong-format video is refused instantly instead of after the upload.
      const reason = rejectionReason(file)
      if (reason) {
        refused.push(`${file.name} — ${reason}`)
        continue
      }
      accepted.push({ key: nextUploadKey(), file, status: 'uploading', progress: 0 })
    }

    setNotice(refused.length > 0 ? refused.join(' · ') : null)
    if (accepted.length === 0) return
    setUploads((list) => [...list, ...accepted])
    for (const entry of accepted) startUpload(entry.key, entry.file)
  }, [startUpload])

  // Aborting outside the updater: React may invoke a state updater twice, and a
  // reducer that fires network side effects is a trap for whoever reads it next.
  const removeUpload = useCallback((key: string) => {
    uploads.find((entry) => entry.key === key)?.controller?.abort()
    setUploads((list) => list.filter((entry) => entry.key !== key))
  }, [uploads])

  const retryUpload = useCallback((key: string) => {
    const entry = uploads.find((candidate) => candidate.key === key)
    if (entry) startUpload(key, entry.file)
  }, [uploads, startUpload])

  const uploading = uploads.filter((entry) => entry.status === 'uploading')
  const failed = uploads.filter((entry) => entry.status === 'failed')
  const ready = uploads.filter((entry): entry is ComposerUpload & { record: Attachment } =>
    entry.status === 'ready' && Boolean(entry.record))

  const handleSend = useCallback(() => {
    if (uploading.length > 0) {
      setNotice(`Still uploading ${uploading.length} file${uploading.length === 1 ? '' : 's'} — one moment.`)
      return
    }
    // Sending past a failed upload would drop it silently, and the chip would
    // outlive the message it was meant for. Make the user decide.
    if (failed.length > 0) {
      setNotice(`${failed[0].file.name} didn't upload — retry it or remove it.`)
      return
    }

    const trimmed = content.trim()
    // Empty content is legal exactly when files ride along — the server
    // accepts an attachment-only message and binds them in the send.
    if (!trimmed && ready.length === 0) return

    const sent = onSend(trimmed, messageType, ready.map((entry) => entry.record))
    // WHY: onSend returns false when the socket is not open. This used to be a
    // silent no-op — the text stayed in the box with no indication it had not
    // been delivered, which reads as "the app ate my message."
    if (!sent) {
      setSendError(true)
      return
    }
    setSendError(false)
    setNotice(null)
    setContent('')
    setUploads([])
    setMessageType('text')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    onTypingStop?.()
    typingRef.current = false
  }, [content, messageType, onSend, onTypingStop, uploading, failed, ready])

  // Research mode: the composer's text is the question, and the dive runs
  // long (the server caps it at 15 iterations / 300s), so the same send
  // guards apply — no attachments ride a question, text only.
  const handleResearch = useCallback(() => {
    if (!onResearch) return
    const trimmed = content.trim()
    if (!trimmed) {
      setNotice('Type the question first — Research sends what is in the composer.')
      return
    }
    const sent = onResearch(trimmed)
    // Same contract as onSend: false means the socket is not open, and the
    // text must stay put rather than read as eaten.
    if (!sent) {
      setSendError(true)
      return
    }
    setSendError(false)
    setNotice(null)
    setContent('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
    onTypingStop?.()
    typingRef.current = false
  }, [content, onResearch, onTypingStop])

  // Enter sends, Shift+Enter inserts a newline — the convention the hint text
  // has always claimed. Cmd/Ctrl+Enter stays supported for muscle memory.
  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== 'Enter') return
    if (e.shiftKey) return
    // A composing IME uses Enter to accept a candidate; sending there would cut
    // the word off mid-entry.
    if (e.nativeEvent.isComposing) return
    e.preventDefault()
    handleSend()
  }

  const handleInput = (value: string) => {
    setContent(value)
    onTypingContent?.(value)
    // Auto-resize
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px'
    }
    // Typing indicators
    if (value && !typingRef.current) {
      typingRef.current = true
      onTypingStart?.()
    } else if (!value && typingRef.current) {
      typingRef.current = false
      onTypingStop?.()
    }
  }

  // A screenshot on the clipboard arrives as a file with no text alongside it.
  // When text IS present the paste is a real paste and must not be swallowed.
  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    if (disabled) return
    const files = Array.from(e.clipboardData?.files ?? [])
    if (files.length === 0) return
    if (!e.clipboardData.types.includes('text/plain')) e.preventDefault()
    addFiles(files)
  }

  const handleDragEnter = (e: DragEvent<HTMLDivElement>) => {
    if (disabled) return
    if (!e.dataTransfer.types.includes('Files')) return
    dragDepthRef.current += 1
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setIsDragging(false)
  }

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (disabled) return
    if (!e.dataTransfer.types.includes('Files')) return
    // Without this the browser navigates away to the dropped file.
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    dragDepthRef.current = 0
    setIsDragging(false)
    if (disabled) return
    if (!e.dataTransfer.types.includes('Files')) return
    e.preventDefault()
    addFiles(Array.from(e.dataTransfer.files))
  }

  const hasSendable = content.trim().length > 0 || ready.length > 0

  return (
    <div className="input-area">
      <div
        className={`input-area-inner${isDragging ? ' input-dragging' : ''}`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        {replyTo && (
          <div className="reply-preview-bar active">
            <div className="reply-preview-text">
              <strong>{replyTo.author}</strong>
              <span>{replyTo.content}</span>
            </div>
            <button className="cancel-reply" onClick={onCancelReply}>&times;</button>
          </div>
        )}
        {uploads.length > 0 && (
          <div className="attach-chips">
            {uploads.map((entry) => (
              <div
                key={entry.key}
                className={`attach-chip attach-chip-${entry.status}`}
                title={entry.error ?? entry.file.name}
              >
                <span className="attach-chip-name">{entry.file.name}</span>
                <span className="attach-chip-size">
                  {entry.status === 'failed'
                    ? (entry.error ?? 'failed')
                    : entry.status === 'uploading'
                      ? `${entry.progress}%`
                      : formatBytes(entry.file.size)}
                </span>
                {entry.status === 'failed' && (
                  <button
                    className="attach-chip-retry"
                    onClick={() => retryUpload(entry.key)}
                    title="Retry this upload"
                  >
                    retry
                  </button>
                )}
                <button
                  className="attach-chip-remove"
                  onClick={() => removeUpload(entry.key)}
                  aria-label={`Remove ${entry.file.name}`}
                >
                  &times;
                </button>
                {entry.status === 'uploading' && (
                  <span className="attach-chip-progress" style={{ width: `${entry.progress}%` }} />
                )}
              </div>
            ))}
          </div>
        )}
        {!quiet && (
          <div className="msg-type-selector">
            {MESSAGE_TYPES.map(t => (
              <button
                key={t.value}
                className={`type-btn ${messageType === t.value ? 'active' : ''}`}
                onClick={() => setMessageType(t.value)}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        <div className="input-row">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_MIME_ATTRIBUTE}
            className="attach-input"
            onChange={(e) => {
              addFiles(Array.from(e.target.files ?? []))
              // Reset, or picking the same file twice in a row fires nothing.
              e.target.value = ''
            }}
          />
          <button
            className="attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            title="Attach an image, video, or file"
            aria-label="Attach a file"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
          <textarea
            ref={textareaRef}
            className="msg-textarea"
            placeholder={placeholder}
            rows={1}
            value={content}
            onChange={e => handleInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            disabled={disabled}
          />
          <button className="send-btn" onClick={handleSend} disabled={disabled || !hasSendable} title="Send (Enter)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
          {/* Home hides the propose surface too — theses, predictions and
              commitments are scheme-room speech acts (§5.3); Home cannot
              bind a thesis at all (see llm/tools.py propose_thesis). */}
          {!quiet && <ProposeMenu disabled={disabled} />}
          {onResearch && (
            <button
              className="research-btn"
              onClick={handleResearch}
              disabled={disabled || researchActive || content.trim().length === 0}
              title={researchActive ? 'A research dive is already running' : `Deep dive — ${PARTICIPANT_NAME} reads the sources and lands a brief (runs long)`}
            >
              {researchActive ? '✦ Researching…' : '✦ Research'}
            </button>
          )}
        </div>
        <div className="input-hints">
          {sendError ? (
            <span className="input-error" role="alert">
              Not connected — your message wasn&rsquo;t sent. It&rsquo;s still here; try again once you reconnect.
            </span>
          ) : notice ? (
            <span className="input-notice" role="status">{notice}</span>
          ) : (
            <span>
              Enter to send &middot; links get read &amp; fact-checked &middot;
              {onResearch ? ' ✦ Research = deep dive with sources' : ' paste or drop files'}
            </span>
          )}
          <span>? for shortcuts</span>
        </div>
      </div>
    </div>
  )
}
