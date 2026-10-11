import { useEffect, useReducer } from 'react'

const MAX_MESSAGES = 500
const RECONNECT_MS = 2000

export type NodeState = {
  nodeId: string
  sequenceId: number
  nodePosition?: { x: number; y: number }
}

export type RobotError = {
  errorType: string
  errorLevel: string
  errorDescription?: string
}

export type RobotState = {
  orderId: string
  lastNodeId: string
  driving: boolean
  version?: string
  // VDA 5050 2.x names ...
  agvPosition?: { x: number; y: number; theta: number }
  batteryState?: { batteryCharge: number; charging: boolean }
  // ... and their 3.0 replacements (docs/research/VDA5050_3_0.md)
  mobileRobotPosition?: { x: number; y: number; theta: number }
  powerSupply?: { stateOfCharge: number; charging: boolean }
  nodeStates: NodeState[]
  errors: RobotError[]
  actunode?: { missionStatus: string }
}

export type Robot = {
  // "v2/ActuNode/robot_01": one robot is one (vdaMajor, manufacturer, serial); robotId is the serial.
  key: string
  robotId: string
  connection: string | null
  state: RobotState | null
  lastSeen: string | null
  vdaMajor?: string
  manufacturer?: string
}

/** Every (version, manufacturer) seen for a serial, most recent first. Display and advice only, never routing (D-21). */
export function identitiesOf(
  robots: Robot[],
  robotId: string,
): { vdaMajor: string; manufacturer: string; lastSeen: string }[] {
  return robots
    .filter((robot) => robot.robotId === robotId && robot.vdaMajor && robot.manufacturer)
    .sort((a, b) => (b.lastSeen ?? '').localeCompare(a.lastSeen ?? ''))
    .map((robot) => ({ vdaMajor: robot.vdaMajor!, manufacturer: robot.manufacturer!, lastSeen: robot.lastSeen ?? '' }))
}

export type Issue = {
  severity: 'error' | 'warning'
  rule: string
  message: string
  path: string
}

export type MqttMessage = {
  id: number
  receivedAt: string
  topic: string
  retained: boolean
  validJson: boolean
  payload: unknown
  issues: Issue[]
}

export type RuleCount = {
  rule: string
  description: string
  severity: 'error' | 'warning'
  count: number
  last?: { message: string; topic: string; at: string }
}

export type ValidationSummary = {
  since: string
  checked: number
  withIssues: number
  byRule: RuleCount[]
}

export type FailureEntry = {
  injectionId: string
  timestamp: string
  robotId: string
  failure: string
  action: 'inject' | 'clear'
  robotStatus: string
}

export type RecordingStatus = {
  sessionId: string
  name: string | null
  startedAt: string
  messageCount: number
  duration: number
  sizeBytes?: number
  maxBytes?: number
}

/** Two live robots currently closer than the minimum distance (near-collision, reported by the backend). */
export type ProximityPair = { robots: string[]; distance: number }

/** Set when the server stopped a recording by itself (size limit or write error). */
export type RecordingStopped = { sessionId: string; reason: string }

export type ReplayStatus = {
  sessionId: string
  state: 'running' | 'finished' | 'stopped' | 'failed'
  speed: number
  includeCommands: boolean
  sent: number
  total: number
  position: number
  duration: number
}

type LiveEvent =
  | {
      type: 'snapshot'
      robots: Robot[]
      messages: MqttMessage[]
      failures: FailureEntry[]
      recording: RecordingStatus | null
      replay: ReplayStatus | null
      validation: ValidationSummary
      proximity?: ProximityPair[]
    }
  | { type: 'proximity'; pairs: ProximityPair[] }
  | { type: 'validation'; validation: ValidationSummary }
  | { type: 'recording'; recording: RecordingStatus | null; stoppedReason?: string; stopped?: RecordingStatus }
  | { type: 'replay'; replay: ReplayStatus | null }
  | { type: 'message'; message: MqttMessage; robot: Robot | null }
  | { type: 'failure'; failure: FailureEntry }

export type Feed = {
  connected: boolean
  robots: Record<string, Robot>
  messages: MqttMessage[]
  failures: FailureEntry[]
  recording: RecordingStatus | null
  recordingStopped: RecordingStopped | null
  replay: ReplayStatus | null
  validation: ValidationSummary | null
  proximity: ProximityPair[]
}

type Action = { type: 'connected' | 'disconnected' } | { type: 'event'; event: LiveEvent }

// Exported for tests.
export function reducer(feed: Feed, action: Action): Feed {
  switch (action.type) {
    case 'connected':
      return { ...feed, connected: true }
    case 'disconnected':
      return { ...feed, connected: false }
    case 'event':
      return applyEvent(feed, action.event)
  }
}

