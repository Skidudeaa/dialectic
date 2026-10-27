import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Message, MessageMetadata, WorkshopJob } from '../../types'
import { MessageBubble } from './MessageBubble'
import { api } from '../../lib/api'
import { useAppStore } from '../../stores/appStore'

vi.mock('../../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api')>('../../lib/api')
  return {
    ...actual,
    api: {
      getWorkshopJob: vi.fn(),
      killWorkshopJob: vi.fn(),
      getThreadDecisions: vi.fn(() => new Promise(() => {})),
    },
  }
})

afterEach(() => {
  useAppStore.setState({ currentRoom: null } as never)
  vi.clearAllMocks()
})

const JOB_ID = '44444444-4444-4444-8444-444444444444'

function job(status: WorkshopJob['status'], extra: Partial<WorkshopJob> = {}): WorkshopJob {
  return {
    id: JOB_ID, room_id: 'room-1', label: 'GBM sweep', language: 'python', status, timeout_s: 3600,
    started_at: '2026-10-27T08:00:00Z', finished_at: null, elapsed_s: 754, exit_code: null, commit_sha: null,
    changed_files: [], result_message_id: null, stdout_tail: 'path 1200/20000\n', stderr_tail: null, ...extra,
  }
}

function message(metadata: MessageMetadata): Message {
  return {
    id: 'm1', thread_id: 'thread-1', sequence: 2, created_at: '2026-10-27T08:00:00Z',
    speaker_type: 'llm_primary', message_type: 'text', user_id: null,
    content: 'Started the sweep in the background.', metadata,
  } as unknown as Message
}

const STARTED: MessageMetadata = {
  tools: { iterations: 1, degraded: false, calls: [
    { name: 'start_job', label: 'starting a workshop job', ok: true, input: { code: 'x' },
      provenance: { kind: 'workshop_job', job_id: JOB_ID, label: 'GBM sweep', timeout_s: 3600 } },
  ] },
}

describe('a background job on the message that started it', () => {
  it('shows the running job with its tail and a Stop that posts the kill', async () => {
    useAppStore.setState({ currentRoom: { id: 'room-1' } } as never)
    vi.mocked(api.getWorkshopJob).mockResolvedValue(job('running'))
    vi.mocked(api.killWorkshopJob).mockResolvedValue({ killed: true, job_id: JOB_ID })
    render(<MessageBubble message={message(STARTED)} authorName="Dialectic" isSelf={false} />)
    await waitFor(() => expect(screen.getByText(/job “GBM sweep” · running 12m/)).toBeInTheDocument())
    expect(api.getWorkshopJob).toHaveBeenCalledWith('room-1', JOB_ID)
    expect(screen.getByText('path 1200/20000')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(api.killWorkshopJob).toHaveBeenCalledWith('room-1', JOB_ID))
  })

  it('reads a finished job as finished with no Stop, and a failed one with its exit code', async () => {
    useAppStore.setState({ currentRoom: { id: 'room-1' } } as never)
    vi.mocked(api.getWorkshopJob).mockResolvedValueOnce(job('done', { exit_code: 0 }))
    const { unmount } = render(<MessageBubble message={message(STARTED)} authorName="Dialectic" isSelf={false} />)
    await waitFor(() => expect(screen.getByText(/job “GBM sweep” · finished/)).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
    unmount()
    vi.mocked(api.getWorkshopJob).mockResolvedValueOnce(job('failed', { exit_code: 3 }))
    render(<MessageBubble message={message(STARTED)} authorName="Dialectic" isSelf={false} />)
    await waitFor(() => expect(screen.getByText(/job “GBM sweep” · failed · exit 3/)).toBeInTheDocument())
  })

  it('renders nothing job-shaped on a human message or a failed start', () => {
    useAppStore.setState({ currentRoom: { id: 'room-1' } } as never)
    const failed: MessageMetadata = { tools: { iterations: 1, degraded: false, calls: [
      { name: 'start_job', label: 'starting a workshop job', ok: false, error: 'a job is already running' },
    ] } }
    render(<MessageBubble message={message(failed)} authorName="Dialectic" isSelf={false} />)
    expect(screen.queryByText(/job “/)).toBeNull()
    expect(api.getWorkshopJob).not.toHaveBeenCalled()
  })
})
