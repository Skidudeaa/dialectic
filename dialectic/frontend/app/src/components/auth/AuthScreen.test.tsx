import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthScreen } from './AuthScreen'
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import { api } from '../../lib/api.ts'

// The signed-out screen is the first thing anyone ever sees of this product,
// and it said four words: "Collaborative reasoning engine". These tests fence
// the two failures that cost a new user the most — a screen that never says
// what the thing IS, and a door that looks open but is not.

vi.mock('../../lib/api.ts', () => ({
  api: {
    forgotPassword: vi.fn(),
    getCapabilities: vi.fn(),
    setAccessToken: vi.fn(),
  },
}))

const mockCapabilities = (signups_enabled: boolean, guest_access_enabled = false) => {
  vi.mocked(api.getCapabilities).mockResolvedValue({ signups_enabled, guest_access_enabled })
}

describe('AuthScreen — the front door', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockCapabilities(false)
  })

  it('says what Dialectic actually is, not just a tagline', () => {
    render(<AuthScreen />)
    // The load-bearing idea: the third participant is a participant, not an
    // assistant waiting to be prompted. A new user who misses this misreads
    // every other surface in the product.
    expect(screen.getByTestId('auth-premise')).toHaveTextContent(/participant/i)
  })

  it('names the participant from product identity, never a provider', () => {
    const { container } = render(<AuthScreen />)
    expect(container.textContent).toContain(PARTICIPANT_NAME)
    // Provider names belong in technical provenance, never a product label.
    expect(container.textContent).not.toMatch(/\bClaude\b/)
  })

  it('says the account door is closed BEFORE the form is filled in', async () => {
    render(<AuthScreen />)
    fireEvent.click(screen.getByRole('tab', { name: /create account/i }))
    // Today this only surfaces as a 403 AFTER three fields and a submit.
    expect(await screen.findByTestId('signup-closed-notice')).toHaveTextContent(
      /invite/i,
    )
  })

  it('offers no form it knows the server will refuse', async () => {
    render(<AuthScreen />)
    fireEvent.click(screen.getByRole('tab', { name: /create account/i }))
    await screen.findByTestId('signup-closed-notice')
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  })

  it('opens the account form when the server says signups are open', async () => {
    mockCapabilities(true)
    render(<AuthScreen />)
    fireEvent.click(screen.getByRole('tab', { name: /create account/i }))
    // The door is not hardcoded shut — it follows the deployment.
    await waitFor(() => {
      expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    })
    expect(screen.queryByTestId('signup-closed-notice')).not.toBeInTheDocument()
  })

  it('offers no guest door while guests are closed', async () => {
    // Owner ruling 2026-08-13: no guests for now. The server refuses POST
    // /users, so a tab here would be a door onto a 403 — the same defect the
    // Create Account tab had.
    render(<AuthScreen />)
    await screen.findByRole('tab', { name: /sign in/i })
    expect(screen.queryByRole('tab', { name: /invite link/i })).not.toBeInTheDocument()
  })

  it('tells a guest what the identity does not get them, when guests are open', async () => {
    mockCapabilities(false, true)
    render(<AuthScreen />)
    const tab = await screen.findByRole('tab', { name: /invite link/i })
    fireEvent.click(tab)
    // A guest identity carries no JWT, so every newer surface (the workroom
    // projection, Home, memory promotion) refuses it. Saying "no account
    // needed" without saying that is the lie this fences.
    expect(screen.getByTestId('guest-limits')).toBeInTheDocument()
  })

  it('does not guess the guest door open while the answer is in flight', () => {
    vi.mocked(api.getCapabilities).mockReturnValue(new Promise(() => {}))
    render(<AuthScreen />)
    expect(screen.queryByRole('tab', { name: /invite link/i })).not.toBeInTheDocument()
  })

  it('never claims a capability it has not heard back about', () => {
    // Unresolved promise: the screen must not guess "open" while in flight.
    vi.mocked(api.getCapabilities).mockReturnValue(new Promise(() => {}))
    render(<AuthScreen />)
    fireEvent.click(screen.getByRole('tab', { name: /create account/i }))
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  })

  it('reports unavailable password recovery without claiming a code was sent', async () => {
    vi.mocked(api.forgotPassword).mockRejectedValue(
      new Error('Password recovery is unavailable because email delivery is not configured'),
    )
    render(<AuthScreen />)
    fireEvent.change(screen.getByLabelText(/^email$/i), {
      target: { value: 'amo@example.com' },
    })
    fireEvent.click(screen.getByRole('button', { name: /forgot password/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Password recovery is unavailable because email delivery is not configured',
    )
    expect(screen.queryByText(/code sent/i)).not.toBeInTheDocument()
  })
})
