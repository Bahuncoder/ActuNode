import { useState } from 'react'
import { cancelMission } from './api'
import { batteryCharge, isOnline, missionStatus, robotErrors, robotPose, text, type Robot } from './live'

// FAILED keeps its order (VDA 5050 3.0 §6.6.5.1: errors never clear an order), so it can be cancelled too.
const CANCELLABLE = ['ACCEPTED', 'MOVING', 'WAITING', 'BLOCKED', 'FAILED']

function loadText(robot: Robot): string {
  const loads = robot.state?.loads
  if (!Array.isArray(loads)) return '—'
  return loads.length === 0 ? 'empty' : loads.map((load) => text(load?.loadId)).join(', ')
}

export default function RobotTable({ robots }: { robots: Robot[] }) {
  const [cancelling, setCancelling] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function cancel(robot: Robot) {
    setCancelling(robot.key)
    setError(null)
    try {
      await cancelMission(robot)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setCancelling(null)
    }
  }

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
            {robots.map((robot) => {
              const status = missionStatus(robot)
              const battery = batteryCharge(robot)
              const pose = robotPose(robot)
              const errors = robotErrors(robot)
              return (
                <tr key={robot.key}>
                  <td className="mono">
                    {robot.robotId}
                    {robots.some((other) => other !== robot && other.robotId === robot.robotId) && (
                      <span className="muted">{` · ${robot.manufacturer ?? '—'} ${robot.vdaMajor ?? ''}`}</span>
                    )}
                  </td>
                  <td>
                    <span className={`badge ${isOnline(robot) ? 'ok' : 'down'}`}>{text(robot.connection)}</span>
                  </td>
                  <td className="mono">{text(robot.state?.version)}</td>
                  <td>
                    <span className={`badge status-${status.toLowerCase()}`}>{status}</span>
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
                  <td className="mono">{text(robot.state?.orderId)}</td>
                  <td className="mono">{text(robot.state?.lastNodeId)}</td>
                  <td className="mono">{loadText(robot)}</td>
                  <td className={errors.length ? 'error-text' : ''}>{errors.length ? errors.join('; ') : '—'}</td>
                  <td>
                    {CANCELLABLE.includes(status) && (
                      <button
                        aria-label={`Cancel mission for ${robot.robotId}`}
                        disabled={cancelling === robot.key}
                        onClick={() => cancel(robot)}
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {error && <p className="result error">{error}</p>}
    </>
  )
}
