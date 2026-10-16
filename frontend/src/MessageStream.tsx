import { memo, useCallback, useState } from 'react'
import { display, get, num, point, type MqttMessage } from './live'

const SHOWN = 200

type Kind = 'state' | 'connection' | 'order' | 'inject' | 'vis' | 'other'

function kindOf(topic: string): Kind {
  const last = topic.split('/').at(-1)
  return last === 'state' || last === 'connection' || last === 'order' || last === 'inject' ? last : last === 'visualization' ? 'vis' : 'other'
}

function robotOf(topic: string): string {
  const parts = topic.split('/')
  return parts.length === 5 ? parts[3] : (parts.at(-2) ?? '')
}

// Highlight robot-reported errors and validator findings alike.
function rowClass(message: MqttMessage): string {
  const issues = message.issues ?? []
  if (issues.some((issue) => issue.severity === 'error')) return 'has-error'
  const errors = get(message.payload, 'errors')
  if (issues.length > 0 || (Array.isArray(errors) && errors.length > 0)) return 'has-warning'
  return ''
}

function summary(message: MqttMessage): string {
  if (!message.validJson) return `invalid JSON: ${display(message.payload).slice(0, 80)}`
  if (typeof message.payload !== 'object' || message.payload === null || Array.isArray(message.payload)) {
    return display(message.payload).slice(0, 100)
  }
  const p = message.payload
  switch (kindOf(message.topic)) {
    case 'state': {
      const pos = point(get(p, 'agvPosition') ?? get(p, 'mobileRobotPosition')) // 2.x or 3.0
      const battery = num(get(get(p, 'batteryState'), 'batteryCharge')) ?? num(get(get(p, 'powerSupply'), 'stateOfCharge'))
      const errors = get(p, 'errors')
      const status = get(get(p, 'actunode'), 'missionStatus')
      const parts = [
        typeof status === 'string' ? status : '',
        pos ? `(${pos.x.toFixed(1)}, ${pos.y.toFixed(1)})` : '',
        battery !== undefined ? `${battery}%` : '',
        Array.isArray(errors) && errors.length
          ? `⚠ ${errors.map((e) => display(get(e, 'errorDescription') ?? get(e, 'errorType'))).join('; ')}`
          : '',
      ]
      return parts.filter(Boolean).join('  ')
    }
    case 'vis': {
      const pos = point(get(p, 'agvPosition') ?? get(p, 'mobileRobotPosition')) // 2.x or 3.0
      const velocity = get(p, 'velocity')
      const vx = num(get(velocity, 'vx'))
      const vy = num(get(velocity, 'vy'))
      const speed = vx === undefined && vy === undefined ? undefined : Math.hypot(vx ?? 0, vy ?? 0)
      return [pos ? `(${pos.x.toFixed(1)}, ${pos.y.toFixed(1)})` : '', speed !== undefined ? `${speed.toFixed(1)} m/s` : ''].filter(Boolean).join('  ')
    }
    case 'connection':
      return display(get(p, 'connectionState'))
    case 'order': {
      const nodes = get(p, 'nodes')
      return `${display(get(p, 'orderId'))} → ${(Array.isArray(nodes) ? nodes : []).map((n) => display(get(n, 'nodeId'))).join(' → ')}`
    }
    case 'inject':
      return `${display(get(p, 'failure'))} ${display(get(p, 'action'))} (${display(get(p, 'injectionId'))})`
    default:
      return display(p).slice(0, 100)
  }
}

function stringify(payload: unknown): string | undefined {
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return undefined
  }
}

function time(iso: string): string {
  const date = new Date(iso)
  return `${date.toLocaleTimeString([], { hour12: false })}.${String(date.getMilliseconds()).padStart(3, '0')}`
}

function MessageStream({ messages }: { messages: MqttMessage[] }) {
  const [filter, setFilter] = useState('')
  const [hideState, setHideState] = useState(false)
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [paused, setPaused] = useState<MqttMessage[] | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const toggle = useCallback((id: number) => setExpanded((current) => (current === id ? null : id)), [])

  const source = paused ?? messages
  const shown = source
    .filter((m) => !hideState || kindOf(m.topic) !== 'state')
    .filter((m) => !filter || m.topic.includes(filter))
    .filter((m) => !onlyIssues || (m.issues ?? []).length > 0)
    .slice(-SHOWN)
    .reverse()

  return (
    <div>
      <div className="stream-controls">
        <input aria-label="Filter by topic" placeholder="Filter topic (e.g. robot_01)" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <label>
          <input type="checkbox" checked={hideState} onChange={(e) => setHideState(e.target.checked)} />
          Hide state messages
        </label>
        <label>
          <input type="checkbox" checked={onlyIssues} onChange={(e) => setOnlyIssues(e.target.checked)} />
          Only validation issues
        </label>
        <button type="button" onClick={() => setPaused(paused ? null : messages)}>
          {paused ? '▶ Resume' : '❚❚ Pause'}
        </button>
        <span className="muted mono">{messages.length} buffered</span>
      </div>

      <ol className="stream">
        {shown.length === 0 && <li className="empty">No messages yet.</li>}
        {shown.map((message) => (
          <MessageRow key={message.id} message={message} open={expanded === message.id} onToggle={toggle} />
        ))}
      </ol>
    </div>
  )
}

// Memoized on the message object, which keeps its identity while it stays in the feed.
const MessageRow = memo(function MessageRow({
  message,
  open,
  onToggle,
}: {
  message: MqttMessage
  open: boolean
  onToggle: (id: number) => void
}) {
  const kind = kindOf(message.topic)
  return (
    <li className={rowClass(message)}>
        <button type="button" className="stream-row" aria-expanded={open} onClick={() => onToggle(message.id)}>
          <span className="mono muted">{time(message.receivedAt)}</span>
          <span className={`kind kind-${kind}`}>{kind}</span>
          <span className="mono">{robotOf(message.topic)}</span>
          <span className="mono stream-summary">{summary(message)}</span>
          {(message.issues ?? []).length > 0 && (
            <span className={`issue-count ${message.issues.some((i) => i.severity === 'error') ? 'error' : 'warning'}`}>
              {message.issues.length} issue{message.issues.length > 1 ? 's' : ''}
            </span>
          )}
        </button>
        {(message.issues ?? []).length > 0 && (
          <ul className="issues">
            {message.issues.map((issue, index) => (
              <li key={index} className={issue.severity}>
                <span className="mono">{issue.rule}</span> {issue.message}
                {issue.path && <span className="mono muted"> at {issue.path}</span>}
              </li>
            ))}
          </ul>
        )}
        {open && (
          <pre className="raw">
            {message.topic}
            {message.retained ? '  (retained)' : ''}
            {'\n\n'}
            {message.validJson ? (stringify(message.payload) ?? display(message.payload)) : display(message.payload)}
          </pre>
        )}
      </li>
  )
})

export default memo(MessageStream)
