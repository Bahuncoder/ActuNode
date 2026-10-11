import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

/** Stub fetch with a handler for /api/session; every other request stays pending (only calls are counted). */
function stubFetch(session: () => Promise<unknown>) {
  const fetch = vi.fn((url: string) => (url === '/api/session' ? session() : new Promise(() => {})))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function stubWebSocket() {
  const opened = vi.fn()
  class FakeSocket {
    readyState = 0
    constructor(url: string) {
      opened(url)
    }
    close() {}
    addEventListener() {}
    removeEventListener() {}
  }
  vi.stubGlobal('WebSocket', FakeSocket)
  return opened
}

const answer = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => body })

describe('App', () => {
  it('opens nothing until the session check has answered (found by the browser tests, issue 6)', async () => {
    const fetch = stubFetch(() => new Promise(() => {}))
    const opened = stubWebSocket()

    render(<App />)

    expect(screen.getByText(/Connecting/)).toBeTruthy()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(opened).not.toHaveBeenCalled()
    expect(fetch.mock.calls.map(([url]) => url)).toEqual(['/api/session'])
  })

  it('shows only the login screen when a login is required, without touching the API', async () => {
    const fetch = stubFetch(() => answer({ loginRequired: true, loggedIn: false }))
    const opened = stubWebSocket()

    render(<App />)

    await screen.findByLabelText(/Access token/)
    expect(opened).not.toHaveBeenCalled()
    expect(fetch.mock.calls.every(([url]) => url === '/api/session')).toBe(true)
  })

  it('still opens the lab when the backend cannot be reached, so the lab can say so', async () => {
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')))
    const opened = stubWebSocket()

    render(<App />)

    await waitFor(() => expect(opened).toHaveBeenCalled())
  })
})
