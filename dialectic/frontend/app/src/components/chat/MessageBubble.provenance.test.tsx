import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Message } from '../../types'
import { MessageBubble } from './MessageBubble'
import { useAppStore } from '../../stores/appStore'
import { useMessageDecisions, type MessageDecisionsState } from '../../hooks/useMessageDecisions'

/**
 * The point of this feature: a machine message must carry SOME visible
 * indication of why it exists, and the raw `reason` string the server
 * records (llm/heuristics.py, llm/wire.py, ...) must never reach the user
 * verbatim — api/decisions.py's own docstring and the build brief both say
 * so explicitly ("wire_interjection must not reach the user as the string
 * 'wire_interjection'").
 *
 * The hook itself (fetch dedup, caching, the loading/ready/unavailable
 * states) is tested in hooks/useMessageDecisions.test.tsx. This file mocks
 * the hook directly so each test can hand MessageBubble an exact decisions
 * state and assert on what it RENDERS from it — the translation table and
 * the wiring, not the network behavior.
 */

vi.mock('../../hooks/useMessageDecisions', () => ({
  useMessageDecisions: vi.fn(),
}))

afterEach(() => {
  useAppStore.setState({ currentRoom: null } as never)
  vi.clearAllMocks()
})

function mockDecisions(state: MessageDecisionsState) {
  vi.mocked(useMessageDecisions).mockReturnValue(state)
}

const THREAD = 'thread-prov-1'
const MID = '33333333-3333-4333-8333-333333333333'

function message(overrides: Partial<Message> = {}): Message {
  return {
    id: MID,
    thread_id: THREAD,
    sequence: 1,
    created_at: '2026-08-21T12:00:00Z',
    speaker_type: 'llm_primary',
    message_type: 'text',
    content: 'The Baltic Dry index moved on the Hormuz thesis.',
    ...overrides,
  } as unknown as Message
}

function renderBubble(msg: Message) {
  useAppStore.setState({ currentRoom: { id: 'room-1', name: 'R', token: 't', is_home: false } } as never)
  return render(<MessageBubble message={msg} isSelf={false} authorName="Dialectic" />)
}

async function openWhy() {
  const trigger = await screen.findByRole('button', { name: 'Why this message appeared' })
  fireEvent.click(trigger)
  return trigger
}

