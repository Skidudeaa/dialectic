import { useState } from 'react'
import { FIELD_RELATIONS } from '../../../types/workspace.ts'
import type { FieldMark, FieldRelation, FieldReviewRequest } from '../../../types/workspace.ts'
import { humanizeRelation } from '../fieldDisplay.ts'
import './Focus.css'

type EditorKind = 'correct' | 'split' | 'merge' | null

interface FocusActionsProps {
  mark: FieldMark
  /** Membership gate (§5.2) — an authenticated room member always passes
   *  this (viewing the room already required membership); a guest identity
   *  does not, since guests carry no JWT and every write here requires one. */
  canAct: boolean
  /** Other still-active marks in the room, for the merge editor's picker.
   *  Never includes `mark` itself or anything already superseded — merging
   *  into a retired mark is refused server-side (409) and the picker should
   *  not offer a choice the door will refuse. */
  mergeCandidates: FieldMark[]
  onReview: (request: FieldReviewRequest) => Promise<void>
}

/**
 * Confirm/contest/correct/split/merge/supersede — the six actions §1.10's
 * append-only rule allows. Confirm, contest and supersede are one-tap (with
 * an optional note); correct, split and merge open a minimal inline editor,
 * because each needs at least a relation and a title for the replacement
 * row(s) the server will write. No hover-only control (§17.4) — every
 * action is a real <button>, reachable at phone width with the software
 * keyboard.
 */
