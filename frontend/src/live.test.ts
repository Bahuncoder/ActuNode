import { describe, expect, it } from 'vitest'
import {
  batteryCharge,
  missionStatus,
  num,
  point,
  reducer,
  robotErrors,
  robotPose,
  routePoints,
  text,
  type Feed,
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
}

function message(id: number, issues: MqttMessage['issues'] = []): MqttMessage {
  return { id, receivedAt: '2026-10-10T12:00:00Z', topic: 'uagv/v2/ActuNode/r1/state', retained: false, validJson: true, payload: {}, issues }
}

// Robot data arrives from any MQTT client, so build deliberately wrong shapes.
function robotWith(state: unknown): Robot {
  return { robotId: 'r1', connection: 'ONLINE', state: state as Robot['state'], lastSeen: null }
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
