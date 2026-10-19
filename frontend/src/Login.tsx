import { useState, type FormEvent } from 'react'
import { login } from './api'

/** Shown instead of the lab when the backend requires a login (sharing the lab on a network, D-25). */
export default function Login({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(token.trim())
      setToken('')
      onLoggedIn()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      <section className="panel login-panel">
        <h2>ActuNode Lab: log in</h2>
        <p>
          This lab is shared on a network, so it needs the access token. On the machine running it:{' '}
          <code>docker compose run --rm mqtt-init show api-token</code>
        </p>
        <form className="mission-form" onSubmit={submit}>
          <label>
            Access token
            <input
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoFocus
            />
          </label>
          <button type="submit" disabled={busy || token.trim() === ''}>
            {busy ? 'Logging in…' : 'Log in'}
          </button>
        </form>
        {error && <p role="alert" className="result mono error">{error}</p>}
      </section>
    </div>
  )
}
