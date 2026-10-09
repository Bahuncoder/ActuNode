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
  agvPosition?: { x: number; y: number; theta: number }
  batteryState?: { batteryCharge: number; charging: boolean }
  nodeStates: NodeState[]
  errors: RobotError[]
  actunode?: { missionStatus: string }
}

export type Robot = {
  robotId: string
  connection: string | null
  state: RobotState | null
  lastSeen: string | null
}

export type MqttMessage = {
  id: number
  receivedAt: string
  topic: string
  retained: boolean
  validJson: boolean
  payload: unknown
}

type LiveEvent =
  | { type: 'snapshot'; robots: Robot[]; messages: MqttMessage[] }
  | { type: 'message'; message: MqttMessage; robot: Robot | null }

type Feed = {
  connected: boolean
  robots: Record<string, Robot>
  messages: MqttMessage[]
}

type Action = { type: 'connected' | 'disconnected' } | { type: 'event'; event: LiveEvent }

function reducer(feed: Feed, action: Action): Feed {
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
      robots: Object.fromEntries(event.robots.map((robot) => [robot.robotId, robot])),
      messages: event.messages,
    }
  }
  // The server subscribes us before sending the snapshot, so a message can arrive twice.
  const lastId = feed.messages.at(-1)?.id ?? 0
  if (event.message.id <= lastId) return feed

  const robots = event.robot ? { ...feed.robots, [event.robot.robotId]: event.robot } : feed.robots
  return { ...feed, robots, messages: [...feed.messages, event.message].slice(-MAX_MESSAGES) }
}

/** Live robots and MQTT messages from the backend WebSocket, reconnecting on drop. */
export function useLiveFeed(): Feed {
  const [feed, dispatch] = useReducer(reducer, { connected: false, robots: {}, messages: [] })

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

export function missionStatus(robot: Robot): string {
  return robot.state?.actunode?.missionStatus ?? 'UNKNOWN'
}

export function isOnline(robot: Robot): boolean {
  return robot.connection === 'ONLINE'
}
