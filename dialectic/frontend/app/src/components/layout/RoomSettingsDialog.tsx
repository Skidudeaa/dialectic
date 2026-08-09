import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import './RoomSettingsDialog.css'

interface RoomSettings {
  interjection_turn_threshold: number
  semantic_novelty_threshold: number
  auto_interjection_enabled: boolean
}

interface RoomSettingsDialogProps {
  roomId: string
  onClose: () => void
}

export function RoomSettingsDialog({ roomId, onClose }: RoomSettingsDialogProps) {
  const [settings, setSettings] = useState<RoomSettings | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.getSettings(roomId)
      .then((data) => setSettings(data as RoomSettings))
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load settings'))
  }, [roomId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const handleSave = async () => {
    if (!settings) return
    setSaving(true)
    setError('')
    try {
      const updated = await api.updateSettings(roomId, settings) as RoomSettings
      setSettings(updated)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-dialog" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="Room settings">
        <div className="settings-dialog-header">
          <div>
            <h2>Room intelligence</h2>
            <p>Choose how actively Claude joins this room.</p>
          </div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close settings">&times;</button>
        </div>

        {error && <div className="settings-error">{error}</div>}
        {!settings ? (
          <div className="settings-loading">Loading settings...</div>
        ) : (
          <div className="settings-fields">
            <label className="settings-toggle">
              <input
                type="checkbox"
                checked={settings.auto_interjection_enabled}
                onChange={(event) => setSettings({ ...settings, auto_interjection_enabled: event.target.checked })}
              />
              <span>
                <strong>Automatic participation</strong>
                <small>Claude can join without being explicitly mentioned.</small>
              </span>
            </label>

            <label>
              Turns before Claude considers joining: <strong>{settings.interjection_turn_threshold}</strong>
              <input
                type="range"
                min="2"
                max="12"
                value={settings.interjection_turn_threshold}
                onChange={(event) => setSettings({ ...settings, interjection_turn_threshold: Number(event.target.value) })}
              />
            </label>

            <label>
              Topic-shift sensitivity: <strong>{Math.round(settings.semantic_novelty_threshold * 100)}%</strong>
              <input
                type="range"
                min="0.3"
                max="0.95"
                step="0.05"
                value={settings.semantic_novelty_threshold}
                onChange={(event) => setSettings({ ...settings, semantic_novelty_threshold: Number(event.target.value) })}
              />
            </label>
          </div>
        )}

        <div className="settings-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleSave} disabled={!settings || saving}>
            {saving ? 'Saving...' : 'Save settings'}
          </button>
        </div>
      </div>
    </div>
  )
}
