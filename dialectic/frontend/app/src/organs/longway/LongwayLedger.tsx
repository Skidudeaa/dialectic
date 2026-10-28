import { useState } from 'react'
import { useLongwayConfirmations } from '../../hooks/useLongwayConfirmations'
import { useLongwayJourney } from '../../hooks/useLongwayJourney'
import { useLongwayResource } from './useLongwayResource'
import { longwayPath, longwayRequest } from './api'

export function LongwayLedger({ roomId, canManageHome }: { roomId: string; canManageHome: boolean }) {
  const { data, error, refresh } = useLongwayConfirmations(roomId)
  const journey = useLongwayJourney(roomId)
  const members = useLongwayResource<{ user_id: string; display_name: string }[]>(canManageHome ? `/rooms/${encodeURIComponent(roomId)}/members` : null)
  const [busy, setBusy] = useState(false)
  const [writeError, setWriteError] = useState('')
  return <div className="longway-ledger scene-body"><h2>Consent ledger</h2><p>A reaction is not a decision. Record what each person explicitly confirmed.</p>
    {error ? <p role="alert">{error} <button onClick={refresh}>Retry ledger</button></p> : !data ? <p role="status">Loading consent ledger…</p> : data.length === 0 ? <p>Nothing confirmed yet.</p> : data.map(entry => <article className="longway-card" key={entry.id}><h3>{entry.member_name}</h3><p>{entry.binds}</p><p>{entry.confirmed_on} · {entry.channel}</p></article>)}
    {canManageHome && <form onSubmit={async e => {
      e.preventDefault(); const form = e.currentTarget; const fields = new FormData(form)
      setBusy(true); setWriteError('')
      try {
        await longwayRequest(longwayPath(roomId, 'confirmations'), { method: 'POST', body: JSON.stringify(Object.fromEntries(fields)) })
        form.reset(); refresh()
      } catch (error) { setWriteError(error instanceof Error ? error.message : 'Could not record consent') }
      finally { setBusy(false) }
    }}><h3>Record a confirmation</h3>
      <label>Member<select name="member_id" required defaultValue=""><option value="" disabled>Choose a member</option>{members.data?.map(member => <option key={member.user_id} value={member.user_id}>{member.display_name}</option>)}</select></label>
      {members.error && <p role="alert">{members.error} <button type="button" onClick={members.refresh}>Retry members</button></p>}
      <label>What binds them<textarea name="binds" required /></label><label>Confirmed on<input type="date" name="confirmed_on" required /></label><label>Channel<input name="channel" required /></label><button disabled={busy || !members.data}>Record confirmation</button>
      {writeError && <p role="alert">{writeError}</p>}
    </form>}
    {journey.error && <p role="alert">{journey.error}</p>}
    {journey.data?.plan?.undecided && <section><h2>Undecided</h2><p className="longway-plan">{journey.data.plan.undecided}</p></section>}
  </div>
}
