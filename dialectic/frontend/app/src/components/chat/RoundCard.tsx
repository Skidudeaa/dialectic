import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/api.ts'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import type { RoundQuestion, RoundState } from '../../types'
import './RoundCard.css'

interface RoundCardProps {
  roomId: string
  messageId: string
  /** Display names by user id, so a forecaster is a person and not a UUID. */
  userNames?: Record<string, string>
}

const PCT = (value: number) => `${Math.round(value * 100)}%`
const SIGNED = (value: number) =>
  `${value > 0 ? '+' : ''}${Math.round(value * 100)}`

/**
 * Local calendar day, NOT `toISOString().slice(0,10)`.
 *
 * That form is UTC: after 19:00 CDT it names TOMORROW, so every "has this
 * closed yet" comparison flips a evening early and the settle controls appear
 * on a question that is still open. The same bug emptied a transfer queue in
 * another project every evening for weeks.
 */
function todayLocal(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * The Sunday Round, in the transcript where both of them already are.
 *
 * Three rules this component exists to honour and must not quietly soften:
 *
 * BLINDNESS IS THE SERVER'S. Until you have forecast a question, the other
 * person's number is ABSENT from the response — `others` is undefined, not a
 * value to hide. So there is nothing here to accidentally render, and nothing
 * to "reveal" client-side. If you ever find yourself writing a conditional
 * that hides a number you were sent, the rule has already been broken
 * upstream. The house's number is under the SAME seal, for the same reason: a
 * machine probability on the card before you have written yours is an anchor
 * with a tool loop behind it.
 *
 * A FAILURE MUST SAY SO. Copied from MessageMarks: silently doing nothing
 * after a tap reads as "my forecast was recorded", which is the worst
 * possible lie for a scoring surface.
 *
 * NOTHING SETTLES ITSELF. The settle controls send a human's verdict. The
 * close-watch job gathers evidence and suggests; it never resolves. One wrong
 * automatic settlement would cost this ledger its standing permanently.
 */
export function RoundCard({ roomId, messageId, userNames = {} }: RoundCardProps) {
  const [state, setState] = useState<RoundState | null>(null)
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [peerDraft, setPeerDraft] = useState<Record<string, number>>({})
  const [reading, setReading] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [refused, setRefused] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      setState(await api.readRound(roomId, messageId))
    } catch {
      setState(null)
    }
  }, [roomId, messageId])

  useEffect(() => { void load() }, [load])

  if (!state || state.questions.length === 0) return null

  const today = todayLocal()

  const submit = async (question: RoundQuestion) => {
    const id = question.commitment_id
    const value = draft[id] ?? question.my_forecast ?? 0.5
    // Only send a read if this viewer actually opened the second slider or
    // has one on file. An untouched control is not a guess of 50%.
    const peer = reading[id]
      ? (peerDraft[id] ?? question.my_peer_forecast ?? 0.5)
      : question.my_peer_forecast
    setBusy(id)
    setFailed(null)
    setRefused((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    try {
      setState(await api.recordForecast(roomId, id, value, undefined, peer))
    } catch (error) {
      // A 409 is the server refusing on purpose — a closed or binned
      // question. That is not a transport failure and must read differently:
      // "try again" would be a lie, because it will never be accepted.
      const detail = (error as { body?: { detail?: string } })?.body?.detail
      const status = (error as { status?: number })?.status
      if (status === 409 && detail) {
        setRefused((prev) => ({ ...prev, [id]: detail }))
        void load()
      } else {
        setFailed(id)
      }
    } finally {
      setBusy(null)
    }
  }

  const act = async (
    id: string,
    run: () => Promise<RoundState>,
  ) => {
    setBusy(id)
    setFailed(null)
    try {
      setState(await run())
    } catch (error) {
      const detail = (error as { body?: { detail?: string } })?.body?.detail
      const status = (error as { status?: number })?.status
      if (status === 409 && detail) {
        setRefused((prev) => ({ ...prev, [id]: detail }))
        void load()
      } else {
        setFailed(id)
      }
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="round-card">
      {state.questions.map((question, index) => {
        const id = question.commitment_id
        const binned = question.status === 'binned'
        const settled = question.resolution !== null
        // Closed but nobody has said what happened. This is the only state in
        // which a score is one tap away, so it is the only one that shouts.
        const awaitingVerdict = !binned && !settled
          && question.status === 'active'
          && !!question.closes && question.closes < today
        const value = draft[id] ?? question.my_forecast ?? 0.5
        const peerValue = peerDraft[id] ?? question.my_peer_forecast ?? 0.5
        const showPeer = reading[id] || question.my_peer_forecast !== null
        const them = question.others?.[0]
        // Before reveal there is no forecast to read a name out of — that is
        // the whole point of the seal — so the name comes from membership.
        const themName = them
          ? (userNames[them.user_id]
            ?? state.peers?.find((p) => p.user_id === them.user_id)?.display_name
            ?? 'them')
          : (state.peers?.[0]?.display_name ?? 'them')
        return (
          <div
            key={id}
            className={[
              'round-q',
              binned ? 'binned' : '',
              settled ? 'settled' : '',
              awaitingVerdict ? 'awaiting' : '',
            ].filter(Boolean).join(' ')}
          >
            <div className="round-q-head">
              <span className="round-q-n">{index + 1}</span>
              <span className="round-q-claim">{question.claim}</span>
            </div>
            {question.closes && (
              <div className="round-q-meta">
                {settled
                  ? `settled ${question.resolution} · closed ${question.closes}`
                  : awaitingVerdict
                    ? `closed ${question.closes} — what happened?`
                    : `closes ${question.closes}`}
              </div>
            )}

            {binned ? (
              <div className="round-q-binned">binned — never scored</div>
            ) : (
              <>
                {!settled && (
                  <>
                    <div className="round-q-row">
                      <label className="round-q-label" htmlFor={`f-${id}`}>you</label>
                      <input
                        id={`f-${id}`}
                        className="round-q-slider"
                        type="range"
                        min={0}
                        max={1}
                        step={0.01}
                        value={value}
                        disabled={busy === id}
                        onChange={(e) => setDraft((d) => ({
                          ...d, [id]: Number(e.target.value),
                        }))}
                      />
                      <span className="round-q-value">{PCT(value)}</span>
                      <button
                        className="round-q-submit"
                        disabled={busy === id}
                        onClick={() => void submit(question)}
                      >
                        {question.my_forecast === null ? 'lock in' : 'revise'}
                      </button>
                    </div>

                    {/* THE SECOND SLIDER. Optional on purpose: the number you
                        must give is your own, and this one is a bet on your
                        friend. It scores the moment you both commit — it
                        never waits for the world to settle anything. */}
                    {showPeer ? (
                      <div className="round-q-row round-q-row-peer">
                        <label className="round-q-label" htmlFor={`p-${id}`}>
                          {themName}
                        </label>
                        <input
                          id={`p-${id}`}
                          className="round-q-slider round-q-slider-peer"
                          type="range"
                          min={0}
                          max={1}
                          step={0.01}
                          value={peerValue}
                          disabled={busy === id}
                          onChange={(e) => setPeerDraft((d) => ({
                            ...d, [id]: Number(e.target.value),
                          }))}
                        />
                        <span className="round-q-value">{PCT(peerValue)}</span>
                      </div>
                    ) : (
                      <button
                        className="round-q-peer-open"
                        disabled={busy === id}
                        onClick={() => setReading((r) => ({ ...r, [id]: true }))}
                      >
                        + where will {themName} land?
                      </button>
                    )}
                  </>
                )}

                {question.my_forecast !== null && (
                  <div className="round-q-mine">
                    yours: {PCT(question.my_forecast)}
                    {question.my_revisions > 1
                      && ` · ${question.my_revisions} revisions`}
                    {question.my_peer_forecast !== null
                      && ` · you read ${themName} at ${PCT(question.my_peer_forecast)}`}
                  </div>
                )}

                {/* Nothing to hide here — before reveal the server sent no
                    number at all. */}
                {question.revealed && question.others ? (
                  <div className="round-q-others">
                    {question.others.map((other) => (
                      <div key={other.user_id} className="round-q-other">
                        <span>{userNames[other.user_id] ?? 'them'}</span>
                        <span className="round-q-value">{PCT(other.forecast)}</span>
                        {question.my_forecast !== null && (
                          <span className="round-q-delta">
                            Δ {Math.round(
                              Math.abs(other.forecast - question.my_forecast) * 100,
                            )}
                          </span>
                        )}
                      </div>
                    ))}
                    {question.peer_read_error !== undefined && (
                      <div className="round-q-read">
                        you had {themName} at{' '}
                        {PCT(question.my_peer_forecast ?? 0)} — out by{' '}
                        <span className="round-q-delta">
                          {SIGNED(question.peer_read_error)}
                        </span>
                        {question.peer_read_error > 0
                          ? ' (you read them low)'
                          : question.peer_read_error < 0
                            ? ' (you read them high)'
                            : ' (exactly)'}
                      </div>
                    )}
                    {question.house && (
                      <div className="round-q-house">
                        <div className="round-q-other">
                          <span>{PARTICIPANT_NAME}</span>
                          <span className="round-q-value">
                            {PCT(question.house.forecast)}
                          </span>
                          {question.my_forecast !== null && (
                            <span className="round-q-delta">
                              Δ {Math.round(
                                Math.abs(
                                  question.house.forecast - question.my_forecast,
                                ) * 100,
                              )}
                            </span>
                          )}
                        </div>
                        {question.house.because && (
                          <div className="round-q-because">
                            {question.house.because}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ) : question.waiting_on_other ? (
                  <div className="round-q-sealed">
                    in — sealed until they answer
                    {question.house_committed && ' · the house is in too'}
                  </div>
                ) : (question.others_committed ?? 0) > 0 ? (
                  <div className="round-q-sealed">
                    they are in — yours is what unseals it
                  </div>
                ) : null}

                {/* The only tap that turns a closed question into a score. */}
                {awaitingVerdict && (
                  <div className="round-q-verdict">
                    <span className="round-q-label">what happened</span>
                    <button
                      className="round-q-submit"
                      disabled={busy === id}
                      onClick={() => void act(id, () =>
                        api.resolveRoundQuestion(roomId, id, 'correct'))}
                    >
                      it happened
                    </button>
                    <button
                      className="round-q-submit"
                      disabled={busy === id}
                      onClick={() => void act(id, () =>
                        api.resolveRoundQuestion(roomId, id, 'incorrect'))}
                    >
                      it didn't
                    </button>
                    <button
                      className="round-q-bin"
                      disabled={busy === id}
                      onClick={() => void act(id, () =>
                        api.resolveRoundQuestion(roomId, id, 'voided'))}
                    >
                      void
                    </button>
                  </div>
                )}

                {question.scores && question.scores.length > 0 && (
                  <div className="round-q-scores">
                    {question.scores.map((score) => (
                      <div
                        key={score.user_id ?? score.actor}
                        className={`round-q-score${
                          score.actor === 'house' ? ' is-house' : ''}`}
                      >
                        <span>
                          {score.actor === 'house'
                            ? PARTICIPANT_NAME
                            : (userNames[score.user_id ?? ''] ?? 'them')}
                        </span>
                        <span>Brier {score.brier.toFixed(3)}</span>
                        <span className="round-q-gap">
                          final {score.brier_final_answer.toFixed(3)}
                        </span>
                        {/* Coverage sits beside the Brier and never inside
                            it: a good score across a third of the question's
                            life is not a good score. */}
                        {score.coverage < 0.999 && (
                          <span className="round-q-gap">
                            in for {Math.round(score.coverage * 100)}%
                          </span>
                        )}
                        {score.peer !== null && (
                          <span className="round-q-peer">
                            {score.peer > 0 ? '+' : ''}{score.peer.toFixed(0)}
                          </span>
                        )}
                      </div>
                    ))}
                    <div className="round-q-meta">
                      head-to-head over {question.scores[0].contested_days} day
                      {question.scores[0].contested_days === 1 ? '' : 's'} you
                      were both in · probabilities clipped at 1% for the log
                      score
                    </div>
                  </div>
                )}

                {!settled && (
                  <div className="round-q-actions">
                    <button
                      className="round-q-bin"
                      disabled={busy === id}
                      onClick={() => void act(id, () =>
                        api.binRoundQuestion(roomId, id))}
                    >
                      bin it
                    </button>
                  </div>
                )}
              </>
            )}

            {refused[id] && (
              <div className="round-q-refused" role="status">{refused[id]}</div>
            )}
            {failed === id && (
              <div className="round-q-error" role="status">
                not recorded — try again
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
