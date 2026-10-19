import { memo, useState } from 'react'
import { injectFailure, VIEWER_NOTE } from './api'
import { display, FAILURE_LABELS, injectedFailures, missionStatus, type FailureEntry, type Robot } from './live'

type Result = { ok: boolean; text: string }

// How each failure ends (design brief: say whether it ends by itself). LOW_BATTERY: charging does not end it.
const FAILURE_ENDS: Record<string, string> = {
  BLOCKED_PATH: 'Stays until you clear it.',
  LOW_BATTERY: 'Stays until you clear it (the battery level from before is restored); charging does not end it.',
  DISCONNECT: 'Ends by itself after the duration set here.',
  UNRESPONSIVE: 'Ends by itself after the duration set here.',
  INVALID_PAYLOAD: 'Sends the bad message(s) once; normal traffic goes on.',
}

const TYPES = [
  { value: 'BLOCKED_PATH', label: FAILURE_LABELS.BLOCKED_PATH, clearable: true },
  { value: 'LOW_BATTERY', label: FAILURE_LABELS.LOW_BATTERY, clearable: true },
  { value: 'DISCONNECT', label: FAILURE_LABELS.DISCONNECT, clearable: false },
  { value: 'INVALID_PAYLOAD', label: FAILURE_LABELS.INVALID_PAYLOAD, clearable: false },
  { value: 'UNRESPONSIVE', label: FAILURE_LABELS.UNRESPONSIVE, clearable: false },
]
const KINDS = ['not-json', 'schema', 'wrong-serial', 'wrong-version']

function paramsText(params?: Record<string, unknown>): string {
  return Object.entries(params ?? {}).map(([key, value]) => `${key}=${display(value)}`).join(' ')
}

function time(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour12: false })
}