export function FocusActions({ mark, canAct, mergeCandidates, onReview }: FocusActionsProps) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [editor, setEditor] = useState<EditorKind>(null)
  const [error, setError] = useState<string | null>(null)

  const [correctRelation, setCorrectRelation] = useState<FieldRelation>(mark.relation)
  const [correctTitle, setCorrectTitle] = useState(mark.title)

  const [splitA, setSplitA] = useState<{ relation: FieldRelation; title: string }>(
    { relation: mark.relation, title: mark.title },
  )
  const [splitB, setSplitB] = useState<{ relation: FieldRelation; title: string }>(
    { relation: mark.relation, title: '' },
  )

  const [mergeIds, setMergeIds] = useState<string[]>([])
  const [mergeRelation, setMergeRelation] = useState<FieldRelation>(mark.relation)
  const [mergeTitle, setMergeTitle] = useState(mark.title)

  if (!canAct) return null
  const terminal = mark.review === 'superseded'

  const run = async (request: FieldReviewRequest) => {
    setBusy(true)
    setError(null)
    try {
      await onReview(request)
      setNote('')
      setEditor(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That action did not go through.')
    } finally {
      setBusy(false)
    }
  }

  const oneTap = (action: 'confirm' | 'contest' | 'supersede') => () => {
    void run({ action, note: note.trim() || undefined })
  }

  const submitCorrect = () => {
    void run({
      action: 'correct',
      note: note.trim() || undefined,
      // Subjects carry over unchanged — re-picking them is a bigger surface
      // (a search/browse over messages, readings, memories, commitments)
      // than a minimal editor covers; a further correction can still narrow
      // them later. Nothing here loses data the append-only row cannot fix.
      replacement: { relation: correctRelation, subjects: mark.subjects, title: correctTitle },
    })
  }

  const submitSplit = () => {
    void run({
      action: 'split',
      note: note.trim() || undefined,
      replacements: [
        { relation: splitA.relation, subjects: mark.subjects, title: splitA.title },
        { relation: splitB.relation, subjects: mark.subjects, title: splitB.title },
      ],
    })
  }

  const submitMerge = () => {
    void run({
      action: 'merge',
      note: note.trim() || undefined,
      merge_ids: mergeIds,
      replacement: { relation: mergeRelation, subjects: mark.subjects, title: mergeTitle },
    })
  }

  return (
    <section className="focus-section focus-actions" aria-label="Actions">
      <h3 className="focus-section-label">Actions</h3>
      <label className="focus-actions-note-label">
        Note (optional)
        <input
          type="text"
          className="focus-actions-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Why — the human record, not required"
        />
      </label>
      <div className="focus-actions-row">
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={busy || terminal || mark.review === 'confirmed'}
          onClick={oneTap('confirm')}
        >
          Confirm
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          disabled={busy || terminal || mark.review === 'contested'}
          onClick={oneTap('contest')}
        >
          Contest
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || terminal}
          onClick={oneTap('supersede')}
        >
          Already answered
        </button>
      </div>
      <div className="focus-actions-row">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || terminal}
          aria-expanded={editor === 'correct'}
          onClick={() => setEditor(editor === 'correct' ? null : 'correct')}
        >
          Correct…
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || terminal}
          aria-expanded={editor === 'split'}
          onClick={() => setEditor(editor === 'split' ? null : 'split')}
        >
          Split…
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy || terminal || mergeCandidates.length === 0}
          aria-expanded={editor === 'merge'}
          onClick={() => setEditor(editor === 'merge' ? null : 'merge')}
        >
          Merge…
        </button>
      </div>

      {editor === 'correct' && (
        <div className="focus-actions-editor">
          <label>
            Relation
            <select value={correctRelation} onChange={(e) => setCorrectRelation(e.target.value as FieldRelation)}>
              {FIELD_RELATIONS.map((r) => <option key={r} value={r}>{humanizeRelation(r)}</option>)}
            </select>
          </label>
          <label>
            Title
            <input type="text" value={correctTitle} onChange={(e) => setCorrectTitle(e.target.value)} />
          </label>
          <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={submitCorrect}>
            Replace with this
          </button>
        </div>
      )}

      {editor === 'split' && (
        <div className="focus-actions-editor">
          <fieldset className="focus-actions-split-part">
            <legend>Part 1</legend>
            <label>
              Relation
              <select
                value={splitA.relation}
                onChange={(e) => setSplitA({ ...splitA, relation: e.target.value as FieldRelation })}
              >
                {FIELD_RELATIONS.map((r) => <option key={r} value={r}>{humanizeRelation(r)}</option>)}
              </select>
            </label>
            <label>
              Title
              <input type="text" value={splitA.title} onChange={(e) => setSplitA({ ...splitA, title: e.target.value })} />
            </label>
          </fieldset>
          <fieldset className="focus-actions-split-part">
            <legend>Part 2</legend>
            <label>
              Relation
              <select
                value={splitB.relation}
                onChange={(e) => setSplitB({ ...splitB, relation: e.target.value as FieldRelation })}
              >
                {FIELD_RELATIONS.map((r) => <option key={r} value={r}>{humanizeRelation(r)}</option>)}
              </select>
            </label>
            <label>
              Title
              <input type="text" value={splitB.title} onChange={(e) => setSplitB({ ...splitB, title: e.target.value })} />
            </label>
          </fieldset>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || !splitA.title.trim() || !splitB.title.trim()}
            onClick={submitSplit}
          >
            Split into these two
          </button>
        </div>
      )}

      {editor === 'merge' && (
        <div className="focus-actions-editor">
          <label>
            Merge with
            <select
              multiple
              value={mergeIds}
              onChange={(e) => setMergeIds(Array.from(e.target.selectedOptions, (o) => o.value))}
            >
              {mergeCandidates.map((m) => (
                <option key={m.id} value={m.id.split(':', 2)[1]}>{m.title || humanizeRelation(m.relation)}</option>
              ))}
            </select>
          </label>
          <label>
            Merged relation
            <select value={mergeRelation} onChange={(e) => setMergeRelation(e.target.value as FieldRelation)}>
              {FIELD_RELATIONS.map((r) => <option key={r} value={r}>{humanizeRelation(r)}</option>)}
            </select>
          </label>
          <label>
            Merged title
            <input type="text" value={mergeTitle} onChange={(e) => setMergeTitle(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={busy || mergeIds.length === 0 || !mergeTitle.trim()}
            onClick={submitMerge}
          >
            Merge into one mark
          </button>
        </div>
      )}

      {error && <p className="focus-actions-error" role="alert">{error}</p>}
    </section>
  )
}
