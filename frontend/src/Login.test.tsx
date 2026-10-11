import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Login from './Login'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body })
}

async function submit(token: string) {
  fireEvent.change(screen.getByLabelText(/Access token/), { target: { value: token } })
  fireEvent.click(screen.getByText('Log in'))
}

describe('Login', () => {
  it('logs in with the token and reports success', async () => {
    const fetchMock = respond(200, { loggedIn: true })
    vi.stubGlobal('fetch', fetchMock)
    const onLoggedIn = vi.fn()
    render(<Login onLoggedIn={onLoggedIn} />)

    await submit('secret-token')

    await waitFor(() => expect(onLoggedIn).toHaveBeenCalled())
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/login')
    expect(JSON.parse(init.body)).toEqual({ token: 'secret-token' })
  })

  it('shows why a login failed', async () => {
    vi.stubGlobal('fetch', respond(401, { detail: 'Wrong token' }))
    const onLoggedIn = vi.fn()
    render(<Login onLoggedIn={onLoggedIn} />)

    await submit('nope')

    expect(await screen.findByText('Wrong token')).toBeTruthy()
    expect(onLoggedIn).not.toHaveBeenCalled()
  })

  it('explains the rate limit', async () => {
    vi.stubGlobal('fetch', respond(429, { detail: 'Too many failed logins; wait a minute' }))
    render(<Login onLoggedIn={vi.fn()} />)

    await submit('nope')

    expect(await screen.findByText(/Too many failed logins/)).toBeTruthy()
  })

  it('tells people where the token comes from', () => {
    render(<Login onLoggedIn={vi.fn()} />)

    expect(screen.getByText(/show api-token/)).toBeTruthy()
  })
})
