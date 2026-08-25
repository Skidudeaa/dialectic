import { useMemo, useState } from 'react'
import type { FieldMark } from '../../../types/workspace.ts'
import type { WorkspaceObjectsState } from '../../../hooks/useWorkspaceObjects.ts'
import type { FieldMarksState } from '../../../hooks/useFieldMarks.ts'
import { PARTICIPANT_NAME } from '../../../lib/productIdentity.ts'
import { SceneEmpty, SceneLoading, SceneUnavailable } from '../SceneEmpty'
import {
  FIELD_SECTIONS,
  buildObjectTitleMap,
  causalFieldBinding,
  humanizeRelation,
  resolveSubjectLabel,
  sectionMarks,
  tradingDeskBuilderUrl,
  type FieldRow,
  type OrphanSupersededRow,
} from '../fieldDisplay.ts'
import { ReviewChip } from '../ReviewChip.tsx'
import { Explain } from '../../common/Explain'
import { useAppStore } from '../../../stores/appStore.ts'
import './FieldScene.css'

/**
 * The Field — the room's reasoning, laid out (design v2 §14, §7.3).
 *
 * EDITORIAL BANDS, NOT A GRAPH (§16.7): fixed-order sections, plain rows,
 * hairline rules, indentation. The sectioning and lineage-folding logic
 * lives in fieldDisplay.ts, shared with Focus, so the two surfaces that
 * both render a FieldMark cannot drift into different rules for the same
 * state.
 *
 * STABLE ORDER (§5.2): within a section, this renders `sectionMarks`'s
 * output in the order it was given — the backend's own anchor ordering
 * (field_marks.py's `_root_anchor` sort key). Nothing here re-sorts.
 *
 * Tapping a row selects it into Focus (§1.18) — `onOpen` is the ONLY write
 * this component performs, and it is a navigation, not a review action.
 * Review actions (confirm/contest/correct/split/merge) live in
 * FocusActions; this scene is read-mostly by design.
 */

interface FieldSceneProps {
  state: FieldMarksState
  /** For client-side subject-title resolution — the reading/thesis/etc a
   *  mark points at stays ONE object, no second projection (§5.2). */
  objects: WorkspaceObjectsState
  onOpen?: (mark: FieldMark) => void
}

function SubjectList({ mark, titles }: { mark: FieldMark; titles: Map<string, string> }) {
  const causal = causalFieldBinding(mark)
  if (causal) {
    return (
      <p className="field-mark-subjects field-mark-causal">
        <span>{causal.scopeLabel}</span>
        <span aria-hidden="true"> · </span>
        <span>{humanizeRelation(mark.relation)}</span>
        <span aria-hidden="true"> · </span>
        <span>{causal.nodeLabel}</span>
      </p>
    )
  }
  if (mark.subjects.length === 0) return null
  return (
    <p className="field-mark-subjects">
      {mark.subjects.map((s, i) => (
        <span key={`${s.entity}:${s.id}:${i}`}>
          {i > 0 ? ', ' : ''}
          {resolveSubjectLabel(s, titles)}
        </span>
      ))}
    </p>
  )
}

