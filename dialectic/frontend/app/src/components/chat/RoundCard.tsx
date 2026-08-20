import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/api.ts'
import type { RoundQuestion, RoundState } from '../../types'
import './RoundCard.css'

interface RoundCardProps {
  roomId: string
  messageId: string
  /** Display names by user id, so a forecaster is a person and not a UUID. */
  userNames?: Record<string, string>
}

const PCT = (value: number) => `${Math.round(value * 100)}%`

/**
 * The Sunday Round, in the transcript where both of them already are.
 *
 * Two rules this component exists to honour and must not quietly soften:
 *
 * BLINDNESS IS THE SERVER'S. Until you have forecast a question, the other
 * person's number is ABSENT from the response — `others` is undefined, not a
 * value to hide. So there is nothing here to accidentally render, and nothing
 * to "reveal" client-side. If you ever find yourself writing a conditional
 * that hides a number you were sent, the rule has already been broken
 * upstream.
 *
 * A FAILURE MUST SAY SO. Copied from MessageMarks: silently doing nothing
 * after a tap reads as "my forecast was recorded", which is the worst
 * possible lie for a scoring surface.
 */
export function RoundCard({ roomId, messageId, userNames = {} }: RoundCardProps) {
  const [state, setState] = useState<RoundState | null>(null)
  const [draft, setDraft] = useState<Record<string, number>>({})
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

  const submit = async (question: RoundQuestion) => {
    const value = draft[question.commitment_id]
      ?? question.my_forecast
      ?? 0.5
    setBusy(question.commitment_id)
    setFailed(null)
    setRefused((prev) => {
      const next = { ...prev }
      delete next[question.commitment_id]
      return next
    })
    try {
      setState(await api.recordForecast(roomId, question.commitment_id, value))
    } catch (error) {
      // A 409 is the server refusing on purpose — a closed or binned
      // question. That is not a transport failure and must read differently:
      // "try again" would be a lie, because it will never be accepted.
      const detail = (error as { body?: { detail?: string } })?.body?.detail
      const status = (error as { status?: number })?.status
      if (status === 409 && detail) {
        setRefused((prev) => ({ ...prev, [question.commitment_id]: detail }))
        void load()
      } else {
        setFailed(question.commitment_id)
      }
    } finally {
      setBusy(null)
    }
  }

  const bin = async (question: RoundQuestion) => {
    setBusy(question.commitment_id)
    setFailed(null)
    try {
      setState(await api.binRoundQuestion(roomId, question.commitment_id))
    } catch {
      setFailed(question.commitment_id)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="round-card">
      {state.questions.map((question, index) => {
        const id = question.commitment_id
        const binned = question.status === 'binned'
        const value = draft[id] ?? question.my_forecast ?? 0.5
        return (
          <div key={id} className={`round-q ${binned ? 'binned' : ''}`}>
            <div className="round-q-head">
              <span className="round-q-n">{index + 1}</span>
              <span className="round-q-claim">{question.claim}</span>
            </div>
            {question.closes && (
              <div className="round-q-meta">closes {question.closes}</div>
            )}

            {binned ? (
              <div className="round-q-binned">binned — never scored</div>
            ) : (
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

                {question.my_forecast !== null && (
                  <div className="round-q-mine">
                    yours: {PCT(question.my_forecast)}
                    {question.my_revisions > 1
                      && ` · ${question.my_revisions} revisions`}
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
                  </div>
                ) : question.waiting_on_other ? (
                  <div className="round-q-sealed">
                    in — sealed until they answer
                  </div>
                ) : (question.others_committed ?? 0) > 0 ? (
                  <div className="round-q-sealed">
                    they are in — yours is what unseals it
                  </div>
                ) : null}

                {question.scores && question.scores.length > 0 && (
                  <div className="round-q-scores">
                    {question.scores.map((score) => (
                      <div key={score.user_id} className="round-q-score">
                        <span>{userNames[score.user_id] ?? 'them'}</span>
                        <span>Brier {score.brier.toFixed(3)}</span>
                        <span className="round-q-gap">
                          final {score.brier_final_answer.toFixed(3)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}

                <div className="round-q-actions">
                  <button
                    className="round-q-bin"
                    disabled={busy === id}
                    onClick={() => void bin(question)}
                  >
                    bin it
                  </button>
                </div>
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
