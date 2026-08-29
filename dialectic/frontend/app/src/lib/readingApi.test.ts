import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api.ts'

function stubFetch(response: Partial<Response>) {
  const fetchMock = vi.fn().mockResolvedValue(response as Response)
  vi.stubGlobal('fetch', fetchMock)
  window.fetch = fetchMock as unknown as typeof window.fetch
  return fetchMock
}

function jsonResponse(body: unknown): Partial<Response> {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(body),
  }
}

afterEach(() => {
  api.setAccessToken('')
  api.setRoomToken('')
  vi.unstubAllGlobals()
})

describe('DialecticAPI reading Library', () => {
  it('encodes server-side search, exact filters, limit, and cursor', async () => {
    const fetchMock = stubFetch(jsonResponse({ items: [], next_before: null }))

    await api.getReadingLibrary('room-1', {
      q: '  rate & oil  ',
      site: ' Reuters / Markets ',
      source: ' browser_capture ',
      limit: 25,
      before: 'cursor+/=',
    })

    expect(fetchMock.mock.calls[0][0]).toBe(
      '/rooms/room-1/reading/library?q=rate+%26+oil&site=Reuters+%2F+Markets' +
      '&source=browser_capture&limit=25&before=cursor%2B%2F%3D',
    )
    expect(fetchMock.mock.calls[0][1].method ?? 'GET').toBe('GET')
  })

  it('omits empty filters instead of changing their meaning', async () => {
    const fetchMock = stubFetch(jsonResponse({ items: [], next_before: null }))
    await api.getReadingLibrary('room-1', { q: ' ', site: '', source: '  ' })
    expect(fetchMock.mock.calls[0][0]).toBe('/rooms/room-1/reading/library')
  })

  it('loads one room-fenced reading detail', async () => {
    const fetchMock = stubFetch(jsonResponse({ id: 'reading-1', markdown: '# Exact' }))
    await api.getReadingDetail('room-1', 'reading/1')
    expect(fetchMock.mock.calls[0][0]).toBe('/rooms/room-1/reading/reading%2F1')
  })

  it('downloads authenticated text/markdown bytes and keeps the server filename', async () => {
    const blob = new Blob(['# Exact\n'], { type: 'text/markdown' })
    const fetchMock = stubFetch({
      ok: true,
      status: 200,
      headers: new Headers({
        'content-type': 'text/markdown; charset=utf-8',
        'content-disposition': 'attachment; filename="Exact-Piece.md"',
      }),
      blob: vi.fn().mockResolvedValue(blob),
    })
    api.setAccessToken('jwt')
    api.setRoomToken('room-token')

    await expect(api.fetchReadingMarkdown('room-1', 'reading-1')).resolves.toEqual({
      blob,
      filename: 'Exact-Piece.md',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/rooms/room-1/reading/reading-1/markdown',
      { headers: { Authorization: 'Bearer jwt', 'X-Room-Token': 'room-token' } },
    )
  })

  it('fails loudly when the download route falls through to the app shell', async () => {
    stubFetch({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/html' }),
      blob: vi.fn(),
    })

    await expect(api.fetchReadingMarkdown('room-1', 'reading-1')).rejects.toMatchObject({
      name: 'ApiError',
      status: 502,
    } satisfies Partial<ApiError>)
  })
})
