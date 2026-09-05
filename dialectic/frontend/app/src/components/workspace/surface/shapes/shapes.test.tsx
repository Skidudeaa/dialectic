import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { MessageAnchor, MessageRef } from '../../../../types'
import { WHOLE_ROOM_TOPIC, type DailyActivity, type SurfaceAuthor, type SurfaceMsg } from '../surfaceModel'
import { SurfaceMessage } from './SurfaceMessage'
import { ShapeStream } from './ShapeStream'
import { ShapeTree } from './ShapeTree'
import { ShapeLanes } from './ShapeLanes'
import { ShapeSignal } from './ShapeSignal'
import { api } from '../../../../lib/api'
import { useAppStore } from '../../../../stores/appStore'

function human(id: string, name: string): SurfaceAuthor {
  return { id, name, kind: 'human', glyph: name.charAt(0).toUpperCase(), isSelf: false }
}

function machine(role?: 'primary' | 'provoker' | 'annotator'): SurfaceAuthor {
  return { id: 'dialectic', name: 'Dialectic', kind: 'machine', glyph: ')', role, isSelf: false }
}

let seq = 0
function msg(overrides: Partial<SurfaceMsg> & { author: SurfaceAuthor }): SurfaceMsg {
  seq += 1
  return {
    id: overrides.id ?? `m${seq}`,
    author: overrides.author,
    createdAt: overrides.createdAt ?? '2026-09-01T10:00:00Z',
    time: overrides.time ?? '10:00',
    text: overrides.text ?? 'hello',
    anchor: overrides.anchor ?? null,
    refs: overrides.refs ?? [],
    parentId: overrides.parentId ?? null,
    tools: overrides.tools ?? [],
    isNew: overrides.isNew ?? false,
    isStreaming: overrides.isStreaming ?? false,
    topic: overrides.topic ?? WHOLE_ROOM_TOPIC,
    message: overrides.message ?? {
      id: overrides.id ?? `m${seq}`, thread_id: 'thread', sequence: seq,
      created_at: overrides.createdAt ?? '2026-09-01T10:00:00Z',
      speaker_type: overrides.author.kind === 'human' ? 'human' : 'llm_primary',
      user_id: overrides.author.kind === 'human' ? overrides.author.id : null,
      user_name: overrides.author.name,
      content: overrides.text ?? 'hello', message_type: 'text',
      references_message_id: overrides.parentId,
      metadata: { ...(overrides.anchor ? { anchor: overrides.anchor } : {}), refs: overrides.refs },
    },
  }
}

describe('SurfaceMessage', () => {
  it('renders the author name', () => {
    render(<SurfaceMessage msg={msg({ author: human('u1', 'Amo'), text: 'hi there' })} />)
    expect(screen.getByText('Amo')).toBeInTheDocument()
  })

  it('calls onAnchor with the anchor when the anchor chip is tapped', () => {
    const onAnchor = vi.fn()
    const anchor: MessageAnchor = { kind: 'node', id: 'n1', label: 'Cascade phase' }
    render(<SurfaceMessage msg={msg({ author: human('u1', 'Amo'), anchor })} onAnchor={onAnchor} />)
    fireEvent.click(screen.getByRole('button', { name: /ON Cascade phase/ }))
    expect(onAnchor).toHaveBeenCalledWith(anchor)
  })

  it('calls onOpenRef with the ref when a ref chip is tapped', () => {
    const onOpenRef = vi.fn()
    const ref: MessageRef = { entity: 'reading_items', id: 'r1', label: 'GDELT wire hit' }
    render(<SurfaceMessage msg={msg({ author: human('u1', 'Amo'), refs: [ref] })} onOpenRef={onOpenRef} />)
    fireEvent.click(screen.getByRole('button', { name: /GDELT wire hit/ }))
    expect(onOpenRef).toHaveBeenCalledWith(ref)
  })
})

