import { cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MqttMessage, Robot } from './live'
import MessageStream from './MessageStream'
import RobotTable from './RobotTable'
import WarehouseMap from './WarehouseMap'

// Count how often each robot is read while rendering (a memoized row that is skipped is not read).
const reads = vi.hoisted(() => ({ calls: [] as string[] }))
vi.mock('./live', async (importActual) => {
  const actual = await importActual<typeof import('./live')>()
  return { ...actual, missionStatus: (robot: Robot) => (reads.calls.push(robot.key), actual.missionStatus(robot)) }
})

beforeEach(() => {
  reads.calls = []
})
afterEach(cleanup)

function robot(id: string, state: Record<string, unknown> = {}): Robot {
  return {
    key: `v2/ActuNode/${id}`,
    robotId: id,
    connection: 'ONLINE',
    lastSeen: null,
    state: { agvPosition: { x: 5, y: 5, theta: 0, mapId: 'warehouse' }, nodeStates: [], errors: [], ...state } as unknown as Robot['state'],
  }
}

const a = robot('a')
const b = robot('b')

describe('memoized rows', () => {
  it('RobotTable re-renders only the robot that changed', () => {
    const { rerender } = render(<RobotTable robots={[a, b]} />)
    reads.calls = []
    rerender(<RobotTable robots={[a, robot('b', { agvPosition: { x: 6, y: 5, theta: 0 } })]} />)
    expect(new Set(reads.calls)).toEqual(new Set([b.key]))
  })

  it('WarehouseMap redraws only the marker and route of the robot that changed', () => {
    const { rerender } = render(<WarehouseMap robots={[a, b]} locations={{}} />)
    reads.calls = []
    rerender(<WarehouseMap robots={[a, robot('b', { agvPosition: { x: 6, y: 5, theta: 0 } })]} locations={{}} />)
    expect(new Set(reads.calls)).toEqual(new Set([b.key]))
  })

  it('MessageStream formats a row once, not on every new message', () => {
    const msg = (id: number): MqttMessage => ({
      id, receivedAt: '2026-10-10T12:00:00Z', topic: 'uagv/v2/ActuNode/a/state', retained: false, validJson: true, payload: {}, issues: [],
    })
    const spy = vi.spyOn(Date.prototype, 'toLocaleTimeString')
    const first = [msg(1), msg(2)]
    const { rerender } = render(<MessageStream messages={first} />)
    spy.mockClear()
    rerender(<MessageStream messages={[...first, msg(3)]} />)
    expect(spy).toHaveBeenCalledTimes(1)
    spy.mockRestore()
  })
})

describe('WarehouseMap positions', () => {
  it('clamps an off-map robot to the edge and says so', () => {
    const { container } = render(<WarehouseMap robots={[robot('far', { agvPosition: { x: 100, y: -5, theta: 0, mapId: 'warehouse' } })]} locations={{}} />)
    const marker = container.querySelector('g.robot.off-map') as SVGGElement
    expect(marker.querySelector('title')?.textContent).toContain('off map (100.0, -5.0)')
    expect(marker.style.transform).toBe('translate(800px, 400px)')
  })

  it('greys out a robot on another map', () => {
    const { container } = render(<WarehouseMap robots={[robot('elsewhere', { agvPosition: { x: 1, y: 1, theta: 0, mapId: 'annex' } })]} locations={{}} />)
    const marker = container.querySelector('g.robot.other-map') as SVGGElement
    expect(marker.querySelector('title')?.textContent).toContain('on map annex')
    expect(container.querySelector('g.robot.off-map')).toBeNull()
  })

  it('draws zones and racks from the backend map, PARKING included in the fallback', () => {
    const { container, rerender } = render(<WarehouseMap robots={[]} locations={{}} />)
    expect(container.textContent).toContain('PARKING')
    rerender(
      <WarehouseMap
        robots={[]}
        locations={{}}
        map={{ size: { width: 10, height: 10 }, zones: [{ id: 'z', label: 'ZONE X', x: 0, y: 0, w: 2, h: 2 }], racks: [{ x: 3, y: 3, w: 2, h: 1 }], locations: {} }}
      />,
    )
    expect(container.textContent).toContain('ZONE X')
    expect(container.textContent).not.toContain('PARKING')
    expect(container.querySelectorAll('rect.rack')).toHaveLength(1)
    expect(container.querySelector('svg')?.getAttribute('viewBox')).toBe('0 0 200 200')
  })
})
