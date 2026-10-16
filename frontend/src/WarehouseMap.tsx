import { memo } from 'react'
import type { Location, MapInfo } from './api'
import { get, isOnline, missionStatus, missionStatusOf, robotPose, routePoints, statusClass, type ProximityPair, type Robot } from './live'

// Built-in floor in meters, origin bottom-left (same frame as the simulator); used until /api/map answers.
const FALLBACK_MAP: MapInfo = {
  size: { width: 40, height: 20 },
  zones: [
    { id: 'RECEIVING', label: 'RECEIVING', x: 0, y: 11, w: 5, h: 9 },
    { id: 'STORAGE', label: 'STORAGE RACKS', x: 9, y: 9, w: 12, h: 11 },
    { id: 'PACK_SORT', label: 'PACK / SORT', x: 25, y: 11, w: 6, h: 8 },
    { id: 'LOADING', label: 'LOADING DOCKS', x: 35, y: 9, w: 5, h: 11 },
    { id: 'CHARGING', label: 'CHARGING', x: 0, y: 0, w: 12, h: 4 },
    { id: 'CONVEYOR', label: 'CONVEYOR', x: 14, y: 3, w: 20, h: 2 },
    { id: 'PARKING', label: 'PARKING', x: 0, y: 5, w: 8.5, h: 5.5 },
  ],
  racks: [11, 13.5, 16, 18.5].map((y) => ({ x: 10, y: y - 0.4, w: 10, h: 0.8 })),
  locations: {},
}

// The map id robots report in their position (simulator MAP_ID).
const MAP_ID = 'warehouse'
const PX_PER_M = 20

// Locations this far right get their label on the left so it stays on the map.
const LABEL_FLIP_X = 32

const px = (x: number) => x * PX_PER_M

function WarehouseMap({
  robots,
  locations,
  proximity = [],
  map = FALLBACK_MAP,
}: {
  robots: Robot[]
  locations: Record<string, Location>
  proximity?: ProximityPair[]
  map?: MapInfo
}) {
  const { width, height } = map.size
  const near = new Set(proximity.flatMap((pair) => pair.robots))
  const poses = new Map(robots.map((robot) => [robot.key, robotPose(robot)]))
  const byKey = new Map(robots.map((robot) => [robot.key, robot]))
  const serials = new Map<string, number>()
  for (const robot of robots) serials.set(robot.robotId, (serials.get(robot.robotId) ?? 0) + 1)
  // Pairs carry robot keys; show the plain serial unless another robot shares it.
  const label = (key: string) => {
    const robot = byKey.get(key)
    return robot && serials.get(robot.robotId) === 1 ? robot.robotId : key
  }
  return (
    <svg
      className="warehouse-map"
      viewBox={`0 0 ${px(width)} ${px(height)}`}
      role="img"
      aria-label="Warehouse map with robot positions"
    >
      <Floor map={map} locations={locations} />

      {robots.map((robot) => (
        <RobotRoute key={`route-${robot.key}`} robot={robot} height={height} />
      ))}
      {proximity.map((pair) => {
        const [a, b] = pair.robots.map((key) => poses.get(key))
        if (!a || !b) return null
        return (
          <line key={pair.robots.join('-')} className="proximity" x1={px(a.x)} y1={py(a.y, height)} x2={px(b.x)} y2={py(b.y, height)}>
            <title>{`${pair.robots.map(label).join(' and ')}: ${pair.distance} m apart`}</title>
          </line>
        )
      })}
      {robots.map((robot) => (
        <RobotMarker key={robot.key} robot={robot} near={near.has(robot.key)} width={width} height={height} />
      ))}
    </svg>
  )
}

const py = (y: number, height: number) => (height - y) * PX_PER_M

// Zones, racks and locations only change with the map, not with robots.
const Floor = memo(function Floor({ map, locations }: { map: MapInfo; locations: Record<string, Location> }) {
  const { width, height } = map.size
  return (
    <>
      <rect className="floor" x={0} y={0} width={px(width)} height={px(height)} />

      {map.zones.map((zone) => (
        <g key={zone.id}>
          <rect className="zone" x={px(zone.x)} y={py(zone.y + zone.h, height)} width={zone.w * PX_PER_M} height={zone.h * PX_PER_M} />
          <text className="zone-label" x={px(zone.x) + 6} y={py(zone.y + zone.h, height) + 14}>
            {zone.label}
          </text>
        </g>
      ))}

      {map.racks.map((rack, index) => (
        <rect key={index} className="rack" x={px(rack.x)} y={py(rack.y + rack.h, height)} width={rack.w * PX_PER_M} height={rack.h * PX_PER_M} />
      ))}

      {Object.entries(locations).map(([name, location]) => (
        <g key={name}>
          <rect
            className="location"
            x={px(location.x) - 4}
            y={py(location.y, height) - 4}
            width={8}
            height={8}
            transform={`rotate(45 ${px(location.x)} ${py(location.y, height)})`}
          />
          <text
            className="location-label"
            x={px(location.x) + (location.x > LABEL_FLIP_X ? -8 : 8)}
            y={py(location.y, height) + 14}
            textAnchor={location.x > LABEL_FLIP_X ? 'end' : 'start'}
          >
            {name}
          </text>
        </g>
      ))}
    </>
  )
})

const RobotRoute = memo(function RobotRoute({ robot, height }: { robot: Robot; height: number }) {
  const position = robotPose(robot)
  const route = routePoints(robot)
  if (!position || route.length === 0) return null

  const points = [position, ...route]
  // Route the robot cannot finish right now: blocked path or empty battery.
  const blocked = ['BLOCKED', 'FAILED'].includes(missionStatus(robot))
  return (
    <polyline
      className={`route ${blocked ? 'blocked' : ''}`}
      points={points.map((point) => `${px(point.x)},${py(point.y, height)}`).join(' ')}
    />
  )
})

// "robot_07" -> "07" keeps labels apart when robots park 2 m apart; the full id is in the tooltip.
function shortLabel(robotId: string): string {
  return robotId.replace(/^robot_/, '')
}

const RobotMarker = memo(function RobotMarker({ robot, near, width, height }: { robot: Robot; near: boolean; width: number; height: number }) {
  const position = robotPose(robot)
  if (!position) return null

  const offMap = position.x < 0 || position.x > width || position.y < 0 || position.y > height
  const otherMap = position.mapId !== undefined && position.mapId !== MAP_ID
  const x = Math.min(width, Math.max(0, position.x))
  const y = Math.min(height, Math.max(0, position.y))
  const heading = -position.theta * (180 / Math.PI)
  return (
    <g
      className={`robot ${statusClass(missionStatus(robot))} ${isOnline(robot) ? '' : 'offline'} ${near ? 'near' : ''} ${offMap ? 'off-map' : ''} ${otherMap ? 'other-map' : ''}`}
      style={{ transform: `translate(${px(x)}px, ${py(y, height)}px)` }}
    >
      <title>{`${robot.robotId}: ${missionStatus(robot)}${missionStatusOf(robot.state).derived ? ' (derived from VDA 5050 fields)' : ''}${get(robot.state, 'paused') === true ? ' (paused)' : ''}${offMap ? ` - off map (${position.x.toFixed(1)}, ${position.y.toFixed(1)})` : ''}${otherMap ? ` - on map ${position.mapId}` : ''}`}</title>
      <circle r={9} />
      <line x1={0} y1={0} x2={13} y2={0} transform={`rotate(${heading})`} />
      <text y={-14}>{shortLabel(robot.robotId)}</text>
    </g>
  )
})

export default memo(WarehouseMap)
