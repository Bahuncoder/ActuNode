import { memo, useEffect, useState } from 'react'
import { fetchAudit, type AuditEntry } from './api'

const POLL_MS = 5000
const LIMIT = 50
const EVERYONE = ''

function time(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString([], { hour12: false })
}

function target(entry: AuditEntry): string {
  return [entry.robot, entry.sessionId, entry.destination, entry.failure].filter(Boolean).join(' · ') || '—'
}

function ActivityPanel() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [user, setUser] = useState(EVERYONE)

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const result = await fetchAudit({ limit: LIMIT })
        if (cancelled) return
        setEntries(result)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'request failed')
      }
    }
    void poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const users = [...new Set(entries.map((entry) => entry.user).filter((name): name is string => Boolean(name)))].sort()
  const shown = user === EVERYONE ? entries : entries.filter((entry) => entry.user === user)

  return (
    <section className="panel panel-wide">
      <h2>Activity</h2>
      <label>
        User
        <select value={user} onChange={(e) => setUser(e.target.value)}>
          <option value={EVERYONE}>everyone</option>
          {users.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </label>
      {error && <p role="alert" className="result mono error">Could not load activity: {error}</p>}
      <div className="table-scroll">
        <table className="robot-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Action</th>
              <th>Target</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && !error && (
              <tr>
                <td colSpan={5} className="muted">
                  No changes recorded yet
                </td>
              </tr>
            )}
            {shown.map((entry, index) => (
              <tr key={`${entry.at}-${index}`}>
                <td className="mono">{time(entry.at)}</td>
                <td>{entry.user ?? '—'}</td>
                <td className="mono">{entry.action}</td>
                <td className="mono">{target(entry)}</td>
                <td className={`mono${entry.status >= 200 && entry.status < 300 ? '' : ' error-text'}`}>{entry.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default memo(ActivityPanel)
