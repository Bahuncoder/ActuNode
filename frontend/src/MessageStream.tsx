import { useState } from 'react'
import { num, point, type MqttMessage } from './live'

const SHOWN = 200

type Kind = 'state' | 'connection' | 'order' | 'inject' | 'other'

function kindOf(topic: string): Kind {
  const last = topic.split('/').at(-1)
  return last === 'state' || last === 'connection' || last === 'order' || last === 'inject' ? last : 'other'
}

function robotOf(topic: string): string {
  const parts = topic.split('/')
  return parts.length === 5 ? parts[3] : (parts.at(-2) ?? '')
}

// Highlight robot-reported errors and validator findings alike.
function rowClass(message: MqttMessage): string {
  const issues = message.issues ?? []
  if (issues.some((issue) => issue.severity === 'error')) return 'has-error'
  const payload = message.payload as { errors?: unknown[] }
  if (issues.length > 0 || (Array.isArray(payload?.errors) && payload.errors.length > 0)) return 'has-warning'
  return ''
}

function summary(message: MqttMessage): string {
  if (!message.validJson) return `invalid JSON: ${String(message.payload).slice(0, 80)}`
  if (typeof message.payload !== 'object' || message.payload === null || Array.isArray(message.payload)) {
    return (JSON.stringify(message.payload) ?? '').slice(0, 100)
  }
  const p = message.payload as Record<string, any>
  switch (kindOf(message.topic)) {
    case 'state': {
      const pos = point(p.agvPosition ?? p.mobileRobotPosition) // 2.x or 3.0
      const battery = num(p.batteryState?.batteryCharge) ?? num(p.powerSupply?.stateOfCharge)
      const errors = Array.isArray(p.errors) ? p.errors : []
      const parts = [
        typeof p.actunode?.missionStatus === 'string' ? p.actunode.missionStatus : '',
        pos ? `(${pos.x.toFixed(1)}, ${pos.y.toFixed(1)})` : '',
        battery !== undefined ? `${battery}%` : '',
        errors.length ? `⚠ ${errors.map((e: any) => e?.errorDescription ?? e?.errorType).join('; ')}` : '',
      ]
      return parts.filter(Boolean).join('  ')
    }
    case 'connection':
      return String(p.connectionState)
    case 'order':
      return `${p.orderId} → ${(Array.isArray(p.nodes) ? p.nodes : []).map((n: any) => n?.nodeId).join(' → ')}`
    case 'inject':
      return `${p.failure} ${p.action} (${p.injectionId})`
    default:
      return JSON.stringify(p).slice(0, 100)
  }
}

function time(iso: string): string {
  const date = new Date(iso)
  return `${date.toLocaleTimeString([], { hour12: false })}.${String(date.getMilliseconds()).padStart(3, '0')}`
}

export default function MessageStream({ messages }: { messages: MqttMessage[] }) {
  const [filter, setFilter] = useState('')
  const [hideState, setHideState] = useState(false)
  const [onlyIssues, setOnlyIssues] = useState(false)
  const [paused, setPaused] = useState<MqttMessage[] | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)

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
        <input placeholder="Filter topic (e.g. robot_01)" value={filter} onChange={(e) => setFilter(e.target.value)} />
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
        {shown.map((message) => {
          const kind = kindOf(message.topic)
          const open = expanded === message.id
          return (
            <li key={message.id} className={rowClass(message)}>
              <button type="button" className="stream-row" onClick={() => setExpanded(open ? null : message.id)}>
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
                  {message.validJson ? JSON.stringify(message.payload, null, 2) : String(message.payload)}
                </pre>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
