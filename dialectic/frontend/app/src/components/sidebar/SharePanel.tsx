import { useCallback, useMemo, useState } from 'react'
import './SharePanel.css'

interface SharePanelProps {
  roomId: string
  roomToken: string
}

type CopyTarget = 'invite' | 'room' | 'token'

export function SharePanel({ roomId, roomToken }: SharePanelProps) {
  // SECURITY: The invite is an explicit secret, not a URL. That keeps the
  // room token out of browser history, referrer headers, and proxy logs.
  const inviteCode = useMemo(
    () => roomId && roomToken ? `dialectic-v1:${roomId}:${roomToken}` : '',
    [roomId, roomToken],
  )
  const [copied, setCopied] = useState<CopyTarget | null>(null)

  const handleCopy = useCallback(async (target: CopyTarget, value: string) => {
    if (!value) return
    await navigator.clipboard.writeText(value)
    setCopied(target)
    window.setTimeout(() => setCopied((current) => current === target ? null : current), 2000)
  }, [])

  return (
    <div className="share-section">
      <div className="share-module share-invite-module">
        <p>Send this invite code privately. It grants access to this room.</p>
        <label className="share-field-label" htmlFor="dialectic-invite-code">
          <svg className="share-label-glyph" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="8" cy="15" r="4" /><path d="m10.9 12.1 8.6-8.6" /><path d="m18 6 2.5 2.5" /><path d="m14.5 9.5 2 2" />
          </svg>
          Invite code
        </label>
        <div className="share-link-row share-invite-row">
          <textarea
            id="dialectic-invite-code"
            value={inviteCode}
            readOnly
            rows={3}
            aria-label="Dialectic invite code"
          />
          <button
            className={`btn btn-secondary btn-sm share-copy-btn${copied === 'invite' ? ' is-copied' : ''}`}
            onClick={() => void handleCopy('invite', inviteCode)}
            disabled={!inviteCode}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              {copied === 'invite'
                ? <polyline points="20 6 9 17 4 12" />
                : <><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>}
            </svg>
            {copied === 'invite' ? 'Copied!' : 'Copy Invite'}
          </button>
        </div>
      </div>

      <div className="share-manual-fields">
        <div>
          <label className="share-field-label" htmlFor="dialectic-room-id">Room ID</label>
          <div className="share-link-row">
            <input id="dialectic-room-id" type="text" value={roomId} readOnly />
            <button
              className={`btn btn-ghost btn-sm share-copy-btn${copied === 'room' ? ' is-copied' : ''}`}
              onClick={() => void handleCopy('room', roomId)}
              disabled={!roomId}
            >
              {copied === 'room' ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
        <div>
          <label className="share-field-label" htmlFor="dialectic-room-token">Room token</label>
          <div className="share-link-row">
            <input id="dialectic-room-token" type="text" value={roomToken} readOnly />
            <button
              className={`btn btn-ghost btn-sm share-copy-btn${copied === 'token' ? ' is-copied' : ''}`}
              onClick={() => void handleCopy('token', roomToken)}
              disabled={!roomToken}
            >
              {copied === 'token' ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
      </div>
      <p className="share-hint">
        Your collaborator can paste the complete code into “Join Room.” Room ID and token are shown separately for older clients.
      </p>
    </div>
  )
}
