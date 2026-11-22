import { longwayPath, longwayRequest, notifyLongwayChanged } from '../organs/longway/api'
import type { FriendNote, JourneyNotebook } from '../organs/longway/types'
import { useLongwayResource } from '../organs/longway/useLongwayResource'

type Contribution = Pick<FriendNote, 'kind' | 'text'> & { place: string | null; about: string | null }

export function useJourneyNotes(roomId: string, slug?: string | null) {
  const path = slug ? longwayPath(roomId, `notebook/${encodeURIComponent(slug)}`) : null
  const { data, error, refresh, update } = useLongwayResource<JourneyNotebook>(path, '', 300_000)

  async function postNote(suffix: string, body: Contribution | { why: string }) {
    if (!path) throw new Error('Choose a journey first.')
    const { note } = await longwayRequest<{ note: FriendNote }>(path + suffix, { method: 'POST', body: JSON.stringify(body) })
    update(book => ({ ...book, notes: book.notes.some(item => item.id === note.id)
      ? book.notes.map(item => item.id === note.id ? note : item) : [...book.notes, note] }))
    notifyLongwayChanged(roomId)
  }

  function add(contribution: Contribution) {
    return postNote('', contribution)
  }
  function review(id: string, decision: 'accept' | 'set-aside', why: string) {
    return postNote(`/${encodeURIComponent(id)}/${decision}`, { why })
  }
  async function scout() {
    if (!path) throw new Error('Choose a journey first.')
    await longwayRequest(path + '/scout', { method: 'POST' })
    notifyLongwayChanged(roomId)
  }

  return { data, error, refresh, add, review, scout }
}

export type JourneyNotes = ReturnType<typeof useJourneyNotes>