function applyEvent(feed: Feed, event: LiveEvent): Feed {
  if (event.type === 'snapshot') {
    return {
      ...feed,
      robots: Object.fromEntries(event.robots.map((robot) => [robot.key, robot])),
      messages: event.messages,
      failures: event.failures,
      recording: event.recording,
      replay: event.replay,
      validation: event.validation,
      proximity: event.proximity ?? [],
    }
  }
  if (event.type === 'proximity') {
    return { ...feed, proximity: event.pairs }
  }
  if (event.type === 'validation') {
    return { ...feed, validation: event.validation }
  }
  if (event.type === 'recording') {
    const recordingStopped =
      event.stoppedReason && event.stopped
        ? { sessionId: event.stopped.sessionId, reason: event.stoppedReason }
        : event.recording
          ? null // a new recording clears an old notice
          : feed.recordingStopped
    return { ...feed, recording: event.recording, recordingStopped }
  }
  if (event.type === 'replay') {
    return { ...feed, replay: event.replay }
  }
  if (event.type === 'failure') {
    if (feed.failures.some((entry) => entry.injectionId === event.failure.injectionId)) return feed
    return { ...feed, failures: [...feed.failures, event.failure] }
  }
  // The server subscribes us before sending the snapshot, so a message can arrive twice.
  const lastId = feed.messages.at(-1)?.id ?? 0
  if (event.message.id <= lastId) return feed

  const robots = event.robot ? { ...feed.robots, [event.robot.key]: event.robot } : feed.robots
  return {
    ...feed,
    robots,
    messages: [...feed.messages, event.message].slice(-MAX_MESSAGES),
    validation: countIssues(feed.validation, event.message),
  }
}

// Keep the per-rule counters in step with the server's without polling.
function countIssues(validation: ValidationSummary | null, message: MqttMessage): ValidationSummary | null {
  if (!validation) return validation
  const issues = message.issues ?? []
  const byRule = validation.byRule.map((rule) => ({ ...rule }))
  for (const issue of issues) {
    let rule = byRule.find((candidate) => candidate.rule === issue.rule)
    if (!rule) {
      rule = { rule: issue.rule, description: '', severity: issue.severity, count: 0 }
      byRule.push(rule)
    }
    rule.count += 1
    rule.last = { message: issue.message, topic: message.topic, at: message.receivedAt }
  }
  byRule.sort((a, b) => b.count - a.count)
  return {
    ...validation,
    checked: validation.checked + 1,
    withIssues: validation.withIssues + (issues.length > 0 ? 1 : 0),
    byRule,
  }
}

/** Live robots and MQTT messages from the backend WebSocket, reconnecting on drop. */
export function useLiveFeed(): Feed {
  const [feed, dispatch] = useReducer(reducer, {
    connected: false,
    robots: {},
    messages: [],
    failures: [],
    recording: null,
    recordingStopped: null,
    replay: null,
    validation: null,
    proximity: [],
  })

  useEffect(() => {
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | undefined
    let closed = false

    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
      socket = new WebSocket(`${protocol}://${window.location.host}/api/ws`)
      socket.onopen = () => dispatch({ type: 'connected' })
      socket.onmessage = (message) => dispatch({ type: 'event', event: JSON.parse(message.data) })
      socket.onclose = () => {
        dispatch({ type: 'disconnected' })
        if (!closed) retry = setTimeout(connect, RECONNECT_MS)
      }
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      socket?.close()
    }
  }, [])

  return feed
}

// Robot data comes from any MQTT client and may be malformed (that is what ActuNode is for),
// so the UI reads it through these helpers instead of trusting the RobotState type.

export function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function point(value: unknown): { x: number; y: number } | undefined {
  const candidate = value as { x?: unknown; y?: unknown } | null
  const x = num(candidate?.x)
  const y = num(candidate?.y)
  return x === undefined || y === undefined ? undefined : { x, y }
}

export function robotPose(robot: Robot): { x: number; y: number; theta: number } | undefined {
  const raw = robot.state?.agvPosition ?? robot.state?.mobileRobotPosition // 2.x or 3.0
  const position = point(raw)
  return position && { ...position, theta: num(raw?.theta) ?? 0 }
}

export function batteryCharge(robot: Robot): number | undefined {
  return num(robot.state?.batteryState?.batteryCharge) ?? num(robot.state?.powerSupply?.stateOfCharge) // 2.x or 3.0
}

export function routePoints(robot: Robot): { x: number; y: number }[] {
  const nodes = robot.state?.nodeStates
  return Array.isArray(nodes) ? nodes.flatMap((node) => point(node?.nodePosition) ?? []) : []
}

export function robotErrors(robot: Robot): string[] {
  const errors = robot.state?.errors
  if (!Array.isArray(errors)) return []
  return errors.map((error) => String(error?.errorDescription ?? error?.errorType ?? 'error'))
}

export function text(value: unknown): string {
  return typeof value === 'string' && value ? value : '—'
}

export function missionStatus(robot: Robot): string {
  const status = robot.state?.actunode?.missionStatus
  return typeof status === 'string' ? status : 'UNKNOWN'
}

export function isOnline(robot: Robot): boolean {
  return robot.connection === 'ONLINE'
}