function HistoryDisclosure({ history, titles }: { history: FieldMark[]; titles: Map<string, string> }) {
  const [open, setOpen] = useState(false)
  if (history.length === 0) return null
  return (
    <div className="field-mark-history">
      <button
        type="button"
        className="field-mark-history-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        History ({history.length})
      </button>
      {open && (
        <ul className="field-mark-history-list">
          {history.map((ancestor) => (
            <li key={ancestor.id} className="field-mark-row is-superseded">
              <div className="field-mark-head">
                <span className="field-mark-title">{ancestor.title || humanizeRelation(ancestor.relation)}</span>
                <ReviewChip review="superseded" />
              </div>
              <SubjectList mark={ancestor} titles={titles} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MarkRow({
  row, titles, onOpen, accessToken,
}: {
  row: FieldRow
  titles: Map<string, string>
  onOpen?: (mark: FieldMark) => void
  accessToken: string | null
}) {
  const { mark } = row
  const causal = causalFieldBinding(mark)
  const title = mark.title || humanizeRelation(mark.relation)
  const body = (
    <>
      <div className="field-mark-head">
        <span className="field-mark-title">{title}</span>
        <ReviewChip review={mark.review} />
      </div>
      <SubjectList mark={mark} titles={titles} />
      {row.nested.map(({ mark: nestedMark, label }) => (
        <p key={nestedMark.id} className={`field-mark-nested is-${nestedMark.review}`}>
          — {label}
          <ReviewChip review={nestedMark.review} className="field-mark-nested-chip" />
        </p>
      ))}
      <HistoryDisclosure history={row.history} titles={titles} />
    </>
  )
  return (
    <li className={`field-mark-row is-${mark.review}`} data-relation={mark.relation}>
      {onOpen ? (
        <button type="button" className="field-mark-open" onClick={() => onOpen(mark)}>
          {body}
        </button>
      ) : body}
      {causal && accessToken && (
        <a
          className="field-mark-builder"
          href={tradingDeskBuilderUrl(accessToken, causal.roomId)}
          target="_blank"
          rel="noreferrer"
        >
          Open node in Builder
        </a>
      )}
    </li>
  )
}

function OrphanRow({ orphan, titles }: { orphan: OrphanSupersededRow; titles: Map<string, string> }) {
  const [open, setOpen] = useState(false)
  const { mark } = orphan
  return (
    <li className="field-mark-row is-superseded field-mark-orphan">
      <button
        type="button"
        className="field-mark-history-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        Retired: {mark.title || humanizeRelation(mark.relation)}
        <ReviewChip review="superseded" />
      </button>
      {open && <SubjectList mark={mark} titles={titles} />}
    </li>
  )
}

export function FieldScene({ state, objects, onOpen }: FieldSceneProps) {
  const accessToken = useAppStore((store) => store.accessToken)
  const titles = useMemo(
    () => buildObjectTitleMap(objects.status === 'ready' ? objects.objects : []),
    [objects],
  )
  const sectioned = useMemo(
    () => (state.status === 'ready' ? sectionMarks(state.marks) : null),
    [state],
  )

  if (state.status === 'loading') return <SceneLoading kicker="Field" />
  if (state.status === 'unavailable') {
    return (
      <SceneUnavailable
        kicker="Field"
        what="the field"
        error={state.error}
        onRetry={state.retry}
      />
    )
  }

  const totalVisible = sectioned
    ? [...sectioned.bySection.values(), ...sectioned.orphans.values()]
      .reduce((sum, list) => sum + list.length, 0)
    : 0

  if (totalVisible === 0) {
    return (
      <SceneEmpty kicker="Field" headline="Nothing marked yet.">
        <p>
          The Field is the room&rsquo;s reasoning laid out — the positions
          taken, the claims made, the tensions between them, and the
          questions still open.
        </p>
        <p>
          {PARTICIPANT_NAME} pencils provisional marks in a lighter hand as
          the conversation grows — a support, a contradiction, a question
          worth tracking. Nothing here is filed by hand.
        </p>
        <p>
          <strong>Your confirm makes a mark solid; your contest puts it on
          notice.</strong> Nothing {PARTICIPANT_NAME} marks outranks what you
          say.
        </p>
      </SceneEmpty>
    )
  }

  return (
    <div className="scene-body field-scene">
      {/* The POPULATED Field had no orientation at all — every word explaining
          a mark lived in the empty state, which is the one screen a reader
          with 85 marks never sees. That is the shape of the defect this line
          answers: the machinery was reachable and unexplained, so it was used
          zero times. The tap sentence is conditional because without `onOpen`
          the rows are not tappable, and promising an action a surface does not
          offer is the same failure as advertising a door the server refuses. */}
      <p className="field-lede">
        <Explain term="field-mark">Field marks</Explain>
        {' '}— provisional, and not conclusions.{' '}
        {onOpen
          ? 'Tap a row to open it, where you can confirm or contest it; the same two actions sit under the message that earned the mark.'
          : 'Confirm and contest sit under the message that earned the mark.'}
        {' '}Nothing marked here outranks what you said.
      </p>
      {FIELD_SECTIONS.map((section) => {
        const rows = sectioned?.bySection.get(section.key) ?? []
        const orphans = sectioned?.orphans.get(section.key) ?? []
        if (rows.length === 0 && orphans.length === 0) return null
        return (
          <section key={section.key} className="field-section" aria-label={section.label}>
            <h3 className="field-section-label">{section.label}</h3>
            <ul className="field-section-list">
              {rows.map((row) => (
                <MarkRow
                  key={row.mark.id}
                  row={row}
                  titles={titles}
                  onOpen={onOpen}
                  accessToken={accessToken}
                />
              ))}
              {orphans.map((orphan) => (
                <OrphanRow key={orphan.mark.id} orphan={orphan} titles={titles} />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
