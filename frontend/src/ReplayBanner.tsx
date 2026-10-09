import { useState } from 'react'
import { stopReplay } from './api'
import type { ReplayStatus } from './live'

const STATE_TEXT = { running: 'REPLAYING', finished: 'REPLAY FINISHED', stopped: 'REPLAY STOPPED', failed: 'REPLAY FAILED' }

/** Shown while a session replays, so replayed traffic is never mistaken for live robots. */
export default function ReplayBanner({ replay }: { replay: ReplayStatus | null }) {
  const [dismissed, setDismissed] = useState<string | null>(null)
  if (!replay) return null

  const running = replay.state === 'running'
  const key = `${replay.sessionId}:${replay.state}`
  if (!running && dismissed === key) return null

  const percent = replay.total ? (replay.sent / replay.total) * 100 : 100
  return (
    <div className={`replay-banner ${running ? '' : 'done'}`} role="status">
      <strong>▶ {STATE_TEXT[replay.state]}</strong>
      <span className="mono">{replay.sessionId}</span>
      <span className="mono muted">
        {replay.position.toFixed(1)} / {replay.duration.toFixed(1)} s · {replay.speed}× · {replay.sent}/{replay.total}{' '}
        msgs{replay.includeCommands ? ' · with commands' : ''}
      </span>
      <span className="replay-progress">
        <span style={{ width: `${percent}%` }} />
      </span>
      {running ? (
        <button type="button" onClick={() => stopReplay().catch(() => {})}>
          ■ Stop replay
        </button>
      ) : (
        <button type="button" onClick={() => setDismissed(key)}>
          Dismiss
        </button>
      )}
    </div>
  )
}
