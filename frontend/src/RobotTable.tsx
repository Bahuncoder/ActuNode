import { isOnline, missionStatus, type Robot } from './live'

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
            const state = robot.state
            const status = missionStatus(robot)
            const battery = state?.batteryState?.batteryCharge
            return (
              <tr key={robot.robotId}>
                <td className="mono">{robot.robotId}</td>
                <td>
                  <span className={`badge ${isOnline(robot) ? 'ok' : 'down'}`}>{robot.connection ?? '—'}</span>
                </td>
                <td>
                  <span className={`badge status-${status.toLowerCase()}`}>{status}</span>
                </td>
                <td>
                  {battery === undefined ? '—' : (
                    <span className="battery">
                      <span className="battery-bar" style={{ width: `${battery}%` }} />
                      <span className="mono">{battery.toFixed(1)}%</span>
                    </span>
                  )}
                </td>
                <td className="mono">
                  {state?.agvPosition ? `${state.agvPosition.x.toFixed(1)}, ${state.agvPosition.y.toFixed(1)}` : '—'}
                </td>
                <td className="mono">{state?.orderId || '—'}</td>
                <td className="mono">{state?.lastNodeId || '—'}</td>
                <td className={state?.errors.length ? 'error-text' : ''}>
                  {state?.errors.length ? state.errors.map((e) => e.errorDescription ?? e.errorType).join('; ') : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
