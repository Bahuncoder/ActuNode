import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
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

const v3robot: Robot = {
  robotId: 'robot_31',
  connection: 'ONLINE',
  lastSeen: null,
  vdaMajor: 'v3',
  state: {
    version: '3.0.0',
    orderId: '',
    lastNodeId: '',
    driving: false,
    mobileRobotPosition: { x: 7, y: 3, theta: 0, mapId: 'warehouse', localized: true },
    powerSupply: { stateOfCharge: 64, charging: false },
    nodeStates: [],
    errors: [],
    actunode: { missionStatus: 'IDLE' },
  } as unknown as Robot['state'],
}

describe('WarehouseMap near-misses', () => {
  it('highlights robots that are too close and joins them with a line', () => {
    const close: Robot = { ...v3robot, robotId: 'robot_02', state: { ...v3robot.state!, mobileRobotPosition: { x: 1.5, y: 2, theta: 0 } } }
    const { container } = render(
      <WarehouseMap robots={[healthy, close]} locations={{}} proximity={[{ robots: ['robot_01', 'robot_02'], distance: 0.25 }]} />,
    )

    expect(container.querySelectorAll('g.robot.near')).toHaveLength(2)
    expect(container.querySelectorAll('line.proximity')).toHaveLength(1)
  })
})

describe('mixed fleet (VDA 5050 2.1 and 3.0)', () => {
  it('shows each robot with its version, position and charge', () => {
    render(<RobotTable robots={[healthy, v3robot]} />)

    expect(screen.getByText('3.0.0')).toBeTruthy()
    expect(screen.getByText('64.0%')).toBeTruthy()
    expect(screen.getByText('7.0, 3.0')).toBeTruthy()
  })

  it('draws 3.0 robots on the map', () => {
    const { container } = render(<WarehouseMap robots={[healthy, v3robot]} locations={{}} />)

    expect(container.querySelectorAll('g.robot')).toHaveLength(2)
  })
})

describe('WarehouseMap', () => {
  it('draws healthy robots and their routes, and skips robots without a valid position', () => {
    const { container } = render(<WarehouseMap robots={[malformed, healthy]} locations={{}} />)

    expect(container.querySelectorAll('g.robot')).toHaveLength(1)
    expect(container.querySelectorAll('polyline.route')).toHaveLength(1)
  })
})

describe('MissionSender target', () => {
  const locations = { A: { x: 0, y: 0, zone: 'z' } }

  async function sentBody(robot: Robot, chooseValue: string | null) {
    const { default: MissionSender } = await import('./MissionSender')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ order_id: 'o', topic: 't' }) })
    vi.stubGlobal('fetch', fetchMock)
    render(<MissionSender robots={[robot]} locations={locations} />)
    const target = screen.getByTitle(/Where the order is published/).querySelector('select') as HTMLSelectElement
    if (chooseValue !== null) fireEvent.change(target, { target: { value: chooseValue } })
    fireEvent.click(screen.getByText('Send mission'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    vi.unstubAllGlobals()
    return JSON.parse(fetchMock.mock.calls[0][1].body)
  }

  it('preselects nothing: observed identities are a choice, not a default (D-21)', async () => {
    const one: Robot = { ...v3robot, identities: [{ vdaMajor: 'v3', manufacturer: 'ActuNode', lastSeen: 'x' }] }

    const body = await sentBody(one, null)

    expect(body.manufacturer).toBeUndefined()
    expect(body.vda_version).toBeUndefined()
    expect(screen.getByText(/was seen as ActuNode · VDA 3/)).toBeTruthy()
  })

  it('sends exactly the identity that was chosen', async () => {
    const one: Robot = { ...v3robot, identities: [{ vdaMajor: 'v3', manufacturer: 'ActuNode', lastSeen: 'x' }] }

    const body = await sentBody(one, '0')

    expect(body).toMatchObject({ manufacturer: 'ActuNode', vda_version: '3' })
  })

  it('cannot be tricked by a manufacturer name containing the old separator', async () => {
    const tricky: Robot = { ...v3robot, identities: [{ vdaMajor: 'v2', manufacturer: 'Evil|v3', lastSeen: 'x' }] }
    const { default: MissionSender } = await import('./MissionSender')
    render(<MissionSender robots={[tricky]} locations={locations} />)

    const option = screen.getByRole('option', { name: /Evil\|v3/ }) as HTMLOptionElement
    expect(option.disabled).toBe(true)
  })
})

describe('MissionSender robot', () => {
  it('sends to the robot it shows, even if the default robot does not exist', async () => {
    const { default: MissionSender } = await import('./MissionSender')
    render(<MissionSender robots={[v3robot]} locations={{ A: { x: 0, y: 0, zone: 'z' } }} />)

    const robotSelect = screen.getAllByRole('combobox')[0] as HTMLSelectElement
    expect(robotSelect.value).toBe('robot_31')
  })
})