function FailurePanel({ robots: allRobots, failures, readOnly = false }: { robots: Robot[]; failures: FailureEntry[]; readOnly?: boolean }) {
  // Only ActuNode's simulated robots can be failed (the backend refuses others with 409).
  const robots = allRobots.filter((robot) => robot.manufacturer === 'ActuNode')
  const [chosen, setChosen] = useState('')
  const [failure, setFailure] = useState('BLOCKED_PATH')
  const [level, setLevel] = useState('15')
  const [duration, setDuration] = useState('10')
  const [mode, setMode] = useState('broken')
  const [kind, setKind] = useState('schema')
  const [count, setCount] = useState('1')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<Result | null>(null)

  // Default to a robot that is actually on a route, since that is what can be blocked. Picked once (when
  // robots first appear), not on every frame, or the select would jump while statuses change.
  const [defaultId, setDefaultId] = useState('')
  if (!defaultId && robots.length > 0) {
    setDefaultId((robots.find((robot) => ['ACCEPTED', 'MOVING'].includes(missionStatus(robot))) ?? robots[0]).robotId)
  }
  // Failures address the simulator by serial: one entry per serial, showing its most recently seen robot.
  const bySerial = new Map<string, Robot>()
  for (const candidate of robots) {
    const seen = bySerial.get(candidate.robotId)
    if (!seen || (candidate.lastSeen ?? '') > (seen.lastSeen ?? '')) bySerial.set(candidate.robotId, candidate)
  }
  const serials = [...bySerial.values()]
  // What the select shows is what gets sent: fall back to the first listed robot if the chosen one is gone.
  const robotId = [chosen, defaultId].find((id) => id && bySerial.has(id)) ?? serials[0]?.robotId ?? ''
  const robot = bySerial.get(robotId)
  const status = robot ? missionStatus(robot) : '—'

  const type = TYPES.find((t) => t.value === failure) ?? TYPES[0]
  const needsRoute = failure === 'BLOCKED_PATH'
  // Absent on older simulators: then Clear stays enabled.
  const injected = injectedFailures(robot)
  const range: [string, number, number] | undefined = { LOW_BATTERY: [level, 1, 99] as [string, number, number],
    DISCONNECT: [duration, 1, 300] as [string, number, number],
    INVALID_PAYLOAD: [count, 1, 10] as [string, number, number],
    UNRESPONSIVE: [duration, 1, 300] as [string, number, number],
  }[
    failure as 'LOW_BATTERY' | 'DISCONNECT' | 'INVALID_PAYLOAD' | 'UNRESPONSIVE'
  ]
  // The backend takes whole numbers only.
  const invalid = range !== undefined && !(/^\d+$/.test(range[0].trim()) && Number(range[0]) >= range[1] && Number(range[0]) <= range[2])
  const clearBlocked = needsRoute
    ? status !== 'BLOCKED'
    : failure === 'LOW_BATTERY' && injected !== undefined && !injected.includes('LOW_BATTERY')

  function currentParams(): Record<string, unknown> {
    if (failure === 'LOW_BATTERY') return { level: Number(level) }
    if (failure === 'DISCONNECT') return { duration_s: Number(duration), mode }
    if (failure === 'UNRESPONSIVE') return { duration_s: Number(duration) }
    if (failure === 'INVALID_PAYLOAD') return { kind, count: Number(count) }
    return {}
  }

  async function run(action: 'inject' | 'clear') {
    setBusy(true)
    try {
      await injectFailure(robotId, failure, action, action === 'inject' ? currentParams() : {})
      setResult({ ok: true, text: `${type.label} ${action === 'inject' ? 'injected on' : 'cleared on'} ${robotId}` })
    } catch (error) {
      setResult({ ok: false, text: (error as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Failure injection</h2>
      <p>Inject a failure into a simulated robot. A blocked path needs a robot on a route; it stops and waits until cleared.</p>

      <div className="mission-form">
        <label>
          Robot
          <select value={robotId} onChange={(e) => setChosen(e.target.value)} disabled={robots.length === 0}>
            {serials.map((candidate) => (
              <option key={candidate.robotId} value={candidate.robotId}>
                {candidate.robotId} · ActuNode · {missionStatus(candidate)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Failure type
          <select value={failure} onChange={(e) => setFailure(e.target.value)}>
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </label>
        {failure === 'LOW_BATTERY' && (
          <label>
            Battery level
            <input type="number" min={1} max={99} value={level} onChange={(e) => setLevel(e.target.value)} />
          </label>
        )}
        {failure === 'DISCONNECT' && (
          <>
            <label>
              Duration (s)
              <input type="number" min={1} max={300} value={duration} onChange={(e) => setDuration(e.target.value)} />
            </label>
            <label>
              Mode
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="broken">broken</option>
                <option value="offline">offline</option>
              </select>
            </label>
          </>
        )}
        {failure === 'UNRESPONSIVE' && (
          <label>
            Duration (s)
            <input type="number" min={1} max={300} value={duration} onChange={(e) => setDuration(e.target.value)} />
          </label>
        )}
        {failure === 'INVALID_PAYLOAD' && (
          <>
            <label>
              Kind
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </label>
            <label>
              Count
              <input type="number" min={1} max={10} value={count} onChange={(e) => setCount(e.target.value)} />
            </label>
          </>
        )}
        <button
          type="button"
          className="danger-button"
          title={readOnly ? VIEWER_NOTE : undefined}
          disabled={readOnly || busy || !robotId || invalid || (needsRoute && !['ACCEPTED', 'MOVING'].includes(status))}
          onClick={() => run('inject')}
          >
            {busy ? 'Sending…' : 'Inject'}
          </button>
        {type.clearable && (
          <button
            type="button"
            className="secondary-button"
            title={readOnly ? VIEWER_NOTE : undefined}
            disabled={readOnly || busy || !robotId || clearBlocked}
            onClick={() => run('clear')}
          >
            Clear
          </button>
        )}
      </div>

      {failure === 'UNRESPONSIVE' && (
        <p className="muted">The robot stays connected but stops answering: no state, orders and commands ignored, while it keeps driving.</p>
      )}
      {FAILURE_ENDS[failure] && <p className="muted">{FAILURE_ENDS[failure]}</p>}
      {invalid && <p className="muted">Enter a number between {range[1]} and {range[2]}</p>}
      {injected && injected.length > 0 && (
        <p className="muted">Injected: {injected.map((name) => TYPES.find((t) => t.value === name)?.label ?? name).join(', ')}</p>
      )}

      <div role="status">{result?.ok && <p className="result mono ok">{result.text}</p>}</div>
      {result && !result.ok && <p role="alert" className="result mono error">{result.text}</p>}

      <ol className="failure-log mono">
        {failures.length === 0 && <li className="muted">No failures injected yet.</li>}
        {[...failures].reverse().map((entry) => (
          <li key={entry.injectionId}>
            <span className="muted">{time(entry.timestamp)}</span>
            <span>{entry.robotId}</span>
            <span className={entry.action}>
              {display(entry.failure)} {entry.action === 'inject' ? 'injected' : 'cleared'}
            </span>
            {entry.params && Object.keys(entry.params).length > 0 && <span className="muted">{paramsText(entry.params)}</span>}
            <span className="muted">was {entry.robotStatus}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

export default memo(FailurePanel)
