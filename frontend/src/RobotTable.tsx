import { memo, useCallback, useState } from 'react'
import { cancelMission } from './api'
import {
  batteryCharge,
  CANCELLABLE_STATUSES,
  display,
  failureLabel,
  get,
  injectedFailures,
  isOnline,
  missionStatus,
  num,
  type Robot,
  robotErrors,
  robotPose,
  statusClass,
  stringList,
  text,
} from './live'

function loadText(robot: Robot): string {
  const loads = get(robot.state, 'loads')
  if (!Array.isArray(loads)) return '—'
  return loads.length === 0 ? 'empty' : loads.map((load) => text(get(load, 'loadId'))).join(', ')
}

// The backend keeps only a trimmed copy of very large states (issue 21); say what is missing.
// A robot can publish its own `_truncated`, so every part of it is read defensively.
function trimmedTitle(trimmed: unknown): string {
  const lists = get(trimmed, 'lists')
  const listed = lists !== null && typeof lists === 'object' ? Object.entries(lists).map(([name, length]) => `${name}: first 50 of ${display(length)}`) : []
  const names = stringList(get(trimmed, 'dropped'))
  const dropped = names.length ? [`not stored: ${names.join(', ')}`] : []
  return [`state of ${num(get(trimmed, 'bytes')) ?? '?'} bytes stored trimmed`, ...listed, ...dropped].join('; ')
}

function RobotTable({ robots }: { robots: Robot[] }) {
  const [cancelling, setCancelling] = useState<Set<string>>(new Set())
  // Latest error per robot key, so concurrent failures each name their robot.
  const [errors, setErrors] = useState<Record<string, string>>({})
  // Only robots still listed keep their error.
  const listed = new Set(robots.map((robot) => robot.key))
  const shownErrors = Object.entries(errors).filter(([key]) => listed.has(key))

  const cancel = useCallback(async (robot: Robot) => {
    setCancelling((keys) => new Set(keys).add(robot.key))
    setErrors(({ [robot.key]: _cleared, ...rest }) => rest)
    try {
      await cancelMission(robot)
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err)
      setErrors((current) => ({ ...current, [robot.key]: `${robot.robotId}: ${detail}` }))
    } finally {
      setCancelling((keys) => {
        const next = new Set(keys)
        next.delete(robot.key)
        return next
      })
    }
  }, [])

  // Serials shared by more than one robot (different manufacturer or VDA version) show their identity.
  const serials = new Map<string, number>()
  for (const robot of robots) serials.set(robot.robotId, (serials.get(robot.robotId) ?? 0) + 1)

  if (robots.length === 0) {
    return <p className="empty">No robots yet. Start the simulator: <code>python -m simulator --robots 3</code></p>
  }

  return (
    <>
      <div className="table-scroll">
        <table className="robot-table">
          <thead>
            <tr>
              <th>Robot</th>
              <th>Link</th>
              <th>VDA</th>
              <th>Mission</th>
              <th>Battery</th>
              <th>Position</th>
              <th>Order</th>
              <th>Last node</th>
              <th>Load</th>
              <th>Errors</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {robots.map((robot) => (
              <RobotRow
                key={robot.key}
                robot={robot}
                shared={(serials.get(robot.robotId) ?? 0) > 1}
                cancelling={cancelling.has(robot.key)}
                onCancel={cancel}
              />
            ))}
          </tbody>
        </table>
      </div>
      {shownErrors.map(([key, message]) => (
        <p key={key} className="result error">{message}</p>
      ))}
    </>
  )
}

const RobotRow = memo(function RobotRow({
  robot,
  shared,
  cancelling,
  onCancel,
}: {
  robot: Robot
  shared: boolean
  cancelling: boolean
  onCancel: (robot: Robot) => void
}) {
  const status = missionStatus(robot)
  const battery = batteryCharge(robot)
  const pose = robotPose(robot)
  const errors = robotErrors(robot)
  const injected = injectedFailures(robot) ?? []
  return (
        <tr>
          <td className="mono">
            {robot.robotId}
            {shared && (
              <span className="muted">{` · ${robot.manufacturer ?? '—'} ${robot.vdaMajor ?? ''}`}</span>
            )}
          </td>
          <td>
            <span className={`badge ${isOnline(robot) ? 'ok' : 'down'}`}>{text(robot.connection)}</span>
          </td>
          <td className="mono">{text(get(robot.state, 'version'))}</td>
          <td>
            <span className={`badge ${statusClass(status)}`}>{status}</span>
            {injected.length > 0 && <div className="muted">{`injected: ${injected.map(failureLabel).join(', ')}`}</div>}
            {get(robot.state, 'paused') === true && <span className="badge status-paused">PAUSED</span>}
            {!!get(robot.state, '_truncated') && (
              <span className="muted" title={trimmedTitle(get(robot.state, '_truncated'))}>
                {' '}
                state trimmed
              </span>
            )}
          </td>
          <td>
            {battery === undefined ? '—' : (
              <span className="battery">
                <span className="battery-bar" style={{ width: `${Math.min(100, Math.max(0, battery))}%` }} />
                <span className="mono">{battery.toFixed(1)}%</span>
              </span>
            )}
          </td>
          <td className="mono">{pose ? `${pose.x.toFixed(1)}, ${pose.y.toFixed(1)}` : '—'}</td>
          <td className="mono">{text(get(robot.state, 'orderId'))}</td>
          <td className="mono">{text(get(robot.state, 'lastNodeId'))}</td>
          <td className="mono">{loadText(robot)}</td>
          <td className={errors.length ? 'error-text' : ''}>{errors.length ? errors.join('; ') : '—'}</td>
          <td>
            {CANCELLABLE_STATUSES.includes(status) && (
              <button
                aria-label={`Cancel mission for ${robot.robotId}`}
                disabled={cancelling}
                onClick={() => onCancel(robot)}
              >
                Cancel
              </button>
            )}
          </td>
        </tr>
  )
})

export default memo(RobotTable)
