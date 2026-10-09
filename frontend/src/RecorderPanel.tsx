import { useEffect, useState } from 'react'
import { fetchRecordingCount, fetchSessions, startRecording, stopRecording, type SessionSummary } from './api'
import type { RecordingStatus } from './live'

const POLL_MS = 1000

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

export default function RecorderPanel({ recording }: { recording: RecordingStatus | null }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [count, setCount] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())

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

  const elapsed = recording ? Math.max(0, (now - Date.parse(recording.startedAt)) / 1000) : 0

  return (
    <section className="panel panel-wide">
      <h2>Record</h2>
      <p>Capture every MQTT message (orders, states, connections, failures) to a JSONL session file.</p>

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
                    <a className="link" href={`/api/sessions/${session.sessionId}/download`} download>
                      Download .jsonl
                    </a>
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
