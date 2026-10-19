import { useState } from 'react'
import { stopReplay, VIEWER_NOTE } from './api'
import type { ReplayStatus } from './live'

const STATE_TEXT = { running: 'REPLAYING', finished: 'REPLAY FINISHED', stopped: 'REPLAY STOPPED', failed: 'REPLAY FAILED' }

/** Shown while a session replays, so replayed traffic is never mistaken for live robots. */
export default function ReplayBanner({ replay, readOnly = false }: { replay: ReplayStatus | null; readOnly?: boolean }) {
  const [stopping, setStopping] = useState(false)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const key = `${replay?.sessionId}:${replay?.state}`
  const [seen, setSeen] = useState(key)
  // Announce start and end only, never the progress ticks.
  if (key !== seen) {
    setSeen(key)
    if (replay) setAnnouncement(`Replay ${replay.state === 'running' ? 'started' : replay.state}: ${replay.sessionId}`)
  }

  const live = (
    <p role="status" className="sr-only">
      {announcement}
    </p>
  )
  if (!replay) return live

  const running = replay.state === 'running'
  if (!running && dismissed === key) return live

  const percent = replay.total ? (replay.sent / replay.total) * 100 : 100
  return (
    <>
      {live}
    <div className={`replay-banner ${running ? '' : 'done'}`}>
      <strong>▶ {STATE_TEXT[replay.state]}</strong>
      <span className="mono">{replay.sessionId}</span>
      <span className="mono muted">
        {replay.position.toFixed(1)} / {replay.duration.toFixed(1)} s · {replay.speed}× · {replay.sent}/{replay.total}{' '}
        msgs{replay.includeCommands ? ' · with commands' : ''}
        {replay.currentTime ? ' · current time' : ''}
      </span>
      <span className="replay-progress">
        <span style={{ width: `${percent}%` }} />
      </span>
      {running ? (
        <button
          type="button"
          disabled={readOnly || stopping}
          title={readOnly ? VIEWER_NOTE : undefined}
          onClick={() => {
            setStopping(true)
            stopReplay()
              .catch(() => {})
              .finally(() => setStopping(false))
          }}
        >
          {stopping ? 'Stopping…' : '■ Stop replay'}
        </button>
      ) : (
        <button type="button" onClick={() => setDismissed(key)}>
          Dismiss
        </button>
      )}
    </div>
    </>
  )
}
