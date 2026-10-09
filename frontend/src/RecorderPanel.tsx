import { useEffect, useState } from 'react'
import {
  fetchRecordingCount,
  fetchSessions,
  startRecording,
  startReplay,
  stopRecording,
  type SessionSummary,
} from './api'
import type { RecordingStatus, ReplayStatus } from './live'

const POLL_MS = 1000
const SPEEDS = [1, 2, 5, 10]

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

function sessionDuration(session: SessionSummary): string {
  if (!session.startedAt || !session.endedAt) return '—'
  return formatDuration((Date.parse(session.endedAt) - Date.parse(session.startedAt)) / 1000)
}

export default function RecorderPanel({
  recording,
  replay,
}: {
  recording: RecordingStatus | null
  replay: ReplayStatus | null
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [count, setCount] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [speed, setSpeed] = useState(1)
  const [includeCommands, setIncludeCommands] = useState(false)

  // Refresh the list whenever recording starts or stops (from this tab or another).
  const recordingId = recording?.sessionId ?? null
  useEffect(() => {
    fetchSessions().then(setSessions).catch(() => {})
  }, [recordingId])

  // Live counter while recording.
  useEffect(() => {
    if (!recordingId) return
    const timer = setInterval(() => {
      setNow(Date.now())
      fetchRecordingCount().then(setCount).catch(() => {})
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [recordingId])

  async function toggle() {
    setBusy(true)
    setError(null)
    try {
      if (recording) {
        await stopRecording()
      } else {
        await startRecording(name)
        setCount(0)
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function replaySession(sessionId: string) {
    setError(null)
    try {
      await startReplay(sessionId, speed, includeCommands)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const replaying = replay?.state === 'running'
  const elapsed = recording ? Math.max(0, (now - Date.parse(recording.startedAt)) / 1000) : 0

  return (
    <section className="panel panel-wide">
      <h2>Sessions</h2>
      <p>
        Record every MQTT message (orders, states, connections, failures) to a JSONL file, then replay it to
        reproduce the incident.
      </p>

      <div className="mission-form">
        <label>
          Session name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="p1042-blocked-aisle"
            disabled={Boolean(recording)}
            maxLength={40}
          />
        </label>
        <button type="button" className={recording ? 'danger-button' : ''} disabled={busy} onClick={toggle}>
          {recording ? '■ Stop recording' : '● Start recording'}
        </button>
        {recording && (
          <span className="recording-indicator mono">
            <span className="rec-dot" /> {recording.sessionId} · {formatDuration(elapsed)} ·{' '}
            {count ?? recording.messageCount} messages
          </span>
        )}
      </div>

      <div className="replay-options">
        <span className="muted">Replay options:</span>
        <label>
          Speed
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {SPEEDS.map((value) => (
              <option key={value} value={value}>
                {value}×
              </option>
            ))}
          </select>
        </label>
        <label title="Orders and failure injections would be executed by any robot listening">
          <input type="checkbox" checked={includeCommands} onChange={(e) => setIncludeCommands(e.target.checked)} />
          Include commands (orders, failure injections)
        </label>
      </div>

      {error && <p className="result mono error">{error}</p>}

      <div className="table-scroll">
        <table className="robot-table sessions-table">
          <thead>
            <tr>
              <th>Session</th>
              <th>Started</th>
              <th>Duration</th>
              <th>Messages</th>
              <th>Size</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {sessions.length === 0 && (
              <tr>
                <td colSpan={6} className="muted">
                  No sessions recorded yet.
                </td>
              </tr>
            )}
            {sessions.map((session) => (
              <tr key={session.sessionId}>
                <td className="mono">
                  {session.sessionId}
                  {session.recording && <span className="badge down session-badge">REC</span>}
                  {!session.recording && session.complete === false && (
                    <span className="badge session-badge" title="No end record: the backend stopped while recording">
                      INCOMPLETE
                    </span>
                  )}
                </td>
                <td className="mono">{session.startedAt ? new Date(session.startedAt).toLocaleString() : '—'}</td>
                <td className="mono">{session.recording ? 'recording…' : sessionDuration(session)}</td>
                <td className="mono">{session.recording ? (count ?? session.messageCount) : session.messageCount}</td>
                <td className="mono">{formatSize(session.sizeBytes)}</td>
                <td>
                  {!session.recording && (
                    <span className="session-actions">
                      <button
                        type="button"
                        className="link-button"
                        disabled={replaying}
                        onClick={() => replaySession(session.sessionId)}
                      >
                        ▶ Replay
                      </button>
                      <a className="link" href={`/api/sessions/${session.sessionId}/download`} download>
                        Download
                      </a>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
