import { useEffect, useId, useRef, useState } from 'react'
import { api, ApiError } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'
import './ProposeMenu.css'

/**
 * "Make a move" — the propose surface (§1.11, §5.3, plan Ruling R2).
 *
 * WHY a normal message and not a new write path: proposal_envelope.py
 * already normalizes exactly this shape out of `messages.metadata`, and
 * `acceptance_stamp()` already handles acceptance. This component's entire
 * job is to get a human's draft into that shape and post it through the
 * message-create door — the server (proposal_intake.py) is the real trust
 * boundary, re-validating every field before it reaches storage. The four
 * kinds mirror `proposal_envelope.PROPOSAL_SLOTS` exactly; resolution
 * proposals are excluded on purpose — those belong to the deadline-watch
 * job, not a human composing one from nothing.
 *
 * WHY no hover: §17.4 forbids a hover-only action. The trigger is an
 * ordinary button, reachable and visible at every width including phone;
 * the panel opens on click/tap and closes on click-away or Escape — never
 * on pointer leave.
 */

type ProposeKind = 'prediction_draft' | 'thesis_proposal' | 'reading_draft' | 'commitment_proposal'

const KIND_ORDER: readonly ProposeKind[] = [
  'prediction_draft', 'thesis_proposal', 'reading_draft', 'commitment_proposal',
]

const KIND_LABEL: Record<ProposeKind, string> = {
  prediction_draft: 'Prediction',
  thesis_proposal: 'Thesis',
  reading_draft: 'Reading',
  commitment_proposal: 'Commitment',
}

const KIND_HINT: Record<ProposeKind, string> = {
  prediction_draft: 'Put a statement on record with a confidence and a deadline.',
  thesis_proposal: 'Propose the room argue a tracked thesis.',
  reading_draft: "File an article into the room's library.",
  commitment_proposal: 'Put a bet or commitment on record.',
}

type Phase = 'closed' | 'pick' | ProposeKind | 'sent'

function isProposeKind(phase: Phase): phase is ProposeKind {
  return (KIND_ORDER as readonly string[]).includes(phase)
}

interface ProposeMenuProps {
  /** Mirrors the composer's own disabled state — no socket, no open thread. */
  disabled?: boolean
}

interface FieldsetProps {
  fields: Record<string, string>
  setField: (key: string, value: string) => void
  idFor: (key: string) => string
}

function TextField({ fields, setField, idFor, name, label, textarea, placeholder, maxLength, type }: FieldsetProps & {
  name: string
  label: string
  textarea?: boolean
  placeholder?: string
  maxLength?: number
  type?: string
}) {
  const id = idFor(name)
  return (
    <div className="propose-field">
      <label htmlFor={id}>{label}</label>
      {textarea ? (
        <textarea
          id={id}
          value={fields[name] ?? ''}
          onChange={(e) => setField(name, e.target.value)}
          maxLength={maxLength}
          placeholder={placeholder}
          rows={3}
        />
      ) : (
        <input
          id={id}
          type={type ?? 'text'}
          value={fields[name] ?? ''}
          onChange={(e) => setField(name, e.target.value)}
          maxLength={maxLength}
          placeholder={placeholder}
        />
      )}
    </div>
  )
}

/** statement/confidence/deadline — the exact shape proposal_intake.py's
 *  _validate_prediction_draft (and llm/tools.py draft_prediction) enforce. */
function isPredictionDraftValid(fields: Record<string, string>): boolean {
  const statement = fields.statement?.trim()
  const confidence = Number(fields.confidence)
  const deadline = fields.deadline?.trim()
  return Boolean(statement) && Number.isFinite(confidence) && confidence >= 0 && confidence <= 100
    && Boolean(deadline) && !Number.isNaN(Date.parse(deadline))
}

function isThesisProposalValid(fields: Record<string, string>): boolean {
  const title = fields.title?.trim()
  const claim = fields.claim?.trim()
  return Boolean(title) && title!.length <= 120 && Boolean(claim) && claim!.length <= 2000
}

function isReadingDraftValid(fields: Record<string, string>): boolean {
  const url = fields.url?.trim() ?? ''
  const summary = fields.summary?.trim()
  return /^https?:\/\//.test(url) && Boolean(summary) && summary!.length <= 1000
}

