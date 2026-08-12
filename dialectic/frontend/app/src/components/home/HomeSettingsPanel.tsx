import { useState } from 'react'
import { api } from '../../lib/api.ts'
import './HomeSettingsPanel.css'

interface HomeSettingsPanelProps {
  canManageHome: boolean
  onMembershipChanged: () => void
}

interface Candidate {
  user_id: string
  display_name: string
  email: string
}

/**
 * Nondelegable Home membership administration. Resolve-then-confirm: the
 * add lands on exactly the account previewed (the server re-checks the
 * email against the confirmed user id). No invite code, no removal UI —
 * emergency removal is the reviewed operator script.
 */
export function HomeSettingsPanel({ canManageHome, onMembershipChanged }: HomeSettingsPanelProps) {
  const [email, setEmail] = useState('')
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!canManageHome) {
    return (
      <div className="home-settings">
        <h3>Home members</h3>
        <p className="home-settings-note">
          Only Amo and Dan can add members to Home. Membership controls
          what every Home member sees in the shared pulse, so additions go
          through them.
        </p>
      </div>
    )
  }

  const resolve = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    setBusy(true)
    try {
      const normalized = email.trim().toLowerCase()
      const found = await api.resolveHomeMember(normalized)
      setCandidate({ ...found, email: normalized })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'No account with that email')
      setCandidate(null)
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    if (!candidate) return
    setError(null)
    setBusy(true)
    try {
      const added = await api.addHomeMember(candidate.email, candidate.user_id)
      setResult(added.status === 'added'
        ? `Added ${added.display_name}`
        : `${added.display_name} is already in Home`)
      setCandidate(null)
      setEmail('')
      if (added.status === 'added') onMembershipChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add that account')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="home-settings">
      <h3>Home members</h3>
      <p className="home-settings-note">
        Add an existing account by email. Added members participate fully
        but cannot add anyone else.
      </p>

      {!candidate && (
        <form className="home-settings-form" onSubmit={resolve}>
          <input
            className="form-input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="member@example.com"
            required
          />
          <button className="btn btn-secondary btn-sm" type="submit" disabled={busy}>
            {busy ? 'Checking…' : 'Look up'}
          </button>
        </form>
      )}

      {candidate && (
        <div className="home-settings-confirm">
          <p>
            Add <strong>{candidate.display_name}</strong> ({candidate.email})
            to Home?
          </p>
          <div className="home-settings-confirm-actions">
            <button className="btn btn-primary btn-sm" onClick={() => void confirm()} disabled={busy}>
              {busy ? 'Adding…' : 'Confirm'}
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setCandidate(null)}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {result && <p className="home-settings-result">{result}</p>}
      {error && <p className="home-settings-error">{error}</p>}
    </div>
  )
}
