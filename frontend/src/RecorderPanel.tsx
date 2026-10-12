import { useEffect, useRef, useState } from 'react'
import {
  deleteSession,
  fetchRecording,
  fetchSessions,
  startRecording,
  startReplay,
  stopRecording,
  type SessionSummary,
} from './api'
import type { RecordingStatus, RecordingStopped, ReplayStatus } from './live'

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

function stopExplanation(reason: string): string {
  if (reason === 'sizeLimit') return 'it reached the size limit (ACTUNODE_MAX_SESSION_MB)'
  if (reason.startsWith('writeError')) return `the file could not be written (${reason.slice('writeError: '.length)})`
  return reason
}

function sessionDuration(session: SessionSummary): string {
  if (!session.startedAt || !session.endedAt) return '—'
  return formatDuration((Date.parse(session.endedAt) - Date.parse(session.startedAt)) / 1000)
}

export default function RecorderPanel({
  recording,
  recordingStopped,
  replay,
}: {
  recording: RecordingStatus | null
  recordingStopped: RecordingStopped | null
  replay: ReplayStatus | null
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [polled, setPolled] = useState<RecordingStatus | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [speed, setSpeed] = useState(1)
  const [includeCommands, setIncludeCommands] = useState(false)

  // Refresh the list whenever recording starts or stops (from this tab or another).
  const recordingId = recording?.sessionId ?? null
  const [listVersion, setListVersion] = useState(0)
  useEffect(() => {
    fetchSessions().then(setSessions).catch(() => {})
  }, [recordingId, listVersion])

  // Live counter while recording. Counts belong to one session: a different sessionId (started from any
  // tab or the API) shows no counts until its own poll answers, and an answer for another session is dropped.
  const live = polled && polled.sessionId === recordingId ? polled : null
  const latest = useRef(0)
  useEffect(() => {
    if (!recordingId) return
    const timer = setInterval(() => {
      setNow(Date.now())
      const sequence = ++latest.current
      fetchRecording()
        .then((next) => {
          if (sequence === latest.current && next?.sessionId === recordingId) setPolled(next)
        })
        .catch(() => {})
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

  async function removeSession(sessionId: string) {
    if (!window.confirm(`Delete session ${sessionId}? This cannot be undone.`)) return
    setError(null)
    try {
      await deleteSession(sessionId)
      setListVersion((version) => version + 1)
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
            {live?.messageCount ?? recording.messageCount} messages · {formatSize(live?.sizeBytes ?? 0)}
            {recording.maxBytes ? ` of ${formatSize(recording.maxBytes)}` : ''}
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

      {recordingStopped && !recording && (
        <p className="result mono error">
          Recording {recordingStopped.sessionId} stopped automatically: {stopExplanation(recordingStopped.reason)}.
        </p>
      )}
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
                  {session.reason === 'sizeLimit' && (
                    <span className="badge down session-badge" title="Stopped at the size limit">
                      SIZE LIMIT
                    </span>
                  )}
                  {session.reason?.startsWith('writeError') && (
                    <span className="badge down session-badge" title={session.reason}>
                      WRITE ERROR
                    </span>
                  )}
                  {!session.recording && session.complete === false && (
                    <span className="badge session-badge" title="No end record: the backend stopped while recording">
                      INCOMPLETE
                    </span>
                  )}
                </td>
                <td className="mono">{session.startedAt ? new Date(session.startedAt).toLocaleString() : '—'}</td>
                <td className="mono">{session.recording ? 'recording…' : sessionDuration(session)}</td>
                <td className="mono">
                  {session.recording ? (live?.messageCount ?? session.messageCount) : session.messageCount}
                </td>
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
                      <button
                        type="button"
                        className="link-button danger-link"
                        disabled={replaying && replay?.sessionId === session.sessionId}
                        onClick={() => removeSession(session.sessionId)}
                      >
                        Delete
                      </button>
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
