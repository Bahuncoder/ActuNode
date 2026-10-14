import { useEffect, useRef, useState } from 'react'
import {
  deleteSession,
  fetchRecording,
  fetchSessionStorage,
  fetchSessions,
  startRecording,
  startReplay,
  stopRecording,
  uploadSession,
  validateSession,
  type SessionStorage,
  type ValidationReport,
  type SessionSummary,
} from './api'
import { num, text, type RecordingStatus, type RecordingStopped, type ReplayStatus } from './live'

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

// The session list is data from files anyone can upload: read every field through text()/num().
function sessionDuration(session: SessionSummary): string {
  const seconds = (Date.parse(text(session.endedAt)) - Date.parse(text(session.startedAt))) / 1000
  return Number.isFinite(seconds) ? formatDuration(seconds) : '—'
}

function sessionStart(session: SessionSummary): string {
  const start = Date.parse(text(session.startedAt))
  return Number.isFinite(start) ? new Date(start).toLocaleString() : '—'
}

function ValidationResult({ report }: { report: ValidationReport | string }) {
  if (typeof report === 'string') return <p className="result mono error">{report}</p>
  return (
    <div className="result mono">
      <p>
        {report.checked} messages checked, {report.withIssues} with issues
      </p>
      <ul>
        {report.byRule.map((rule) => (
          <li key={rule.rule} title={rule.description}>
            <span>{rule.rule}</span> <span className={`badge ${rule.severity === 'error' ? 'down' : 'warn'}`}>{rule.severity}</span> ×{rule.count}
          </li>
        ))}
      </ul>
      <ul>
        {report.issues.slice(0, 10).map((issue, index) => (
          <li key={index}>
            line {issue.line} · {issue.topic} · {issue.message}
          </li>
        ))}
      </ul>
      {(report.issues.length > 10 || report.truncated) && (
        <p className="muted">
          {[
            report.issues.length > 10 && `showing first 10 of ${report.issues.length} listed issues`,
            report.truncated && 'the report lists the first 100 issues',
          ]
            .filter(Boolean)
            .join(' · ')}
        </p>
      )}
    </div>
  )
}

