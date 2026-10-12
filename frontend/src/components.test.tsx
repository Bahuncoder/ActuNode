import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Robot } from './live'
import MessageStream from './MessageStream'
import RobotTable from './RobotTable'
import WarehouseMap from './WarehouseMap'

afterEach(cleanup)

// Regression: a state with batteryCharge as a string once blanked the whole UI (D-9).
const malformed: Robot = {
  key: 'v2/ActuNode/amr_7',
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
  key: 'v2/ActuNode/robot_01',
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
  key: 'v3/ActuNode/robot_31',
  manufacturer: 'ActuNode',
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
    const close: Robot = { ...v3robot, key: 'v3/ActuNode/robot_02', robotId: 'robot_02', state: { ...v3robot.state!, mobileRobotPosition: { x: 1.5, y: 2, theta: 0 } } }
    const { container } = render(
      <WarehouseMap robots={[healthy, close]} locations={{}} proximity={[{ robots: ['v2/ActuNode/robot_01', 'v3/ActuNode/robot_02'], distance: 0.25 }]} />,
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
    const body = await sentBody(v3robot, null)

    expect(body.manufacturer).toBeUndefined()
    expect(body.vda_version).toBeUndefined()
    expect(screen.getByText(/was seen as ActuNode · VDA 3/)).toBeTruthy()
  })

  it('sends exactly the identity that was chosen', async () => {
    const body = await sentBody(v3robot, '0')

    expect(body).toMatchObject({ manufacturer: 'ActuNode', vda_version: '3' })
  })

  it('cannot be tricked by a manufacturer name containing the old separator', async () => {
    const tricky: Robot = { ...v3robot, key: 'v2/Evil|v3/robot_31', vdaMajor: 'v2', manufacturer: 'Evil|v3' }
    const { default: MissionSender } = await import('./MissionSender')
    render(<MissionSender robots={[tricky]} locations={locations} />)

    const option = screen.getByRole('option', { name: /Evil\|v3/ }) as HTMLOptionElement
    expect(option.disabled).toBe(true)
  })
})

