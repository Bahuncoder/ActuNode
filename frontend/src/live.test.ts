import { renderHook, act } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
// Shared with the backend tests (backend/tests/test_live.py): the real shape the hub broadcasts (D-38).
import contractMessageEvent from '../../contracts/live_message_event.json?raw'
import {
  batteryCharge,
  identitiesOf,
  missionStatus,
  num,
  point,
  reducer,
  robotErrors,
  robotPose,
  routePoints,
  text,
  type Feed,
  useLiveFeed,
  type MqttMessage,
  type Robot,
} from './live'

const empty: Feed = {
  connected: true,
  robots: {},
  messages: [],
  failures: [],
  recording: null,
  recordingStopped: null,
  replay: null,
  validation: { since: 'x', checked: 0, withIssues: 0, byRule: [] },
  proximity: [],
}

function message(id: number, issues: MqttMessage['issues'] = []): MqttMessage {
  return { id, receivedAt: '2026-10-10T12:00:00Z', topic: 'uagv/v2/ActuNode/r1/state', retained: false, validJson: true, payload: {}, issues }
}

// Robot data arrives from any MQTT client, so build deliberately wrong shapes.
function robotWith(state: unknown): Robot {
  return { key: 'v2/ActuNode/r1', robotId: 'r1', connection: 'ONLINE', state: state as Robot['state'], lastSeen: null }
}

// Manual animation frames: queued callbacks run on flush().
function stubFrames() {
  let queue: (() => void)[] = []
  vi.stubGlobal('requestAnimationFrame', (cb: () => void) => queue.push(cb))
  vi.stubGlobal('cancelAnimationFrame', () => {})
  return {
    flush() {
      const run = queue
      queue = []
      run.forEach((cb) => cb())
    },
  }
}

describe('defensive readers for robot data', () => {
  it('accept only finite numbers', () => {
    expect(num(3.5)).toBe(3.5)
    for (const bad of ['87', NaN, Infinity, null, undefined, {}]) expect(num(bad)).toBeUndefined()
  })

  it('read a point only when x and y are numbers', () => {
    expect(point({ x: 1, y: 2 })).toEqual({ x: 1, y: 2 })
    expect(point({ x: '1', y: 2 })).toBeUndefined()
    expect(point(null)).toBeUndefined()
  })

  it('survive a malformed state', () => {
    const robot = robotWith({
      agvPosition: { x: 'left', y: 2 },
      batteryState: { batteryCharge: '87' },
      nodeStates: 'not a list',
      errors: { errorType: 'not a list' },
      actunode: { missionStatus: 42 },
      orderId: 7,
    })
    expect(robotPose(robot)).toBeUndefined()
    expect(batteryCharge(robot)).toBeUndefined()
    expect(routePoints(robot)).toEqual([])
    expect(robotErrors(robot)).toEqual([])
    expect(missionStatus(robot)).toBe('UNKNOWN')
    expect(text(robot.state?.orderId)).toBe('—')
  })

  it('falls back to mobileRobotPosition when agvPosition is malformed', () => {
    const robot = robotWith({ agvPosition: { x: 'left', y: 2 }, mobileRobotPosition: { x: 3, y: 4, theta: 1 } })
    expect(robotPose(robot)).toEqual({ x: 3, y: 4, theta: 1 })
  })

  it('read a well-formed state', () => {
    const robot = robotWith({
      agvPosition: { x: 1, y: 2, theta: 0.5 },
      batteryState: { batteryCharge: 87 },
      nodeStates: [{ nodeId: 'A', sequenceId: 0, nodePosition: { x: 3, y: 4 } }, { nodeId: 'B' }],
      errors: [{ errorType: 'pathBlocked', errorDescription: 'Path blocked' }],
      actunode: { missionStatus: 'BLOCKED' },
    })
    expect(robotPose(robot)).toEqual({ x: 1, y: 2, theta: 0.5 })
    expect(batteryCharge(robot)).toBe(87)
    expect(routePoints(robot)).toEqual([{ x: 3, y: 4 }])
    expect(robotErrors(robot)).toEqual(['Path blocked'])
    expect(missionStatus(robot)).toBe('BLOCKED')
  })
})

describe('backend contract', () => {
  it('applies a state event exactly as the backend sends it (robot without state, stateFromMessage)', () => {
    const event = { ...JSON.parse(contractMessageEvent), id: 1, receivedAt: 'x' }
    event.message = { ...event.message, id: 1, receivedAt: 'x' }
    const feed = reducer(empty, { type: 'event', event })
    const robot = feed.robots[event.robot.key]

    expect(missionStatus(robot)).toBe('MOVING')
    expect(robotPose(robot)?.x).toBe(4)
  })
})

