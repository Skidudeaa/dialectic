import { useState } from 'react'
import type { JourneyNotes } from '../../../hooks/useJourneyNotes'
import type { Journey } from '../types'
import { FriendActions } from '../FriendActions'
import { Saved, VoyageStage } from './VoyageStage'
import { VoyageEditor } from './VoyageEditor'
import type { Receipt } from './voyage'

type Target = Pick<Journey, 'slug' | 'title' | 'voyage'>
// canEdit comes from the chart (room.can_edit): house managers edit, everyone rides.
type Props = { roomId: string; journey: Target; canEdit?: boolean }

export function VoyageActions({ roomId, journey, canEdit = false, library = false, notes, onOpen }: Props & { library?: boolean; notes?: JourneyNotes; onOpen?: () => void }) {
  const [open, setOpen] = useState<'stage' | 'dossier' | 'record' | null>(null)
  const [message, setMessage] = useState('')
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  return <>
    {journey.voyage === true && <button onClick={() => { onOpen?.(); setOpen('stage') }}>Ride the voyage</button>}
    <FriendActions notes={notes} title={journey.title} onOpen={() => { onOpen?.(); setMessage('') }} onSent={setMessage} />
    {notes?.data?.writable === false && <p className="lw-note">{notes.data.why || 'Adding is closed.'}</p>}
    {message && <p role="status" className="lw-note">{message}</p>}
    {library && canEdit && <><button onClick={() => setOpen('dossier')}>Edit dossier</button>
      <button onClick={() => setOpen('record')}>Edit record</button></>}
    {canEdit && receipt && <Saved receipt={receipt} />}
    {open === 'stage' && notes && <VoyageStage notes={notes} roomId={roomId} journey={journey} canEdit={canEdit} close={() => setOpen(null)} />}
    {canEdit && (open === 'dossier' || open === 'record') && <VoyageEditor roomId={roomId} journey={journey} initialView={open}
      close={() => setOpen(null)} onSaved={result => { setReceipt(result); setOpen(null) }} />}
  </>
}
