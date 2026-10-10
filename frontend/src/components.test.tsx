import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { Robot } from './live'
import RobotTable from './RobotTable'
import WarehouseMap from './WarehouseMap'

afterEach(cleanup)

// Regression: a state with batteryCharge as a string once blanked the whole UI (D-9).
const malformed: Robot = {
  robotId: 'amr_7',
  connection: 'ONLINE',
  lastSeen: null,
  state: {
    agvPosition: { x: 'left', y: 2 },
    batteryState: { batteryCharge: '87' },
    nodeStates: 'nope',
    errors: { not: 'a list' },
    actunode: { missionStatus: 42 },
  } as unknown as Robot['state'],
}

const healthy: Robot = {
  robotId: 'robot_01',
  connection: 'ONLINE',
  lastSeen: null,
  state: {
    orderId: 'order-1',
    lastNodeId: 'A',
    driving: true,
    agvPosition: { x: 1.25, y: 2, theta: 0 },
    batteryState: { batteryCharge: 97.5, charging: false },
    nodeStates: [{ nodeId: 'B', sequenceId: 2, nodePosition: { x: 5, y: 5 } }],
    errors: [],
    actunode: { missionStatus: 'MOVING' },
  },
}

describe('RobotTable', () => {
  it('renders a malformed robot without crashing', () => {
    render(<RobotTable robots={[malformed, healthy]} />)

    expect(screen.getByText('amr_7')).toBeTruthy()
    expect(screen.getByText('UNKNOWN')).toBeTruthy()
    expect(screen.getByText('97.5%')).toBeTruthy()
    expect(screen.getByText('1.3, 2.0')).toBeTruthy()
  })
})

describe('WarehouseMap', () => {
  it('draws healthy robots and their routes, and skips robots without a valid position', () => {
    const { container } = render(<WarehouseMap robots={[malformed, healthy]} locations={{}} />)

    expect(container.querySelectorAll('g.robot')).toHaveLength(1)
    expect(container.querySelectorAll('polyline.route')).toHaveLength(1)
  })
})