describe('live feed reducer', () => {
  it('ignores a message it already has (the server subscribes before sending the snapshot)', () => {
    const afterSnapshot = reducer(empty, {
      type: 'event',
      event: { ...empty, type: 'snapshot', robots: [], messages: [message(5)], validation: empty.validation! },
    })
    const duplicate = reducer(afterSnapshot, { type: 'event', event: { type: 'message', message: message(5), robot: null } })
    const next = reducer(duplicate, { type: 'event', event: { type: 'message', message: message(6), robot: null } })

    expect(duplicate.messages.map((m) => m.id)).toEqual([5])
    expect(next.messages.map((m) => m.id)).toEqual([5, 6])
  })

  it('counts validation issues per rule as messages arrive', () => {
    const issue = { severity: 'error' as const, rule: 'schema', message: 'bad', path: '/x' }
    let feed = reducer(empty, { type: 'event', event: { type: 'message', message: message(1, [issue]), robot: null } })
    feed = reducer(feed, { type: 'event', event: { type: 'message', message: message(2), robot: null } })

    expect(feed.validation).toMatchObject({ checked: 2, withIssues: 1 })
    expect(feed.validation?.byRule[0]).toMatchObject({ rule: 'schema', count: 1 })
  })

  it('remembers why a recording stopped by itself, and clears it when a new one starts', () => {
    const recording = { sessionId: 's1', name: null, startedAt: 'x', messageCount: 3, duration: 1 }
    const stopped = reducer(empty, {
      type: 'event',
      event: { type: 'recording', recording: null, stoppedReason: 'sizeLimit', stopped: recording },
    })
    const restarted = reducer(stopped, { type: 'event', event: { type: 'recording', recording: { ...recording, sessionId: 's2' } } })

    expect(stopped.recordingStopped).toEqual({ sessionId: 's1', reason: 'sizeLimit' })
    expect(restarted.recordingStopped).toBeNull()
  })

  it('does not add the same failure twice', () => {
    const failure = { injectionId: 'i1', timestamp: 'x', robotId: 'r1', failure: 'BLOCKED_PATH', action: 'inject' as const, robotStatus: 'MOVING' }
    let feed = reducer(empty, { type: 'event', event: { type: 'failure', failure } })
    feed = reducer(feed, { type: 'event', event: { type: 'failure', failure } })

    expect(feed.failures).toHaveLength(1)
  })
})

describe('VDA 5050 3.0 robots', () => {
  const v3 = robotWith({
    version: '3.0.0',
    mobileRobotPosition: { x: 4, y: 5, theta: 1, mapId: 'warehouse', localized: true },
    powerSupply: { stateOfCharge: 72.5, charging: false },
    actunode: { missionStatus: 'MOVING' },
  })

  it('reads position and charge from the 3.0 field names', () => {
    expect(robotPose(v3)).toEqual({ x: 4, y: 5, theta: 1, mapId: 'warehouse' })
    expect(batteryCharge(v3)).toBe(72.5)
  })

  it('prefers nothing invented: a robot with neither shape has no position or charge', () => {
    const bare = robotWith({ version: '3.0.0' })
    expect(robotPose(bare)).toBeUndefined()
    expect(batteryCharge(bare)).toBeUndefined()
  })
})

describe('robots per (version, manufacturer, serial)', () => {
  const a: Robot = { ...robotWith(null), key: 'v2/VendorA/r1', vdaMajor: 'v2', manufacturer: 'VendorA', lastSeen: '2026-10-10T12:00:00Z' }
  const b: Robot = { ...robotWith(null), key: 'v3/VendorB/r1', vdaMajor: 'v3', manufacturer: 'VendorB', lastSeen: '2026-10-10T12:00:09Z' }

  it('keeps both entries when two manufacturers share a serial', () => {
    const feed = reducer(empty, {
      type: 'event',
      event: { ...empty, type: 'snapshot', robots: [a, b], messages: [], validation: empty.validation! },
    })

    expect(Object.keys(feed.robots)).toEqual(['v2/VendorA/r1', 'v3/VendorB/r1'])
  })

  it('lists identities most recent first, unseen last', () => {
    const never: Robot = { ...a, key: 'v2/VendorC/r1', manufacturer: 'VendorC', lastSeen: null }
    const other: Robot = { ...a, key: 'v2/VendorA/r2', robotId: 'r2' }

    expect(identitiesOf([never, a, other, b], 'r1').map((i) => i.manufacturer)).toEqual(['VendorB', 'VendorA', 'VendorC'])
  })
})

describe('proximity', () => {
  it('takes the current near-miss pairs from snapshot and updates', () => {
    const pairs = [{ robots: ['r1', 'r2'], distance: 0.5 }]
    let feed = reducer(empty, {
      type: 'event',
      event: { ...empty, type: 'snapshot', robots: [], messages: [], validation: empty.validation!, proximity: pairs },
    })
    expect(feed.proximity).toEqual(pairs)

    feed = reducer(feed, { type: 'event', event: { type: 'proximity', pairs: [] } })
    expect(feed.proximity).toEqual([])
  })
})