describe('ShapeStream', () => {
  it('keeps a Round actionable on the default Surface', async () => {
    const previousRoom = useAppStore.getState().currentRoom
    useAppStore.setState({ currentRoom: { id: 'room', name: 'Room', token: 'token', is_home: false } })
    const state = { message_id: 'round', peers: [], questions: [{
      commitment_id: 'q', claim: 'Will shipping resume by Friday?', closes: '2099-09-10', status: 'active',
      resolution: null, my_forecast: null, my_peer_forecast: null, my_revisions: 0,
      house_committed: false, revealed: false, waiting_on_other: false,
    }] }
    vi.spyOn(api, 'readRound').mockResolvedValue(state)
    const forecast = vi.spyOn(api, 'recordForecast').mockResolvedValue(state)
    const round = msg({ id: 'round', author: machine(), text: 'The Round' })
    round.message.metadata = { question_round: { opened: '2026-09-05', questions: [] } }
    try {
      render(<ShapeStream messages={[round]} onOpenRef={vi.fn()} />)
      await screen.findByText('Will shipping resume by Friday?')
      fireEvent.change(screen.getByRole('slider', { name: 'you' }), { target: { value: '0.7' } })
      fireEvent.click(screen.getByRole('button', { name: 'lock in' }))
      await waitFor(() => expect(forecast).toHaveBeenCalledWith('room', 'q', 0.7, undefined, null))
    } finally {
      act(() => useAppStore.setState({ currentRoom: previousRoom }))
    }
  })

  it('renders every message', () => {
    const messages = [
      msg({ id: 'm1', author: human('u1', 'Amo'), text: 'first' }),
      msg({ id: 'm2', author: machine('primary'), text: 'second' }),
    ]
    render(<ShapeStream messages={messages} onOpenRef={vi.fn()} />)
    expect(screen.getByText('first')).toBeInTheDocument()
    expect(screen.getByText('second')).toBeInTheDocument()
  })

  it('keeps the source inspector available beside a conversation without viewport-dependent links', () => {
    const messages = [
      msg({ author: human('u1', 'Amo'), refs: [{ entity: 'memories', id: 'x1', label: 'a memory' }] }),
    ]
    render(<ShapeStream messages={messages} context={<aside>Choose a reading</aside>} onOpenRef={vi.fn()} />)
    expect(screen.getByText('Choose a reading')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /a memory/ })).toBeEnabled()
  })
})

describe('ShapeTree', () => {
  it('nests a reply under its parent', () => {
    const root = msg({ id: 'root1', author: human('u1', 'Amo'), text: 'the claim' })
    const reply = msg({ id: 'reply1', author: machine('primary'), text: 'a reply', parentId: 'root1' })
    render(<ShapeTree messages={[root, reply]} onOpenRef={vi.fn()} />)
    const rootNode = screen.getByText('the claim').closest('.surf-tree-node')!
    const replyArticle = screen.getByText('a reply').closest('article')!
    expect(rootNode.contains(replyArticle)).toBe(true)
  })

  it('lists a merge candidate for a ref shared by two root trees', () => {
    const sharedRef: MessageRef = { entity: 'field_marks', id: 'fm1', label: 'confluence trigger' }
    const rootA = msg({ id: 'a', author: human('u1', 'Amo'), text: 'root A', refs: [sharedRef] })
    const rootB = msg({ id: 'b', author: human('u2', 'Dan'), text: 'root B', refs: [sharedRef] })
    render(<ShapeTree messages={[rootA, rootB]} onOpenRef={vi.fn()} />)
    expect(screen.getByText(/MERGE CANDIDATES/)).toBeInTheDocument()
    expect(screen.getByText(/confluence trigger — 2 trees/)).toBeInTheDocument()
  })
})

describe('ShapeLanes', () => {
  it('puts a machine message in the machine column and names whose move', () => {
    const amo = human('u1', 'Amo')
    const machineMsg = msg({ author: machine('primary'), text: 'machine says' })
    render(<ShapeLanes messages={[machineMsg]} humans={[amo]} onOpenRef={vi.fn()} />)
    const cell = screen.getByText('machine says').closest('.surf-lane-cell')!
    expect(cell.querySelector('.surf-lane-cell-author')?.textContent).toBe('Dialectic')
    // Amo has said nothing in this band, so it reads as his move.
    expect(screen.getByText(/move: Amo/)).toBeInTheDocument()
  })
})

describe('ShapeSignal', () => {
  it('renders the ratio line from rows and the two state lines', () => {
    const activity: DailyActivity = {
      days: 2,
      rows: [
        { day: '2026-09-01', human: 5, llm_primary: 2, llm_provoker: 1, llm_annotator: 0, system: 0 },
        { day: '2026-09-02', human: 3, llm_primary: 1, llm_provoker: 0, llm_annotator: 1, system: 0 },
      ],
    }
    render(
      <ShapeSignal activity={activity} status="ready" annotatorEnabled={false} addressedOnly={true} />,
    )
    // human total 8, machine total (3+1+1)=5 -> 0.6 : 1
    expect(screen.getByText('machine : human = 0.6 : 1')).toBeInTheDocument()
    expect(screen.getByText('Annotator silent · writes marks only')).toBeInTheDocument()
    expect(screen.getByText('Dialectic speaks when addressed or a gate fires')).toBeInTheDocument()
  })
})