export default function RecorderPanel({
  recording,
  recordingStopped,
  replay,
  sessionsVersion = 0,
}: {
  recording: RecordingStatus | null
  recordingStopped: RecordingStopped | null
  replay: ReplayStatus | null
  // Bumped by the live feed whenever the server changed the session list (stop, delete, upload, retention).
  sessionsVersion?: number
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [polled, setPolled] = useState<RecordingStatus | null>(null)
  const [now, setNow] = useState(() => Date.now())
  const [speed, setSpeed] = useState(1)
  const [includeCommands, setIncludeCommands] = useState(false)
  const [currentTime, setCurrentTime] = useState(false)
  const [storage, setStorage] = useState<SessionStorage | null>(null)
  const [reports, setReports] = useState<Record<string, ValidationReport | string>>({})
  const [uploadName, setUploadName] = useState('')
  const [uploadMessage, setUploadMessage] = useState<{ text: string; error: boolean } | null>(null)

  // Refresh the list whenever recording starts or stops (from this tab or another).
  const recordingId = recording?.sessionId ?? null
  const [listVersion, setListVersion] = useState(0)
  useEffect(() => {
    fetchSessions()
      .then((list) => {
        const valid = list.filter((session) => typeof session?.sessionId === 'string')
        setSessions(valid)
        const ids = new Set(valid.map((session) => session.sessionId))
        setReports((current) => {
          const kept = Object.entries(current).filter(([id]) => ids.has(id))
          return kept.length === Object.keys(current).length ? current : Object.fromEntries(kept)
        })
      })
      .catch(() => {})
    fetchSessionStorage().then(setStorage).catch(() => {})
  }, [recordingId, listVersion, sessionsVersion])

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
      await startReplay(sessionId, speed, includeCommands, currentTime)
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

  async function validate(sessionId: string) {
    try {
      const report = await validateSession(sessionId)
      setReports((current) => ({ ...current, [sessionId]: report }))
    } catch (err) {
      setReports((current) => ({ ...current, [sessionId]: (err as Error).message }))
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return
    setUploadMessage(null)
    try {
      const created = await uploadSession(file, uploadName)
      setUploadMessage({ text: `Uploaded ${created.name ?? created.sessionId}`, error: false })
      setUploadName('')
      setListVersion((version) => version + 1)
    } catch (err) {
      setUploadMessage({ text: (err as Error).message, error: true })
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
        <label title="Each message gets the time it is sent again, for a fleet manager that ignores old state">
          <input type="checkbox" checked={currentTime} onChange={(e) => setCurrentTime(e.target.checked)} />
          Current time
        </label>
      </div>

      {recordingStopped && !recording && (
        <p className="result mono error">
          Recording {recordingStopped.sessionId} stopped automatically: {stopExplanation(recordingStopped.reason)}.
        </p>
      )}
      {error && <p className="result mono error">{error}</p>}

      <div className="mission-form">
        <label>
          Upload name
          <input
            value={uploadName}
            onChange={(e) => setUploadName(e.target.value)}
            placeholder="optional"
            maxLength={40}
          />
        </label>
        <label>
          Upload session file
          <input
            type="file"
            accept=".jsonl,application/x-ndjson"
            onChange={(e) => {
              const input = e.target
              void upload(input.files?.[0]).then(() => {
                input.value = ''
              })
            }}
          />
        </label>
      </div>
      {uploadMessage && <p className={`result mono${uploadMessage.error ? ' error' : ''}`}>{uploadMessage.text}</p>}
      {storage && (
        <p className="muted">
          Storage: {storage.usedMb.toFixed(1)} MB
          {storage.maxTotalMb > 0 ? ` of ${storage.maxTotalMb} MB` : ' · no size limit'} ·{' '}
          {storage.keepDays > 0 ? `keeps ${storage.keepDays} days` : 'kept forever'}
        </p>
      )}

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
            {sessions.flatMap((session) => [
              <tr key={session.sessionId}>
                <td className="mono">
                  {session.sessionId}
                  {session.recording === true && <span className="badge down session-badge">REC</span>}
                  {session.reason === 'sizeLimit' && (
                    <span className="badge down session-badge" title="Stopped at the size limit">
                      SIZE LIMIT
                    </span>
                  )}
                  {typeof session.reason === 'string' && session.reason.startsWith('writeError') && (
                    <span className="badge down session-badge" title={session.reason}>
                      WRITE ERROR
                    </span>
                  )}
                  {session.recording !== true && session.complete === false && (
                    <span className="badge session-badge" title="No end record: the backend stopped while recording">
                      INCOMPLETE
                    </span>
                  )}
                </td>
                <td className="mono">{sessionStart(session)}</td>
                <td className="mono">{session.recording === true ? 'recording…' : sessionDuration(session)}</td>
                <td className="mono">
                  {session.recording === true ? (live?.messageCount ?? num(session.messageCount) ?? '—') : (num(session.messageCount) ?? '—')}
                </td>
                <td className="mono">{formatSize(num(session.sizeBytes) ?? 0)}</td>
                <td>
                  {session.recording === true && (
                    <button
                      type="button"
                      className="link-button"
                      aria-label={`Validate session ${text(session.name) === '—' ? session.sessionId : text(session.name)}`}
                      disabled
                    >
                      Validate
                    </button>
                  )}
                  {session.recording !== true && (
                    <span className="session-actions">
                      <button
                        type="button"
                        className="link-button"
                        disabled={replaying}
                        onClick={() => replaySession(session.sessionId)}
                      >
                        ▶ Replay
                      </button>
                      <button
                        type="button"
                        className="link-button"
                        aria-label={`Validate session ${text(session.name) === '—' ? session.sessionId : text(session.name)}`}
                        onClick={() => validate(session.sessionId)}
                      >
                        Validate
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
              </tr>,
              reports[session.sessionId] !== undefined && (
                <tr key={`${session.sessionId}-validation`}>
                  <td colSpan={6}>
                    <ValidationResult report={reports[session.sessionId]} />
                  </td>
                </tr>
              ),
            ])}
          </tbody>
        </table>
      </div>
    </section>
  )
}
