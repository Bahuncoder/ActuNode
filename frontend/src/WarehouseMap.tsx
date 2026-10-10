import type { Location } from './api'
import { isOnline, missionStatus, robotPose, routePoints, type ProximityPair, type Robot } from './live'

// Warehouse floor in meters, origin bottom-left (same frame as the simulator).
const WIDTH_M = 40
const HEIGHT_M = 20
const PX_PER_M = 20

const ZONES = [
  { label: 'RECEIVING', x: 0, y: 11, w: 5, h: 9 },
  { label: 'STORAGE RACKS', x: 9, y: 9, w: 12, h: 11 },
  { label: 'PACK / SORT', x: 25, y: 11, w: 6, h: 8 },
  { label: 'LOADING DOCKS', x: 35, y: 9, w: 5, h: 11 },
  { label: 'CHARGING', x: 0, y: 0, w: 12, h: 4 },
  { label: 'CONVEYOR', x: 14, y: 3, w: 20, h: 2 },
]

const RACK_ROWS = [11, 13.5, 16, 18.5]

// Locations this far right get their label on the left so it stays on the map.
const LABEL_FLIP_X = 32

const px = (x: number) => x * PX_PER_M
const py = (y: number) => (HEIGHT_M - y) * PX_PER_M

export default function WarehouseMap({
  robots,
  locations,
  proximity = [],
}: {
  robots: Robot[]
  locations: Record<string, Location>
  proximity?: ProximityPair[]
}) {
  const near = new Set(proximity.flatMap((pair) => pair.robots))
  const poses = new Map(robots.map((robot) => [robot.robotId, robotPose(robot)]))
  return (
    <svg
      className="warehouse-map"
      viewBox={`0 0 ${px(WIDTH_M)} ${py(0)}`}
      role="img"
      aria-label="Warehouse map with robot positions"
    >
      <rect className="floor" x={0} y={0} width={px(WIDTH_M)} height={py(0)} />

      {ZONES.map((zone) => (
        <g key={zone.label}>
          <rect className="zone" x={px(zone.x)} y={py(zone.y + zone.h)} width={zone.w * PX_PER_M} height={zone.h * PX_PER_M} />
          <text className="zone-label" x={px(zone.x) + 6} y={py(zone.y + zone.h) + 14}>
            {zone.label}
          </text>
        </g>
      ))}

      {RACK_ROWS.map((y) => (
        <rect key={y} className="rack" x={px(10)} y={py(y + 0.4)} width={10 * PX_PER_M} height={0.8 * PX_PER_M} />
      ))}

      {Object.entries(locations).map(([name, location]) => (
        <g key={name}>
          <rect
            className="location"
            x={px(location.x) - 4}
            y={py(location.y) - 4}
            width={8}
            height={8}
            transform={`rotate(45 ${px(location.x)} ${py(location.y)})`}
          />
          <text
            className="location-label"
            x={px(location.x) + (location.x > LABEL_FLIP_X ? -8 : 8)}
            y={py(location.y) + 14}
            textAnchor={location.x > LABEL_FLIP_X ? 'end' : 'start'}
          >
            {name}
          </text>
        </g>
      ))}

      {robots.map((robot) => (
        <RobotRoute key={`route-${robot.robotId}`} robot={robot} />
      ))}
      {proximity.map((pair) => {
        const [a, b] = pair.robots.map((id) => poses.get(id))
        if (!a || !b) return null
        return (
          <line key={pair.robots.join('-')} className="proximity" x1={px(a.x)} y1={py(a.y)} x2={px(b.x)} y2={py(b.y)}>
            <title>{`${pair.robots.join(' and ')}: ${pair.distance} m apart`}</title>
          </line>
        )
      })}
      {robots.map((robot) => (
        <RobotMarker key={robot.robotId} robot={robot} near={near.has(robot.robotId)} />
      ))}
    </svg>
  )
}

function RobotRoute({ robot }: { robot: Robot }) {
  const position = robotPose(robot)
  const route = routePoints(robot)
  if (!position || route.length === 0) return null

  const points = [position, ...route]
  // Route the robot cannot finish right now: blocked path or empty battery.
  const blocked = ['BLOCKED', 'FAILED'].includes(missionStatus(robot))
  return (
    <polyline
      className={`route ${blocked ? 'blocked' : ''}`}
      points={points.map((point) => `${px(point.x)},${py(point.y)}`).join(' ')}
    />
  )
}

// "robot_07" -> "07" keeps labels apart when robots park 2 m apart; the full id is in the tooltip.
function shortLabel(robotId: string): string {
  return robotId.replace(/^robot_/, '')
}

function RobotMarker({ robot, near }: { robot: Robot; near: boolean }) {
  const position = robotPose(robot)
  if (!position) return null

  const status = missionStatus(robot).toLowerCase()
  const heading = -position.theta * (180 / Math.PI)
  return (
    <g
      className={`robot status-${status} ${isOnline(robot) ? '' : 'offline'} ${near ? 'near' : ''}`}
      style={{ transform: `translate(${px(position.x)}px, ${py(position.y)}px)` }}
    >
      <title>{`${robot.robotId}: ${missionStatus(robot)}`}</title>
      <circle r={9} />
      <line x1={0} y1={0} x2={13} y2={0} transform={`rotate(${heading})`} />
      <text y={-14}>{shortLabel(robot.robotId)}</text>
    </g>
  )
}
