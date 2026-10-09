import { useState } from 'react'
import { injectFailure } from './api'
import { missionStatus, type FailureEntry, type Robot } from './live'

type Result = { ok: boolean; text: string }

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour12: false })
}

export default function FailurePanel({ robots, failures }: { robots: Robot[]; failures: FailureEntry[] }) {
  const [chosen, setChosen] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Result | null>(null)

  // Default to a robot that is actually on a route, since that is what can be blocked.
  const onRoute = robots.find((robot) => ['ACCEPTED', 'MOVING'].includes(missionStatus(robot)))
  const robotId = chosen || onRoute?.robotId || robots[0]?.robotId || ''
  const robot = robots.find((candidate) => candidate.robotId === robotId)
  const status = robot ? missionStatus(robot) : '—'

  async function run(action: 'inject' | 'clear') {
    setBusy(true)
    try {
      await injectFailure(robotId, action)
      setResult({ ok: true, text: action === 'inject' ? `BLOCKED_PATH injected on ${robotId}` : `Path cleared on ${robotId}` })
    } catch (error) {
      setResult({ ok: false, text: (error as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Failure injection</h2>
      <p>Block the path of a robot on a route. It stops, reports <code>pathBlocked</code>, and waits until cleared.</p>

      <div className="mission-form">
        <label>
          Robot
          <select value={robotId} onChange={(e) => setChosen(e.target.value)} disabled={robots.length === 0}>
            {robots.map((candidate) => (
              <option key={candidate.robotId} value={candidate.robotId}>
                {candidate.robotId} · {missionStatus(candidate)}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="danger-button"
          disabled={busy || !robotId || !['ACCEPTED', 'MOVING'].includes(status)}
          onClick={() => run('inject')}
        >
          Inject BLOCKED_PATH
        </button>
        <button
          type="button"
          className="secondary-button"
          disabled={busy || status !== 'BLOCKED'}
          onClick={() => run('clear')}
        >
          Clear
        </button>
      </div>

      {result && <p className={`result mono ${result.ok ? 'ok' : 'error'}`}>{result.text}</p>}

      <ol className="failure-log mono">
        {failures.length === 0 && <li className="muted">No failures injected yet.</li>}
        {[...failures].reverse().map((entry) => (
          <li key={entry.injectionId}>
            <span className="muted">{time(entry.timestamp)}</span>
            <span>{entry.robotId}</span>
            <span className={entry.action}>
              {entry.failure} {entry.action === 'inject' ? 'injected' : 'cleared'}
            </span>
            <span className="muted">was {entry.robotStatus}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
