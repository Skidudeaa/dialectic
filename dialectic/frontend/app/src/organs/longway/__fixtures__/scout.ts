import type { ChartProposal, Question, ScoutedProposal, ScoutRun } from '../types'

export const proposal: ScoutedProposal & { field_mark_id: string | null } = {
  id: 'proposal-1', room_id: 'room', candidate: 'ogasawara', created_at: '2026-10-27T12:00:00Z',
  claim: 'The October crossing runs on Tuesdays.', support: 'In October 2027, the crossing departs Tokyo on Tuesdays.',
  url: 'https://operator.example/timetable', publisher: 'The ferry operator', scope: 'October timetable only',
  published_at: null, proposed_by: 'llm', proposer_user_id: null, source_message_id: null,
  review: 'proposed', written_sid: null, written_at: null, written_commit: null,
  question_id: 'question-1', question_text: 'Is there a boat in October?', run_id: 'run-1', search_result_id: 'search-1',
  contradicts: null, applies_from: '2027-10-01', applies_to: '2027-10-31', direction: 'outbound', passport: 'any', vehicle: 'Maru',
  leg_from: 'Tokyo (Takeshiba)', leg_to: 'Chichijima', load_bearing: true, counter_searched_at: '2026-10-27T12:00:00Z',
  requires_counter: false, publisher_count: 1, field_mark_id: 'field_mark:mark-1',
}
export const chartProposal: ChartProposal = {
  id: proposal.id, claim: proposal.claim, support: proposal.support, review: proposal.review,
  url: proposal.url, publisher: proposal.publisher, leg_from: proposal.leg_from, leg_to: proposal.leg_to,
  load_bearing: true, requires_counter: false,
}
export const question: Question = {
  id: 'question-1', room_id: 'room', journey: 'ogasawara', text: 'Is there a boat in October?',
  source: 'human', source_message_id: null, asked_by: 'me', created_at: '2026-10-27T11:00:00Z',
  answered_by_proposal: null, answer_review: null, closed_at: null,
}
export const run: ScoutRun = {
  id: 'run-1', room_id: 'room', journey: 'ogasawara', trigger: 'manual', started_by: 'me',
  started_at: '2026-10-27T11:00:00Z', finished_at: '2026-10-27T11:15:00Z', status: 'done', questions: [question.id],
  pages_read: 12, searches: 4, proposals: 5, counter_proposals: 2, input_tokens: 1000, output_tokens: 2000, error: null,
}
