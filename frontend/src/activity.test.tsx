import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ActivityPanel from './ActivityPanel'
import App from './App'
import { injectFailure } from './api'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }))

const entries = [
  { at: '2026-10-10T12:02:00Z', user: 'bob', role: 'viewer', client: 'x', action: 'mission.send', method: 'POST', path: '/api/missions', status: 403 },
  { at: '2026-10-10T12:01:00Z', user: 'alice', role: 'operator', client: 'x', action: 'mission.send', method: 'POST', path: '/api/missions', status: 200, robot: 'r1', destination: 'DOCK' },
  { at: '2026-10-10T12:00:00Z', user: null, role: null, client: 'x', action: 'login.failed', method: 'POST', path: '/api/login', status: 401 },
]

describe('ActivityPanel', () => {
  it('lists entries newest first with targets and highlights a 403', async () => {
    vi.stubGlobal('fetch', vi.fn(() => json({ entries })))
    render(<ActivityPanel />)
    await screen.findByText('r1 · DOCK')
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(3)
    expect(within(rows[0]).getByText('bob')).toBeTruthy()
    expect(within(rows[1]).getByText('r1 · DOCK')).toBeTruthy()
    expect(within(rows[2]).getByText('—', { selector: 'td:nth-child(2)' })).toBeTruthy()
    expect(within(rows[0]).getByText('403').className).toContain('error-text')
    expect(within(rows[1]).getByText('200').className).not.toContain('error-text')
  })

  it('filters by user', async () => {
    vi.stubGlobal('fetch', vi.fn(() => json({ entries })))
    render(<ActivityPanel />)
    await screen.findByText('alice', { selector: 'td' })
    fireEvent.change(screen.getByLabelText('User'), { target: { value: 'alice' } })
    expect(screen.getAllByRole('row')).toHaveLength(2)
    expect(screen.queryByText('bob', { selector: 'td' })).toBeNull()
  })

  it('shows the empty state and keeps polling after an error', async () => {
    vi.useFakeTimers()
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(() => (++calls === 1 ? json({}, 500) : json({ entries: [] }))))
    render(<ActivityPanel />)
    await act(() => vi.advanceTimersByTimeAsync(10))
    expect(screen.getByText(/Could not load activity/)).toBeTruthy()
    await act(() => vi.advanceTimersByTimeAsync(5100))
    expect(screen.getByText('No changes recorded yet')).toBeTruthy()
    expect(screen.queryByText(/Could not load activity/)).toBeNull()
  })
})

describe('viewer session', () => {
  it('is read-only but can still validate', async () => {
    vi.stubGlobal('WebSocket', function (this: object) {
      Object.assign(this, { close() {}, addEventListener() {}, removeEventListener() {} })
    })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/api/session') return json({ loginRequired: true, loggedIn: true, user: 'bob', role: 'viewer' })
        if (url === '/api/health') return json({ version: '1', mqtt: { connected: true } })
        if (url === '/api/sessions')
          return json([{ sessionId: 's1', name: null, startedAt: '2026-10-10T12:00:00Z', endedAt: '2026-10-10T12:01:00Z', messageCount: 5, recording: false, sizeBytes: 500 }])
        if (url === '/api/audit') return json({ entries: [] })
        return new Promise(() => {})
      }),
    )
    render(<App />)
    expect(await screen.findByText('View only')).toBeTruthy()
    expect(screen.getByLabelText('Logged in as bob, viewer')).toBeTruthy()
    const send = screen.getByRole('button', { name: 'Send mission' }) as HTMLButtonElement
    expect(send.disabled).toBe(true)
    expect(send.title).toBe('Viewers cannot change the lab')
    expect((screen.getByRole('button', { name: 'Inject' }) as HTMLButtonElement).disabled).toBe(true)
    const validate = (await screen.findByRole('button', { name: /Validate session/ })) as HTMLButtonElement
    expect(validate.disabled).toBe(false)
  })
})

describe('plain-text errors', () => {
  it('shows the body of a plain-text 403', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('Viewers cannot change the lab', { status: 403 }))))
    await expect(injectFailure('r1', 'BLOCKED', 'inject')).rejects.toThrow('Viewers cannot change the lab')
  })
})
