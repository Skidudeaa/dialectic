import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MessageInput } from './MessageInput'

/**
 * TG-E easement (PLAN.md §5.5 amendment, owner-ruled): `initialValue` seeds
 * the composer once, on mount, for device-local draft restoration
 * (§15.2/§7.6's "type a draft, reload: draft present, unsent" checklist
 * item). It is a plain `useState` initial value, not a controlled prop — a
 * later change to the prop must not overwrite what the user is typing. This
 * file covers only that seam; the rest of MessageInput's behavior is TG-C/
 * TG-F's own territory.
 */

vi.mock('../../lib/api', () => ({ api: { uploadAttachment: vi.fn() } }))

describe('MessageInput — draft restoration easement', () => {
  it('seeds the textarea from initialValue on mount', () => {
    render(<MessageInput roomId="room-1" onSend={() => true} initialValue="half a sentence" quiet />)
    expect(screen.getByRole('textbox')).toHaveValue('half a sentence')
  })

  it('defaults to empty when no initialValue is given — unchanged behavior', () => {
    render(<MessageInput roomId="room-1" onSend={() => true} quiet />)
    expect(screen.getByRole('textbox')).toHaveValue('')
  })

  it('does not re-seed or clobber typing when the prop changes after mount', () => {
    const { rerender } = render(
      <MessageInput roomId="room-1" onSend={() => true} initialValue="first" quiet />,
    )
    const textarea = screen.getByRole('textbox')
    expect(textarea).toHaveValue('first')

    fireEvent.change(textarea, { target: { value: 'first, edited' } })

    // A later render with a DIFFERENT initialValue (e.g. continuity's own
    // capture effect writing back what was just typed) must not overwrite
    // what the user is actively typing — useState's initial argument is
    // only consulted once, on the component's first render.
    rerender(<MessageInput roomId="room-1" onSend={() => true} initialValue="second" quiet />)
    expect(textarea).toHaveValue('first, edited')
  })
})
