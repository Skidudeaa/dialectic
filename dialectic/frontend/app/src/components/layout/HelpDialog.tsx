import { useEffect } from 'react'
import { CapabilityMap } from './CapabilityMap'
import './HelpDialog.css'

interface HelpDialogProps {
  onClose: () => void
  /** The room whose real capabilities the map reads. */
  roomId: string
}

export function HelpDialog({ onClose, roomId }: HelpDialogProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="help-overlay" onClick={onClose}>
      <div className="help-dialog" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="Help">
        <div className="help-dialog-header">
          <div>
            <h2>What can this room do?</h2>
            <p>Read from this room, not written about it.</p>
          </div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close help">&times;</button>
        </div>

        <div className="help-body">
          <CapabilityMap roomId={roomId} />
        </div>
      </div>
    </div>
  )
}
