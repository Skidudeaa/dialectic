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
      <p>Send this invite code privately. It grants access to this room.</p>
      <label className="share-field-label" htmlFor="dialectic-invite-code">Invite code</label>
      <div className="share-link-row share-invite-row">
        <textarea
          id="dialectic-invite-code"
          value={inviteCode}
          readOnly
          rows={3}
          aria-label="Dialectic invite code"
        />
        <button className="btn btn-secondary btn-sm" onClick={() => void handleCopy('invite', inviteCode)} disabled={!inviteCode}>
          {copied === 'invite' ? 'Copied!' : 'Copy Invite'}
        </button>
      </div>

      <div className="share-manual-fields">
        <div>
          <label className="share-field-label" htmlFor="dialectic-room-id">Room ID</label>
          <div className="share-link-row">
            <input id="dialectic-room-id" type="text" value={roomId} readOnly />
            <button className="btn btn-ghost btn-sm" onClick={() => void handleCopy('room', roomId)} disabled={!roomId}>
              {copied === 'room' ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
        <div>
          <label className="share-field-label" htmlFor="dialectic-room-token">Room token</label>
          <div className="share-link-row">
            <input id="dialectic-room-token" type="text" value={roomToken} readOnly />
            <button className="btn btn-ghost btn-sm" onClick={() => void handleCopy('token', roomToken)} disabled={!roomToken}>
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
