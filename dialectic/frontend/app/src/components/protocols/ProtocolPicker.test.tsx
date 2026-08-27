import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProtocolPicker } from './ProtocolPicker'

// F-004: a dead socket must not close the modal and destroy the pasted claim.
function invokeSteelman(onInvoke: (t: string, c: Record<string, unknown>) => boolean) {
  const onClose = vi.fn()
  render(<ProtocolPicker onInvoke={onInvoke} onClose={onClose} />)
  fireEvent.click(screen.getByText(/^Steelman/))
  fireEvent.change(screen.getByPlaceholderText(/Enter the claim/), { target: { value: 'CLAIM_8185' } })
  fireEvent.click(screen.getByRole('button', { name: /^Invoke/ }))
  return onClose
}

describe('ProtocolPicker', () => {
  it('keeps the modal and the claim when the send fails', () => {
    const onClose = invokeSteelman(() => false)
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(/claim is kept/)
    expect((screen.getByPlaceholderText(/Enter the claim/) as HTMLTextAreaElement).value).toBe('CLAIM_8185')
  })

  it('closes when the send succeeds', () => {
    const onInvoke = vi.fn(() => true)
    const onClose = invokeSteelman(onInvoke)
    expect(onInvoke).toHaveBeenCalledWith('steelman', { target_claim: 'CLAIM_8185' })
    expect(onClose).toHaveBeenCalledOnce()
  })
})
