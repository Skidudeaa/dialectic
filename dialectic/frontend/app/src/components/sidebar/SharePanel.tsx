import { useCallback, useState } from 'react'
import './SharePanel.css'

interface SharePanelProps {
  roomToken: string
}

export function SharePanel({ roomToken }: SharePanelProps) {
  // SECURITY: Never put room tokens in shareable URLs.
  // Share the token directly (user copies it manually) — the join flow
  // uses a token input field, not a URL parameter.
  const [copied, setCopied] = useState(false)

  const handleCopyToken = useCallback(() => {
    if (roomToken) {
      navigator.clipboard.writeText(roomToken)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [roomToken])

  return (
    <div className="share-section">
      <p>Share this room token with someone to invite them:</p>
      <div className="share-link-row">
        <input type="password" value={roomToken} readOnly aria-label="Room token" />
        <button className="btn btn-secondary btn-sm" onClick={handleCopyToken}>
          {copied ? 'Copied!' : 'Copy Token'}
        </button>
      </div>
      <p className="share-hint">
        They can paste this token in the "Join Room" field.
      </p>
    </div>
  )
}
