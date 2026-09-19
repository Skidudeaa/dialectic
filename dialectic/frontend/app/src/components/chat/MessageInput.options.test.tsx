import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MessageInput } from './MessageInput'

vi.mock('../../lib/api', () => ({ api: { uploadAttachment: vi.fn() } }))

/** The compact composer (reading rooms) spends no row on options nobody is
 *  using; ··· is the way in, and anything that would be sent stays visible. */
describe('MessageInput — compact options row', () => {
  const row = () => document.querySelector('.composer-options')

  it('is absent until ··· opens it, and ··· closes it again', () => {
    render(<MessageInput roomId="room-1" onSend={() => true} compactOptions />)
    const toggle = screen.getByRole('button', { name: 'Message options' })
    expect(row()).toBeNull()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(toggle)
    expect(row()).toHaveAttribute('open')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(toggle)
    expect(row()).toBeNull()
  })

  it('stays as a status line while a tag would otherwise be sent unseen', () => {
    render(<MessageInput roomId="room-1" onSend={() => true} compactOptions />)
    const toggle = screen.getByRole('button', { name: 'Message options' })
    fireEvent.click(toggle)
    const tag = document.querySelector<HTMLButtonElement>('.tag-btn')!
    fireEvent.click(tag)
    fireEvent.click(toggle)
    expect(row()).not.toBeNull()
    expect(row()).not.toHaveAttribute('open')
    expect(row()!.querySelector('summary')!.textContent).toContain(tag.textContent!.trim().toLowerCase())
  })

  it('leaves the ordinary composer exactly as it was', () => {
    render(<MessageInput roomId="room-1" onSend={() => true} />)
    expect(row()).not.toBeNull()
    expect(screen.queryByRole('button', { name: 'Message options' })).toBeNull()
  })
})
