import { useState } from 'react'
import type { ReactNode } from 'react'
import type { JourneyNotes } from '../../../hooks/useJourneyNotes'
import type { Journey } from '../types'
import { FriendActions } from '../FriendActions'
import { Saved, VoyageStage } from './VoyageStage'
import { VoyageEditor } from './VoyageEditor'
import type { Receipt } from './voyage'

type Target = Pick<Journey, 'slug' | 'title' | 'voyage'>
// canEdit comes from the chart (room.can_edit): house managers edit, everyone rides.
type Props = { roomId: string; journey: Target; canEdit?: boolean }

function PlayMark() {
  return <svg className="lw-ride-glyph" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">
    <path d="M2.5 1.8L10.2 6 2.5 10.2V1.8z" fill="currentColor" />
  </svg>
}

export function VoyageActions({ roomId, journey, canEdit = false, library = false, dock = false, primary = true, notes, onOpen, roomAction, managerAction, footerNote }: Props & {
  library?: boolean
  dock?: boolean
  primary?: boolean
  notes?: JourneyNotes
  onOpen?: () => void
  roomAction?: ReactNode
  managerAction?: ReactNode
  footerNote?: ReactNode
}) {
  const [open, setOpen] = useState<'stage' | 'dossier' | 'record' | null>(null)
  const [message, setMessage] = useState('')
  const [receipt, setReceipt] = useState<Receipt | null>(null)
  const ride = journey.voyage === true && <button
    className={primary ? 'lw-primary lw-ride-btn' : 'lw-ride-btn lw-ride-secondary'}
    onClick={() => { onOpen?.(); setOpen('stage') }}
  ><PlayMark />Ride the voyage</button>
  const friends = <FriendActions notes={notes} title={journey.title} onOpen={() => { onOpen?.(); setMessage('') }} onSent={setMessage} />
  const statuses = <>
    {notes?.data?.writable === false && <p className="lw-note lw-action-status">{notes.data.why || 'Adding is closed.'}</p>}
    {message && <p role="status" className="lw-note lw-action-status">{message}</p>}
    {canEdit && receipt && <Saved receipt={receipt} />}
  </>
  const overlays = <>
    {open === 'stage' && notes && <VoyageStage notes={notes} roomId={roomId} journey={journey} canEdit={canEdit} close={() => setOpen(null)} />}
    {canEdit && (open === 'dossier' || open === 'record') && <VoyageEditor roomId={roomId} journey={journey} initialView={open}
      close={() => setOpen(null)} onSaved={result => { setReceipt(result); setOpen(null) }} />}
  </>
  if (library || dock) {
    const hasLead = Boolean(ride || roomAction)
    return <div className={library ? 'lw-action-dock' : 'lw-action-dock lw-house-dock'}>
      <div className="lw-action-main">
        {hasLead && <div className={ride && roomAction ? 'lw-lead-row lw-lead-pair' : 'lw-lead-row'}>
          {ride}
          {roomAction}
        </div>}
        <div className="lw-friend-row">{friends}</div>
      </div>
      {library && canEdit && <div className="lw-manager-tools">
        <button className="lw-quiet-btn" onClick={() => setOpen('dossier')}>Edit dossier</button>
        <button className="lw-quiet-btn" onClick={() => setOpen('record')}>Edit record</button>
      </div>}
      {managerAction && <div className="lw-manager-tools lw-manager-tools-single">
        {managerAction}
      </div>}
      {footerNote}
      {statuses}
      {overlays}
    </div>
  }
  return <>
    {ride}
    {friends}
    {statuses}
    {overlays}
  </>
}