function isCommitmentProposalValid(fields: Record<string, string>): boolean {
  return Boolean(fields.claim?.trim()) && Boolean(fields.resolution_criteria?.trim())
}

const KIND_VALIDATORS: Record<ProposeKind, (fields: Record<string, string>) => boolean> = {
  prediction_draft: isPredictionDraftValid,
  thesis_proposal: isThesisProposalValid,
  reading_draft: isReadingDraftValid,
  commitment_proposal: isCommitmentProposalValid,
}

/** The message body and the metadata slot, from one kind's fields — the
 *  ONLY place this component decides what proposal_intake.py's slot names
 *  are, so the shape lives in one function per kind. */
function buildSubmission(kind: ProposeKind, fields: Record<string, string>): {
  content: string
  metadata: Record<string, unknown>
} {
  const note = fields.note?.trim()
  switch (kind) {
    case 'prediction_draft': {
      const statement = fields.statement.trim()
      const payload: Record<string, unknown> = {
        statement,
        confidence: Number(fields.confidence) / 100,
        deadline: fields.deadline.trim(),
      }
      return { content: note || statement, metadata: { proposal: payload } }
    }
    case 'thesis_proposal': {
      const claim = fields.claim.trim()
      const payload: Record<string, unknown> = {
        title: fields.title.trim(),
        claim,
        monthly_budget: fields.monthly_budget ? Number(fields.monthly_budget) : 5000,
      }
      return { content: note || claim, metadata: { thesis_proposal: payload } }
    }
    case 'reading_draft': {
      const summary = fields.summary.trim()
      const keyClaims = (fields.key_claims ?? '')
        .split('\n').map((s) => s.trim()).filter(Boolean).slice(0, 10)
      const payload: Record<string, unknown> = {
        url: fields.url.trim(), summary, key_claims: keyClaims,
      }
      return { content: note || summary, metadata: { reading_proposal: payload } }
    }
    case 'commitment_proposal': {
      const claim = fields.claim.trim()
      const payload = {
        claim,
        resolution_criteria: fields.resolution_criteria.trim(),
        category: fields.category || 'prediction',
      }
      return { content: note || claim, metadata: { commitment_proposals: [payload] } }
    }
    default: {
      // KIND_ORDER only ever produces the four cases above — this keeps
      // `tsc -b` satisfied without weakening ProposeKind to a fallback type.
      const exhaustive: never = kind
      throw new Error(`unhandled propose kind: ${exhaustive}`)
    }
  }
}

