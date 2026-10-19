import { memo, useEffect, useRef, useState, type FocusEvent, type KeyboardEvent } from 'react'
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
  VIEWER_NOTE,
} from './api'
import { display, num, text, type RecordingStatus, type RecordingStopped, type ReplayStatus } from './live'

const POLL_MS = 1000
const SPEEDS = [1, 2, 5, 10]
// The server's upload limit (ACTUNODE_MAX_UPLOAD_MB default); a larger file is refused here, without sending it.
const MAX_UPLOAD_BYTES = 200 * 1024 ** 2

// Unknown is shown as unknown, not as 0 B (design brief).
function sizeText(bytes: number | undefined | null): string {
  return bytes === undefined || bytes === null ? '—' : formatSize(bytes)
}

// The enabled session actions, per session row.
function actionRows(body: HTMLElement | null): HTMLElement[][] {
  if (!body) return []
  return Array.from(body.querySelectorAll<HTMLTableRowElement>('tr[data-session]'))
    .map((tr) => Array.from(tr.querySelectorAll<HTMLElement>('[data-action]')).filter((el) => !(el as HTMLButtonElement).disabled))
    .filter((row) => row.length > 0)
}

function actionKey(el: HTMLElement): string {
  return `${el.closest<HTMLElement>('tr[data-session]')?.dataset.session ?? ''}|${el.dataset.action ?? ''}`
}

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
          <li key={rule.rule} title={display(rule.description)}>
            <span>{display(rule.rule)}</span> <span className={`badge ${rule.severity === 'error' ? 'down' : 'warn'}`}>{rule.severity}</span> ×{rule.count}
          </li>
        ))}
      </ul>
      <ul>
        {report.issues.slice(0, 10).map((issue, index) => (
          <li key={index}>
            line {display(issue.line)} · {display(issue.topic)} · {display(issue.message)}
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

function RecorderPanel({
  recording,
  recordingStopped,
  replay,
  sessionsVersion = 0,
  readOnly = false,
}: {
  recording: RecordingStatus | null
  recordingStopped: RecordingStopped | null
  replay: ReplayStatus | null
  // Bumped by the live feed whenever the server changed the session list (stop, delete, upload, retention).
  sessionsVersion?: number
  readOnly?: boolean
}) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [starting, setStarting] = useState<string | null>(null) // replay being started
  const [deleting, setDeleting] = useState<string | null>(null)
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
  const [listError, setListError] = useState<string | null>(null)
  const listSequence = useRef(0) // an older answer must not overwrite a newer one
  const [validating, setValidating] = useState<Set<string>>(new Set())
  const [uploading, setUploading] = useState(false)
  useEffect(() => {
    const sequence = ++listSequence.current
    fetchSessions()
      .then((list) => {
        if (sequence !== listSequence.current) return
        setListError(null)
        const valid = list.filter((session) => typeof session?.sessionId === 'string')
        setSessions(valid)
        const ids = new Set(valid.map((session) => session.sessionId))
        setReports((current) => {
          const kept = Object.entries(current).filter(([id]) => ids.has(id))
          return kept.length === Object.keys(current).length ? current : Object.fromEntries(kept)
        })
      })
      .catch((err) => {
        if (sequence === listSequence.current) setListError((err as Error).message)
      })
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

  // One request at a time: the button shows it and cannot be pressed twice (design brief).
  async function replaySession(sessionId: string) {
    if (starting !== null) return
    setStarting(sessionId)
    try {
      await replaySessionNow(sessionId)
    } finally {
      setStarting(null)
    }
  }

  async function replaySessionNow(sessionId: string) {
    setError(null)
    try {
      await startReplay(sessionId, speed, includeCommands, currentTime)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function removeSession(sessionId: string) {
    if (deleting !== null || !window.confirm(`Delete session ${sessionId}? This cannot be undone.`)) return
    setDeleting(sessionId)
    try {
      await removeSessionNow(sessionId)
    } finally {
      setDeleting(null)
    }
  }

  async function removeSessionNow(sessionId: string) {
    setError(null)
    try {
      await deleteSession(sessionId)
      setListVersion((version) => version + 1)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function validate(sessionId: string) {
    if (validating.has(sessionId)) return
    setValidating((current) => new Set(current).add(sessionId))
    try {
      const report = await validateSession(sessionId)
      setReports((current) => ({ ...current, [sessionId]: report }))
    } catch (err) {
      setReports((current) => ({ ...current, [sessionId]: (err as Error).message }))
    } finally {
      setValidating((current) => {
        const next = new Set(current)
        next.delete(sessionId)
        return next
      })
    }
  }

  async function upload(file: File | undefined) {
    if (!file || uploading) return
    setUploadMessage(null)
    if (file.size > MAX_UPLOAD_BYTES) {
      setUploadMessage({ text: `${file.name} is ${formatSize(file.size)}; the limit is ${formatSize(MAX_UPLOAD_BYTES)}`, error: true })
      return
    }
    setUploading(true)
    try {
      const created = await uploadSession(file, uploadName)
      setUploadMessage({ text: `Uploaded ${created.name ?? created.sessionId}`, error: false })
      setUploadName('')
      setListVersion((version) => version + 1)
    } catch (err) {
      setUploadMessage({ text: (err as Error).message, error: true })
    } finally {
      setUploading(false)
    }
  }

  // Announce transitions only (never the running counters). A session already recording on load is not announced.
  const [announcement, setAnnouncement] = useState('')
  const [seenId, setSeenId] = useState(recordingId)
  if (recordingId !== seenId) {
    setSeenId(recordingId)
    if (recordingId) setAnnouncement(`Recording started: ${recordingId}`)
    else if (seenId) {
      const reason = recordingStopped?.sessionId === seenId ? stopExplanation(recordingStopped.reason) : 'stopped by user'
      setAnnouncement(`Recording stopped: ${seenId} (${reason})`)
    }
  }

  const replaying = replay?.state === 'running'
  const elapsed = recording ? Math.max(0, (now - Date.parse(recording.startedAt)) / 1000) : 0

  // The session actions are one Tab stop (D-60): arrows move between them, left/right in a session, up/down between
  // sessions; disabled ones are skipped. Kept on the DOM, so the buttons need no extra props.
  const actionsRef = useRef<HTMLTableSectionElement>(null)
  const lastAction = useRef<string | null>(null)
  useEffect(() => {
    const all = actionRows(actionsRef.current).flat()
    const current = all.find((el) => actionKey(el) === lastAction.current) ?? all[0]
    for (const el of all) el.tabIndex = el === current ? 0 : -1
  })
  function rememberAction(event: FocusEvent<HTMLTableSectionElement>) {
    const el = event.target as HTMLElement
    if (!el.dataset.action) return
    lastAction.current = actionKey(el)
    for (const other of actionRows(actionsRef.current).flat()) other.tabIndex = other === el ? 0 : -1
  }
  function moveAction(event: KeyboardEvent<HTMLTableSectionElement>) {
    const rows = actionRows(actionsRef.current)
    const row = rows.findIndex((r) => r.includes(event.target as HTMLElement))
    if (row < 0) return
    const col = rows[row].indexOf(event.target as HTMLElement)
    const at = (r: number, c: number) => rows[r][Math.min(c, rows[r].length - 1)]
    const next = {
      ArrowRight: at(row, col + 1),
      ArrowLeft: at(row, Math.max(col - 1, 0)),
      ArrowDown: at(Math.min(row + 1, rows.length - 1), col),
      ArrowUp: at(Math.max(row - 1, 0), col),
      Home: rows[row][0],
      End: rows[row][rows[row].length - 1],
    }[event.key]
    if (!next) return
    event.preventDefault()
    next.focus()
  }

  return (
    <section id="sessions" tabIndex={-1} className="panel panel-wide">
      <h2>Sessions</h2>
      <p role="status" className="sr-only">
        {announcement}
      </p>
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
        <button type="button" className={recording ? 'danger-button' : ''} disabled={readOnly || busy} title={readOnly ? VIEWER_NOTE : undefined} onClick={toggle}>
          {busy ? (recording ? 'Stopping…' : 'Starting…') : recording ? '■ Stop recording' : '● Start recording'}
        </button>
        {recording && (
          <span className="recording-indicator mono">
            <span className="rec-dot" /> {recording.sessionId} · {formatDuration(elapsed)} ·{' '}
            {live?.messageCount ?? recording.messageCount} messages · {sizeText(live?.sizeBytes)}
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
          <span className="muted help"> — robots that are listening would carry them out</span>
        <label title="Each message gets the time it is sent again, for a fleet manager that ignores old state">
          <input type="checkbox" checked={currentTime} onChange={(e) => setCurrentTime(e.target.checked)} />
          Current time
          </label>
          <span className="muted help"> — each message gets the time it is sent again, for systems that ignore old state</span>
      </div>

      {recordingStopped && !recording && (
        <p role="alert" className="result mono error">
          Recording {recordingStopped.sessionId} stopped automatically: {stopExplanation(recordingStopped.reason)}.
        </p>
      )}
      {error && <p role="alert" className="result mono error">{error}</p>}

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
            disabled={readOnly || uploading}
            title={readOnly ? VIEWER_NOTE : undefined}
            onChange={(e) => {
                const input = e.target
                void upload(input.files?.[0]).then(() => {
                  input.value = ''
                })
              }}
            />
          </label>
          <p className="muted help">
            A session file (.jsonl), as downloaded here or made by <code>actunode import</code>; up to {MAX_UPLOAD_BYTES} MB.
          </p>
      </div>
      {uploading && <p className="muted">Uploading…</p>}
      <div role="status">{uploadMessage && !uploadMessage.error && <p className="result mono">{uploadMessage.text}</p>}</div>
      {uploadMessage?.error && <p role="alert" className="result mono error">{uploadMessage.text}</p>}
      {storage && (
        <p className="muted">
          Storage: {storage.usedMb.toFixed(1)} MB
          {storage.maxTotalMb > 0 ? ` of ${storage.maxTotalMb} MB` : ' · no size limit'} ·{' '}
          {storage.keepDays > 0 ? `keeps ${storage.keepDays} days` : 'kept forever'}
        </p>
      )}

      {listError && <p role="alert" className="result mono error">Could not load the session list: {listError}</p>}
      <div className="table-scroll">
        <table className="robot-table sessions-table">
          <thead>
            <tr>
              <th>Session</th>
              <th>Started</th>
              <th>Duration (m:ss)</th>
              <th>Messages</th>
              <th>Size</th>
              <th />
            </tr>
          </thead>
          <tbody ref={actionsRef} onFocus={rememberAction} onKeyDown={moveAction}>
            {sessions.length === 0 && !listError && (
              <tr>
                <td colSpan={6} className="muted">
                  No sessions recorded yet.
                </td>
              </tr>
            )}
            {sessions.flatMap((session) => [
              <tr key={session.sessionId} data-session={session.sessionId}>
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
                <td className="mono">{sizeText(num(session.sizeBytes))}</td>
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
                        disabled={readOnly || replaying || starting !== null}
                        title={readOnly ? VIEWER_NOTE : undefined}
                        data-action="replay"
                        onClick={() => replaySession(session.sessionId)}
                      >
                        {starting === session.sessionId ? 'Starting…' : '▶ Replay'}
                      </button>
                      <button
                        type="button"
                        className="link-button"
                        aria-label={`Validate session ${text(session.name) === '—' ? session.sessionId : text(session.name)}`}
                        disabled={validating.has(session.sessionId)}
                        data-action="validate"
                        onClick={() => validate(session.sessionId)}
                      >
                        {validating.has(session.sessionId) ? 'Validating…' : 'Validate'}
                      </button>
                      <a className="link" data-action="download" href={`/api/sessions/${encodeURIComponent(session.sessionId)}/download`} download>
                        Download
                      </a>
                      <button
                        type="button"
                        className="link-button danger-link"
                        disabled={readOnly || deleting !== null || (replaying && replay?.sessionId === session.sessionId)}
                        title={readOnly ? VIEWER_NOTE : undefined}
                        data-action="delete"
                        onClick={() => removeSession(session.sessionId)}
                      >
                        {deleting === session.sessionId ? 'Deleting…' : 'Delete'}
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

export default memo(RecorderPanel)
