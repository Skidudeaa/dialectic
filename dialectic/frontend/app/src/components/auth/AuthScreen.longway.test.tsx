import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthScreen } from './AuthScreen'
import { api } from '../../lib/api'

vi.mock('../../organ', () => ({
  ORGAN: 'longway',
  IDENTITY: {
    name: 'The Long Way', shortName: 'Long Way', participantName: 'Scout', signature: ')',
    lede: 'Go far enough to be surprised. Stay long enough to understand. Leave room to be changed.',
    originImprint: 'The Long Way',
  },
}))
vi.mock('../../lib/api', () => ({ api: { getCapabilities: vi.fn(), setAccessToken: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getCapabilities).mockResolvedValue({ signups_enabled: false, guest_access_enabled: false })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

async function fillAsk(note = '') {
  render(<AuthScreen />)
  fireEvent.click(await screen.findByRole('tab', { name: 'Ask for a seat' }))
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Ada' } })
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'ada@example.com' } })
  fireEvent.change(screen.getByLabelText('Who are you, and who do you know here?'), { target: { value: note } })
}

describe('The Long Way seat request door', () => {
  it.each(['', 'I know Jo.'])('asks without credentials and keeps the asked state: %j', async note => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })))
    vi.stubGlobal('fetch', fetch)
    await fillAsk(note)
    expect(screen.getByText('The Long Way is invite-only.')).toBeVisible()
    expect(screen.getByText('Amo decides who gets a seat.')).toBeVisible()
    expect(screen.getByLabelText('Name')).toBeRequired()
    expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email')
    expect(screen.getByLabelText('Email')).toBeRequired()
    expect(screen.getByRole('textbox', { name: 'Who are you, and who do you know here?' })).toHaveAttribute('maxlength', '1000')
    expect(screen.getByRole('textbox', { name: 'Who are you, and who do you know here?' })).not.toBeRequired()
    fireEvent.click(screen.getByRole('button', { name: 'Ask for a seat' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Asked. Amo decides who gets a seat; you will hear by email.')
    expect(screen.getByRole('status')).toHaveTextContent('“I have a code” under Sign In')
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)
    const [path, init] = fetch.mock.calls[0]
    expect(path).toBe('/organ/longway/invite-requests')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ name: 'Ada', email: 'ada@example.com', note })
    const headers = new Headers(init.headers)
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(headers.has('Authorization')).toBe(false)
    expect(headers.has('X-Room-Token')).toBe(false)
    fireEvent.click(screen.getByRole('tab', { name: 'Sign In' }))
    fireEvent.click(screen.getByRole('button', { name: 'I have a code' }))
    expect(screen.getByLabelText('Your code')).toBeVisible()
    fireEvent.click(screen.getByRole('tab', { name: 'Ask for a seat' }))
    expect(screen.getByRole('status')).toHaveTextContent('Asked.')
  })

  it.each([
    [429, { detail: 'Too many requests. Please try again later.' }, 'Too many asks from here. Try again later.'],
    [403, { detail: 'Requests are closed' }, 'Requests are closed'],
    [422, { detail: [{ loc: ['body', 'email'], msg: 'Invalid email', type: 'value_error' }] }, 'Invalid email'],
    [500, {}, 'Could not send your request'],
  ])('shows the error and preserves the form on %s', async (status, body, message) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: status as number })))
    await fillAsk('I know Jo.')
    fireEvent.click(screen.getByRole('button', { name: 'Ask for a seat' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(message as string)
    expect(screen.getByLabelText('Name')).toHaveValue('Ada')
    expect(screen.getByRole('button', { name: 'Ask for a seat' })).toBeEnabled()
  })

  it('disables repeat submissions until the response arrives', async () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    await fillAsk()
    fireEvent.click(screen.getByRole('button', { name: 'Ask for a seat' }))
    expect(screen.getByRole('button', { name: 'Asking...' })).toBeDisabled()
  })

  it('retains account creation when signups are enabled', async () => {
    vi.mocked(api.getCapabilities).mockResolvedValue({ signups_enabled: true, guest_access_enabled: false })
    render(<AuthScreen />)
    fireEvent.click(await screen.findByRole('tab', { name: 'Create Account' }))
    await waitFor(() => expect(screen.getByLabelText('Display Name')).toBeVisible())
    expect(screen.getByLabelText('Password')).toBeVisible()
    expect(screen.queryByRole('tab', { name: 'Ask for a seat' })).not.toBeInTheDocument()
  })
})