describe('provenance disclosure', () => {
  it('never renders on a human message, in any decisions state', () => {
    mockDecisions({ status: 'ready', decisions: {} })
    renderBubble(message({ speaker_type: 'human' }))
    expect(screen.queryByRole('button', { name: 'Why this message appeared' })).toBeNull()
  })

  it('renders on a machine message even with nothing in the decisions map', () => {
    mockDecisions({ status: 'ready', decisions: {} })
    renderBubble(message())
    expect(screen.getByRole('button', { name: 'Why this message appeared' })).toBeInTheDocument()
  })

  it('is collapsed by default', () => {
    mockDecisions({ status: 'ready', decisions: {} })
    renderBubble(message())
    expect(screen.queryByRole('note')).toBeNull()
  })

  describe('translates every reason the server can record — the raw string never leaks', () => {
    const cases: Array<[string, string]> = [
      ['explicit_mention', 'You addressed it directly, by name.'],
      ['question_detected', 'Your last message read as a question.'],
      ['balance_redirect', 'One of you had been quiet a while, relative to the room.'],
      ['wire_interjection', 'A news story crossed the relevance threshold it holds for the linked thesis.'],
      ['world_interjection', 'A live feed reported something inside geography this room placed and bound to the thesis.'],
      ['silence_follow_up', 'It had asked something here and nobody had answered yet.'],
      ['protocol_active', 'A structured protocol was running, and this was its turn.'],
      ['forced', 'Something in the room asked it to respond directly.'],
      ['turn_threshold_exceeded (9 >= 8)', 'A stretch of turns had passed with nothing from it.'],
      ['semantic_novelty_spike (0.91)', 'The conversation had shifted into territory it hadn’t weighed in on yet.'],
      ['some_future_reason_nobody_has_written_copy_for', 'It decided to speak — the specific reason isn’t translated here yet.'],
    ]

    for (const [reason, expected] of cases) {
      it(`"${reason}"`, async () => {
        mockDecisions({
          status: 'ready',
          decisions: { [MID]: {
            reason, confidence: null, mode: 'primary', use_provoker: false,
            human_turn_count: null, semantic_novelty: null, unsurfaced_memory_count: null,
          } },
        })
        renderBubble(message())
        await openWhy()
        expect(screen.getByText(expected)).toBeInTheDocument()
        // The raw reason string is never the rendered headline — matters
        // most for the ones with no dedicated case above.
        expect(screen.queryByText(reason)).toBeNull()
      })
    }
  })

  it('marks stagnation_detected as historical, not as a live feature', async () => {
    mockDecisions({
      status: 'ready',
      decisions: { [MID]: {
        reason: 'stagnation_detected', confidence: 0.5, mode: 'primary', use_provoker: false,
        human_turn_count: null, semantic_novelty: null, unsurfaced_memory_count: null,
      } },
    })
    renderBubble(message())
    await openWhy()
    expect(screen.getByText(/retired 2026-08-15/)).toBeInTheDocument()
  })

  it('shows the turn count as a detail line when the reason is the turn-threshold rung', async () => {
    mockDecisions({
      status: 'ready',
      decisions: { [MID]: {
        reason: 'turn_threshold_exceeded (9 >= 8)', confidence: 0.8, mode: 'primary',
        use_provoker: false, human_turn_count: 9, semantic_novelty: null,
        unsurfaced_memory_count: null,
      } },
    })
    renderBubble(message())
    await openWhy()
    expect(screen.getByText('9 human turns in a row before it spoke.')).toBeInTheDocument()
    expect(screen.getByText('Recorded confidence 80%.')).toBeInTheDocument()
  })

  it('does NOT show the turn count as a detail when it is present but the reason is unrelated', async () => {
    // human_turn_count rides every heuristic decision regardless of which
    // rung fired; only the turn-threshold rung's OWN count is legible detail.
    mockDecisions({
      status: 'ready',
      decisions: { [MID]: {
        reason: 'question_detected', confidence: 0.7, mode: 'primary',
        use_provoker: false, human_turn_count: 3, semantic_novelty: null,
        unsurfaced_memory_count: null,
      } },
    })
    renderBubble(message())
    await openWhy()
    expect(screen.queryByText(/human turns? in a row/)).toBeNull()
  })

  it('names provoker mode as a detail line when use_provoker is true', async () => {
    mockDecisions({
      status: 'ready',
      decisions: { [MID]: {
        reason: 'semantic_novelty_spike (0.91)', confidence: 0.91, mode: 'provoker',
        use_provoker: true, human_turn_count: null, semantic_novelty: 0.91,
        unsurfaced_memory_count: null,
      } },
    })
    renderBubble(message())
    await openWhy()
    expect(screen.getByText(/provoker mode/)).toBeInTheDocument()
    expect(screen.getByText('Novelty score 0.91 against its own threshold.')).toBeInTheDocument()
  })

  it('falls back to metadata.source when there is no decision row', async () => {
    mockDecisions({ status: 'ready', decisions: {} })
    renderBubble(message({ metadata: { source: 'trading_curator' } }))
    await openWhy()
    expect(screen.getByText(/desk pushed a thesis update/)).toBeInTheDocument()
  })

  it('decision data wins over metadata.source when — hypothetically — both are present', async () => {
    mockDecisions({
      status: 'ready',
      decisions: { [MID]: {
        reason: 'explicit_mention', confidence: 1, mode: 'primary', use_provoker: false,
        human_turn_count: null, semantic_novelty: null, unsurfaced_memory_count: null,
      } },
    })
    renderBubble(message({ metadata: { source: 'trading_curator' } }))
    await openWhy()
    expect(screen.getByText('You addressed it directly, by name.')).toBeInTheDocument()
    expect(screen.queryByText(/desk pushed a thesis update/)).toBeNull()
  })

  it('falls back to a role-based note for the annotator, which never logs a decision', async () => {
    mockDecisions({ status: 'ready', decisions: {} })
    renderBubble(message({ speaker_type: 'llm_annotator' }))
    await openWhy()
    expect(screen.getByText('A note left for whoever was offline — not a reply in the conversation.')).toBeInTheDocument()
  })

  it('still explains a message while the fetch is loading, from role alone', async () => {
    mockDecisions({ status: 'loading' })
    renderBubble(message({ speaker_type: 'llm_provoker' }))
    await openWhy()
    expect(screen.getByText('A provoker turn — no decision record survives for this one.')).toBeInTheDocument()
  })

  it('degrades to the role fallback, not to nothing, when the fetch failed', async () => {
    mockDecisions({ status: 'unavailable' })
    renderBubble(message())
    await openWhy()
    expect(screen.getByText('A primary turn — no decision record survives for this one.')).toBeInTheDocument()
  })

  describe('accessibility contract (mirrors common/Explain.tsx)', () => {
    it('Escape closes the panel and returns focus to the trigger', async () => {
      mockDecisions({ status: 'ready', decisions: {} })
      renderBubble(message())
      const trigger = await openWhy()
      expect(screen.getByRole('note')).toBeInTheDocument()
      fireEvent.keyDown(document, { key: 'Escape' })
      await waitFor(() => expect(screen.queryByRole('note')).toBeNull())
      expect(trigger).toHaveFocus()
    })

    it('a click outside the panel closes it', async () => {
      mockDecisions({ status: 'ready', decisions: {} })
      renderBubble(message())
      await openWhy()
      expect(screen.getByRole('note')).toBeInTheDocument()
      fireEvent.mouseDown(document.body)
      await waitFor(() => expect(screen.queryByRole('note')).toBeNull())
    })

    it('a scroll closes the panel', async () => {
      mockDecisions({ status: 'ready', decisions: {} })
      renderBubble(message())
      await openWhy()
      expect(screen.getByRole('note')).toBeInTheDocument()
      fireEvent.scroll(window)
      await waitFor(() => expect(screen.queryByRole('note')).toBeNull())
    })

    it('the trigger is a real button with aria-expanded, toggled by the click', async () => {
      mockDecisions({ status: 'ready', decisions: {} })
      renderBubble(message())
      const trigger = screen.getByRole('button', { name: 'Why this message appeared' })
      expect(trigger.tagName).toBe('BUTTON')
      expect(trigger).toHaveAttribute('aria-expanded', 'false')
      fireEvent.click(trigger)
      expect(trigger).toHaveAttribute('aria-expanded', 'true')
    })
  })
})