function ProposeForm({ kind, onCancel, onSubmitted }: {
  kind: ProposeKind
  onCancel: () => void
  onSubmitted: () => void
}) {
  const reactId = useId()
  const idFor = (key: string) => `${reactId}-${key}`
  const [fields, setFields] = useState<Record<string, string>>(
    kind === 'thesis_proposal' ? { monthly_budget: '5000' }
      : kind === 'commitment_proposal' ? { category: 'prediction' } : {},
  )
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const setField = (key: string, value: string) => setFields((f) => ({ ...f, [key]: value }))

  const valid = KIND_VALIDATORS[kind](fields)

  const handleSubmit = async () => {
    const threadId = useAppStore.getState().currentThread?.id
    if (!threadId) {
      setError('No open branch to propose into yet.')
      return
    }
    if (!valid) return
    setSubmitting(true)
    setError(null)
    try {
      const { content, metadata } = buildSubmission(kind, fields)
      await api.proposeMove(threadId, content, metadata)
      onSubmitted()
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'Could not send that — try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="propose-form">
      <p className="propose-hint">{KIND_HINT[kind]}</p>
      {kind === 'prediction_draft' && (
        <>
          <TextField fields={fields} setField={setField} idFor={idFor} name="statement"
            label="Statement" textarea placeholder="Brent closes over $90 by October" maxLength={2000} />
          <TextField fields={fields} setField={setField} idFor={idFor} name="confidence"
            label="Confidence (%)" type="number" placeholder="70" />
          <TextField fields={fields} setField={setField} idFor={idFor} name="deadline"
            label="Deadline" type="date" />
        </>
      )}
      {kind === 'thesis_proposal' && (
        <>
          <TextField fields={fields} setField={setField} idFor={idFor} name="title"
            label="Title" placeholder="Strait risk" maxLength={120} />
          <TextField fields={fields} setField={setField} idFor={idFor} name="claim"
            label="Claim" textarea placeholder="The strait shuts and rates re-price" maxLength={2000} />
          <TextField fields={fields} setField={setField} idFor={idFor} name="monthly_budget"
            label="Monthly budget ($)" type="number" placeholder="5000" />
        </>
      )}
      {kind === 'reading_draft' && (
        <>
          <TextField fields={fields} setField={setField} idFor={idFor} name="url"
            label="URL" type="url" placeholder="https://…" />
          <TextField fields={fields} setField={setField} idFor={idFor} name="summary"
            label="Summary" textarea placeholder="What the room should remember of this piece" maxLength={1000} />
          <TextField fields={fields} setField={setField} idFor={idFor} name="key_claims"
            label="Key claims (one per line, optional)" textarea />
        </>
      )}
      {kind === 'commitment_proposal' && (
        <>
          <TextField fields={fields} setField={setField} idFor={idFor} name="claim"
            label="Claim" textarea placeholder="I close before CPI" maxLength={2000} />
          <TextField fields={fields} setField={setField} idFor={idFor} name="resolution_criteria"
            label="Resolution criteria" textarea placeholder="How we'll know" maxLength={1000} />
          <div className="propose-field">
            <label htmlFor={idFor('category')}>Category</label>
            <select id={idFor('category')} value={fields.category ?? 'prediction'}
              onChange={(e) => setField('category', e.target.value)}>
              <option value="prediction">Prediction</option>
              <option value="commitment">Commitment</option>
              <option value="bet">Bet</option>
            </select>
          </div>
        </>
      )}
      <TextField fields={fields} setField={setField} idFor={idFor} name="note"
        label="Note (optional)" textarea placeholder="Add context for the room" />
      {error && <p className="propose-error" role="alert">{error}</p>}
      <div className="propose-actions">
        <button type="button" className="propose-cancel" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
        <button type="button" className="propose-submit" onClick={handleSubmit} disabled={!valid || submitting}>
          {submitting ? 'Sending…' : 'Send to the room'}
        </button>
      </div>
    </div>
  )
}

export function ProposeMenu({ disabled }: ProposeMenuProps) {
  const [phase, setPhase] = useState<Phase>('closed')
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const open = phase !== 'closed'

  const close = () => setPhase('closed')

  // No hover dependency (§17.4): every transition here is a click/tap or a
  // keypress. Escape and click-away both close the panel; nothing closes on
  // pointer leave, so a touch device never loses the form mid-fill.
  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    const onPointerDown = (e: MouseEvent) => {
      const target = e.target as Node
      if (panelRef.current?.contains(target)) return
      if (triggerRef.current?.contains(target)) return
      close()
    }
    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
    }
  }, [open])

  return (
    <div className="propose-menu">
      <button
        ref={triggerRef}
        type="button"
        className="propose-trigger"
        onClick={() => setPhase(open ? 'closed' : 'pick')}
        disabled={disabled}
        aria-haspopup="true"
        aria-expanded={open}
        title="Make a move — propose a prediction, thesis, reading or commitment"
      >
        + Make a move
      </button>
      {open && (
        <div className="propose-panel" ref={panelRef} role="dialog" aria-label="Make a move">
          {phase === 'pick' && (
            <>
              <p className="propose-hint">What are you proposing?</p>
              <div className="propose-kinds">
                {KIND_ORDER.map((kind) => (
                  <button
                    key={kind}
                    type="button"
                    className="propose-kind-btn"
                    onClick={() => setPhase(kind)}
                  >
                    {KIND_LABEL[kind]}
                  </button>
                ))}
              </div>
            </>
          )}
          {isProposeKind(phase) && (
            <ProposeForm
              kind={phase}
              onCancel={() => setPhase('pick')}
              onSubmitted={() => setPhase('sent')}
            />
          )}
          {phase === 'sent' && (
            <div className="propose-sent">
              <p>Sent — it will appear in the thread and carries an Accept action for the room.</p>
              <button type="button" className="propose-submit" onClick={close}>Done</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