describe('live feed hardening', () => {
  it('ignores a frame the browser cannot parse and keeps the connection', () => {
    const sockets: { onmessage: (m: { data: string }) => void }[] = []
    vi.stubGlobal('WebSocket', function (this: unknown) {
      sockets.push(this as (typeof sockets)[number])
    })
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const frames = stubFrames()
    const { result } = renderHook(() => useLiveFeed())
    const snap = { type: 'snapshot', robots: [robotWith(null)], messages: [], failures: [], recording: null, replay: null, validation: null }
    act(() => {
      sockets[0].onmessage({ data: '{"type":"snapshot","robots":[{"x":NaN}]}' })
      sockets[0].onmessage({ data: JSON.stringify(snap) })
      frames.flush()
    })
    expect(Object.keys(result.current.robots)).toEqual(['v2/ActuNode/r1'])
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
    vi.unstubAllGlobals()
  })

  it('caps robots at 1000 (least recently updated dropped) and failures at 200, like the backend', () => {
    let feed = empty
    for (let i = 1; i <= 1500; i++) {
      const robot = { ...robotWith(null), key: `v2/X/s${i}`, robotId: `s${i}` }
      feed = reducer(feed, { type: 'event', event: { type: 'message', robot, message: message(i) } })
    }
    expect(Object.keys(feed.robots)).toHaveLength(1000)
    expect(feed.robots['v2/X/s1500']).toBeDefined()
    expect(feed.robots['v2/X/s1']).toBeUndefined()
    for (let i = 1; i <= 300; i++) {
      const failure = { injectionId: `f${i}`, timestamp: '', robotId: 'r', failure: 'x', action: 'inject' as const, robotStatus: '' }
      feed = reducer(feed, { type: 'event', event: { type: 'failure', failure } })
    }
    expect(feed.failures).toHaveLength(200)
    expect(feed.failures.at(-1)?.injectionId).toBe('f300')
  })
})

describe('live feed batching and backend contract', () => {
  type FakeSocket = { onmessage: (m: { data: string }) => void; onclose: (e: { code: number }) => void; onopen: () => void; close: () => void }
  function setup() {
    const sockets: FakeSocket[] = []
    vi.stubGlobal('WebSocket', function (this: FakeSocket) {
      this.close = () => {}
      sockets.push(this)
    })
    const frames = stubFrames()
    let renders = 0
    const hook = renderHook(() => {
      renders++
      return useLiveFeed()
    })
    const send = (event: unknown) => sockets.at(-1)!.onmessage({ data: JSON.stringify(event) })
    return { sockets, frames, hook, send, renders: () => renders }
  }

  it('applies all frames of one animation frame in one update, in order', () => {
    const { frames, hook, send, renders } = setup()
    const before = renders()
    act(() => {
      send({ type: 'message', message: message(1), robot: null })
      send({ type: 'message', message: message(2), robot: null })
      send({ type: 'message', message: message(2), robot: null })
      send({ type: 'message', message: message(3), robot: null })
    })
    expect(renders()).toBe(before)
    act(() => frames.flush())
    expect(renders()).toBe(before + 1)
    expect(hook.result.current.messages.map((m) => m.id)).toEqual([1, 2, 3])
    vi.unstubAllGlobals()
  })

  it('falls back to a 50 ms timer without requestAnimationFrame', () => {
    vi.useFakeTimers()
    const { hook, send } = setup()
    vi.stubGlobal('requestAnimationFrame', undefined)
    act(() => send({ type: 'message', message: message(1), robot: null }))
    expect(hook.result.current.messages).toHaveLength(0)
    act(() => {
      vi.advanceTimersByTime(50)
    })
    expect(hook.result.current.messages).toHaveLength(1)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('takes the robot state from the message payload when stateFromMessage is set', () => {
    const { frames, hook, send } = setup()
    const payload = { orderId: 'o1' }
    const robot = { ...robotWith(undefined), state: undefined, stateFromMessage: true }
    act(() => {
      send({ type: 'message', message: { ...message(1), payload }, robot })
      frames.flush()
    })
    expect(hook.result.current.robots['v2/ActuNode/r1'].state).toEqual(payload)
    expect(hook.result.current.robots['v2/ActuNode/r1']).not.toHaveProperty('stateFromMessage')
    vi.unstubAllGlobals()
  })

  it('keeps unchanged robots the same object when another robot changes', () => {
    const a = { ...robotWith(null), key: 'a', robotId: 'a' }
    const b = { ...robotWith(null), key: 'b', robotId: 'b' }
    let feed = reducer(empty, { type: 'event', event: { type: 'message', robot: a, message: message(1) } })
    feed = reducer(feed, { type: 'event', event: { type: 'message', robot: b, message: message(2) } })
    const next = reducer(feed, { type: 'event', event: { type: 'message', robot: { ...b }, message: message(3) } })
    expect(next.robots.a).toBe(feed.robots.a)
  })

  it('reconnects promptly after close code 1013, with the normal backoff otherwise', () => {
    vi.useFakeTimers()
    const { sockets } = setup()
    act(() => sockets[0].onclose({ code: 1013 }))
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(sockets).toHaveLength(2)
    act(() => sockets[1].onclose({ code: 1006 }))
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(sockets).toHaveLength(2)
    act(() => {
      vi.advanceTimersByTime(2000)
    })
    expect(sockets).toHaveLength(3)
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })
})
