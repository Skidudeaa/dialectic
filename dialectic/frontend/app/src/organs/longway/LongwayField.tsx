import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import { useLongwayProposals } from '../../hooks/useLongwayProposals'
import { ProposalCard } from './ProposalCard'
import { ScoutQuestions } from './ScoutQuestions'

export function LongwayField({ roomId, canManageHome }: { roomId: string; canManageHome?: boolean }) {
  const { data, error, refresh } = useLongwayProposals(roomId)
  const [manager, setManager] = useState(false)
  const [permissionError, setPermissionError] = useState('')
  const [permissionVersion, setPermissionVersion] = useState(0)
  useEffect(() => {
    if (canManageHome !== undefined) return
    let active = true
    // App owns the room list; it is not in useAppStore and FieldScene has no capability prop.
    void api.getRooms().then(rooms => {
      if (active) { setManager(rooms.some(room => room.is_home && room.can_manage_home)); setPermissionError('') }
    }).catch(() => { if (active) setPermissionError('Could not check Scout management access.') })
    return () => { active = false }
  }, [canManageHome, permissionVersion])
  return <div className="longway-field scene-body">
    <ScoutQuestions key={roomId} roomId={roomId} canManageHome={canManageHome ?? manager} />
    {permissionError && <p role="alert">{permissionError} <button onClick={() => setPermissionVersion(v => v + 1)}>Retry access</button></p>}
    <section aria-label="Proposed evidence"><h2>Proposed evidence</h2>
      {error ? <p role="alert">{error} <button onClick={refresh}>Retry proposals</button></p> : !data ? <p role="status">Loading proposals…</p> : data.length === 0 ? <p>No evidence proposed yet.</p> : data.map(proposal => <ProposalCard key={`${roomId}:${proposal.id}`} proposal={proposal} roomId={roomId} />)}
    </section>
  </div>
}