describe('robots sharing a serial', () => {
  const vendorA: Robot = { ...healthy, key: 'v2/VendorA/robot_01', vdaMajor: 'v2', manufacturer: 'VendorA', lastSeen: '2026-10-10T12:00:00Z' }
  const vendorB: Robot = { ...healthy, key: 'v2/VendorB/robot_01', vdaMajor: 'v2', manufacturer: 'VendorB', lastSeen: '2026-10-10T12:00:05Z' }

  it('tells them apart in the table, and only then', () => {
    const { rerender } = render(<RobotTable robots={[vendorA, vendorB]} />)
    expect(screen.getByText(/VendorA v2/)).toBeTruthy()
    expect(screen.getByText(/VendorB v2/)).toBeTruthy()

    rerender(<RobotTable robots={[vendorA]} />)
    expect(screen.queryByText(/VendorA/)).toBeNull()
  })

  it('are listed once in the failure injection select', async () => {
    const { default: FailurePanel } = await import('./FailurePanel')
    render(<FailurePanel robots={[vendorA, vendorB]} failures={[]} />)

    expect(screen.getAllByRole('option')).toHaveLength(1)
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

describe('payloads that are valid JSON but not what VDA 5050 says', () => {
  const base = { id: 1, receivedAt: '2026-10-11T00:00:00Z', retained: false, validJson: true, issues: [] }

  it('MessageStream renders null, number, array and string payloads on every topic kind', () => {
    for (const kind of ['state', 'connection', 'order', 'inject', 'other']) {
      for (const payload of [null, 5, [1], 'text']) {
        render(<MessageStream messages={[{ ...base, topic: `uagv/v2/X/r1/${kind}`, payload }]} />)
        expect(screen.getByText('r1')).toBeTruthy()
        cleanup()
      }
    }
  })

  it('RobotTable renders an object where a string belongs', () => {
    const robot = { key: 'v2/X/r1', robotId: 'r1', connection: { a: 1 }, lastSeen: null, state: null } as unknown as Robot
    render(<RobotTable robots={[robot]} />)
    expect(screen.getByText('r1')).toBeTruthy()
  })
})

describe('RobotTable cancel and load (D-35)', () => {
  const withState = (base: Robot, extra: Record<string, unknown>): Robot => ({
    ...base,
    state: { ...base.state, ...extra } as Robot['state'],
  })
  const status = (base: Robot, missionStatus: string, extra: Record<string, unknown> = {}) =>
    withState(base, { actunode: { missionStatus }, ...extra })

  it('offers Cancel only for active missions', () => {
    const active = ['ACCEPTED', 'MOVING', 'WAITING', 'BLOCKED', 'FAILED'].map((s) => ({ ...status(healthy, s), key: s, robotId: `r_${s}` }))
    render(<RobotTable robots={active} />)
    expect(screen.getAllByRole('button', { name: /^Cancel mission for/ })).toHaveLength(5)
  })

  it('hides Cancel for inactive missions', () => {
    const inactive = ['IDLE', 'COMPLETED', 'CANCELLED'].map((s) => ({ ...status(healthy, s), key: s, robotId: `r_${s}` }))
    render(<RobotTable robots={inactive} />)
    expect(screen.queryAllByRole('button', { name: /^Cancel mission for/ })).toHaveLength(0)
  })

  it('posts the clicked row identity', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ actionId: 'a', topic: 't' }) })
    vi.stubGlobal('fetch', fetchMock)
    render(<RobotTable robots={[healthy, status(v3robot, 'MOVING')]} />)

    fireEvent.click(screen.getByRole('button', { name: 'Cancel mission for robot_31' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(fetchMock.mock.calls[0][0]).toBe('/api/missions/robot_31/cancel')
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ manufacturer: 'ActuNode', vda_version: '3' })
  })

  it('shows the server error on a 409', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: 'no active order' }) }))
    render(<RobotTable robots={[healthy]} />)

    fireEvent.click(screen.getByRole('button', { name: 'Cancel mission for robot_01' }))

    expect((await screen.findByText('robot_01: no active order')).className).toContain('error')
  })

  it('renders the Load column', () => {
    const robots = [
      { ...withState(healthy, { loads: [] }), key: 'a', robotId: 'r_empty' },
      { ...withState(healthy, { loads: [{ loadId: 'pallet-9' }] }), key: 'b', robotId: 'r_full' },
      { ...healthy, key: 'c', robotId: 'r_old' },
    ]
    render(<RobotTable robots={robots} />)
    expect(screen.getByText('empty')).toBeTruthy()
    expect(screen.getByText('pallet-9')).toBeTruthy()
    const loadCol = screen.getAllByRole('columnheader').findIndex((th) => th.textContent === 'Load')
    expect(screen.getAllByRole('row')[3].querySelectorAll('td')[loadCol].textContent).toBe('—')
  })

  it('renders WAITING and CANCELLED badges', () => {
    render(<RobotTable robots={[{ ...status(healthy, 'WAITING'), key: 'w', robotId: 'w' }, { ...status(healthy, 'CANCELLED'), key: 'c', robotId: 'c' }]} />)
    expect(screen.getByText('WAITING').className).toContain('status-waiting')
    expect(screen.getByText('CANCELLED').className).toContain('status-cancelled')
  })

  it('keeps both buttons disabled while two cancels are in flight', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    const a = { ...status(healthy, 'MOVING'), key: 'a', robotId: 'r_a' }
    const b = { ...status(healthy, 'MOVING'), key: 'b', robotId: 'r_b' }
    render(<RobotTable robots={[a, b]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel mission for r_a' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel mission for r_b' }))
    expect((screen.getByRole('button', { name: 'Cancel mission for r_a' }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole('button', { name: 'Cancel mission for r_b' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('names the failing robot in the error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: 'no active order' }) }))
    const a = { ...status(healthy, 'MOVING'), key: 'a', robotId: 'r_a' }
    const b = { ...status(healthy, 'MOVING'), key: 'b', robotId: 'r_b' }
    render(<RobotTable robots={[a, b]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel mission for r_a' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel mission for r_b' }))
    expect(await screen.findByText('r_a: no active order')).toBeTruthy()
    expect(await screen.findByText('r_b: no active order')).toBeTruthy()
  })

  it('shows a PAUSED badge only when paused', () => {
    const p = { ...status(healthy, 'MOVING', { paused: true }), key: 'p', robotId: 'r_p' }
    const n = { ...status(healthy, 'MOVING', { paused: false }), key: 'n', robotId: 'r_n' }
    render(<RobotTable robots={[p, n]} />)
    expect(screen.getAllByText('PAUSED')).toHaveLength(1)
    expect(screen.getByText('PAUSED').className).toContain('status-paused')
  })

  it('marks paused robots in the map tooltip', () => {
    const p = withState(healthy, { paused: true })
    const { container } = render(<WarehouseMap robots={[p]} locations={{}} />)
    expect(container.querySelector('title')?.textContent).toContain('paused')
  })
})
