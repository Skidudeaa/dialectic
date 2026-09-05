import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MessageInput } from './MessageInput'
import { MessageBubble } from './MessageBubble'
import { FocusSources } from '../workspace/focus/FocusSources'
import type { Message } from '../../types'

vi.mock('../../lib/api', () => ({ api: { uploadAttachment: vi.fn() } }))
const message: Message = { id:'proof', thread_id:'thread', sequence:1,created_at:'2026-09-04T12:00:00Z', speaker_type:'human',user_id:'user',message_type:'text',content:'A **preserved** [source](https://example.test) and `code`.' }
describe('the packaged companion components in Dialectic', () => {
  it('keeps message rendering, quote structure and reply handlers', () => {
    const reply=vi.fn(); const {container}=render(<MessageBubble message={message} authorName="Fixture" isSelf onReply={reply} replyToContent="Quoted evidence" replyToAuthor="Source" />)
    expect(container.querySelector('.drc-response')).toBeInTheDocument()
    expect(screen.getByText('Quoted evidence')).toBeInTheDocument()
    expect(screen.getByRole('link',{name:'source'})).toHaveAttribute('href','https://example.test')
    fireEvent.click(screen.getByRole('button',{name:'Reply'})); expect(reply).toHaveBeenCalledWith('proof')
  })
  it('keeps unsent text when the real send callback refuses delivery', () => {
    const send=vi.fn(()=>false); const {container}=render(<MessageInput roomId="room" quiet initialValue="Keep the draft" onSend={send} />)
    expect(container.querySelector('.drc-composer')).toBeInTheDocument()
    fireEvent.keyDown(screen.getByRole('textbox'),{key:'Enter'}); expect(send).toHaveBeenCalledWith('Keep the draft','text',[],[])
    expect(screen.getByRole('textbox')).toHaveValue('Keep the draft')
  })
  it('uses the host source-navigation callback and preserves unresolved sources', () => {
    const navigate=vi.fn(); const {container}=render(<FocusSources sources={[{label:'Live source',onNavigate:navigate},{label:'Unresolved'}]}/> )
    expect(container.querySelector('.drc-context')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'Live source'})); expect(navigate).toHaveBeenCalledOnce()
    expect(screen.getByText('Unresolved')).toBeInTheDocument()
  })
  it('keeps a submitted draft until receipt and retains it when the server rejects the quote', async () => {
    let reject!: (error: Error) => void
    const pending = new Promise<boolean>((_resolve, fail) => { reject = fail })
    render(<MessageInput roomId="room" quiet initialValue="My evidence-based thought" onSend={() => pending} />)
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
    expect(screen.getByRole('textbox', { hidden: true })).toHaveValue('My evidence-based thought')
    await act(async () => reject(new Error('The source changed; reopen it before quoting')))
    expect(await screen.findByText('The source changed; reopen it before quoting')).toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('My evidence-based thought')
  })
  it('clears an acknowledged contribution only after it has been accepted', async () => {
    let accept!: (ok: boolean) => void
    const pending = new Promise<boolean>((resolve) => { accept = resolve })
    render(<MessageInput roomId="room" quiet initialValue="Keep until accepted" onSend={() => pending} />)
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' })
    expect(screen.getByRole('textbox', { hidden: true })).toHaveValue('Keep until accepted')
    await act(async () => accept(true))
    await waitFor(() => expect(screen.getByRole('textbox')).toHaveValue(''))
  })
})
