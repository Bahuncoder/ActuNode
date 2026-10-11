import { batteryCharge, isOnline, missionStatus, robotErrors, robotPose, text, type Robot } from './live'

export default function RobotTable({ robots }: { robots: Robot[] }) {
  if (robots.length === 0) {
    return <p className="empty">No robots yet. Start the simulator: <code>python -m simulator --robots 3</code></p>
  }

  return (
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
            <th>Errors</th>
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
                <td className={errors.length ? 'error-text' : ''}>{errors.length ? errors.join('; ') : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
