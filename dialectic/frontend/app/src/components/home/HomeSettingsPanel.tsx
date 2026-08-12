import { useState } from 'react'
import type { Memory } from '../../types'
import { api } from '../../lib/api.ts'
import './HomeSettingsPanel.css'

interface HomeSettingsPanelProps {
  canManageHome: boolean
  onMembershipChanged: () => void
  residents: { id: string; name: string; status: string }[]
  facts: Memory[]
  onOpenMemory: () => void
}

interface Candidate {
  user_id: string
  display_name: string
  email: string
}

/**
 * The household drawer: who lives here, what the house currently holds,
 * and (for founders) the nondelegable member-add. Capture and identity
 * novels stay in Memory / AI — this surface is orientation, not a dump.
 */
export function HomeSettingsPanel({
  canManageHome,
  onMembershipChanged,
  residents,
  facts,
  onOpenMemory,
}: HomeSettingsPanelProps) {
  const [adding, setAdding] = useState(false)
  const [email, setEmail] = useState('')
  const [candidate, setCandidate] = useState<Candidate | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const held = facts.slice(0, 4)

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
      setAdding(false)
      if (added.status === 'added') onMembershipChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add that account')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="home-settings">
      <section>
        <h3>Household</h3>
        <ul className="home-household">
          {residents.map((resident) => (
            <li key={resident.id}>
              <span className={`home-household-dot ${resident.status}`} />
              <span className="home-household-name">{resident.name}</span>
              <span className="home-household-status">{resident.status}</span>
            </li>
          ))}
          {residents.length === 0 && (
            <li className="home-settings-note">No one else is in the house right now.</li>
          )}
        </ul>
      </section>

      <section>
        <h3>What we hold</h3>
        {held.length === 0 ? (
          <p className="home-settings-note">The house has no facts yet. Remember them from Memory.</p>
        ) : (
          <ul className="home-held">
            {held.map((memory) => (
              <li key={memory.id}>
                <span className="home-held-key">{titleOf(memory.key)}</span>
                <span className="home-held-body">{oneLine(memory.content, 90)}</span>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="btn btn-ghost btn-sm" onClick={onOpenMemory}>
          All memory
        </button>
      </section>

      <section>
        <h3>Members</h3>
        {!canManageHome && (
          <p className="home-settings-note">
            Only Amo and Dan can add members. Membership controls what every
            Home member sees in the house, so additions go through them.
          </p>
        )}
        {canManageHome && !adding && !candidate && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAdding(true)}>
            Add a member
          </button>
        )}
        {canManageHome && adding && !candidate && (
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
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => { setAdding(false); setEmail(''); setError(null) }}
            >
              Cancel
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
      </section>
    </div>
  )
}

function titleOf(key: string): string {
  return key.replace(/[_:]+/g, ' ').replace(/\s+/g, ' ').trim()
}

function oneLine(raw: string, max: number): string {
  const text = raw.replace(/\s+/g, ' ').trim()
  return text.length <= max ? text : `${text.slice(0, max).trimEnd()}…`
}
