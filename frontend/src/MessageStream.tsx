import { useState } from 'react'
import type { MqttMessage } from './live'

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

function hasErrors(message: MqttMessage): boolean {
  const payload = message.payload as { errors?: unknown[] }
  return !message.validJson || (Array.isArray(payload?.errors) && payload.errors.length > 0)
}

function summary(message: MqttMessage): string {
  if (!message.validJson) return `invalid JSON: ${String(message.payload).slice(0, 80)}`
  const p = message.payload as Record<string, any>
  switch (kindOf(message.topic)) {
    case 'state': {
      const pos = p.agvPosition
      const parts = [
        p.actunode?.missionStatus,
        pos ? `(${pos.x.toFixed(1)}, ${pos.y.toFixed(1)})` : '',
        p.batteryState ? `${p.batteryState.batteryCharge}%` : '',
        p.errors?.length ? `⚠ ${p.errors.map((e: any) => e.errorDescription ?? e.errorType).join('; ')}` : '',
      ]
      return parts.filter(Boolean).join('  ')
    }
    case 'connection':
      return p.connectionState
    case 'order':
      return `${p.orderId} → ${(p.nodes ?? []).map((n: any) => n.nodeId).join(' → ')}`
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
  const [paused, setPaused] = useState<MqttMessage[] | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)

  const source = paused ?? messages
  const shown = source
    .filter((m) => !hideState || kindOf(m.topic) !== 'state')
    .filter((m) => !filter || m.topic.includes(filter))
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
            <li key={message.id} className={hasErrors(message) ? 'has-error' : ''}>
              <button type="button" className="stream-row" onClick={() => setExpanded(open ? null : message.id)}>
                <span className="mono muted">{time(message.receivedAt)}</span>
                <span className={`kind kind-${kind}`}>{kind}</span>
                <span className="mono">{robotOf(message.topic)}</span>
                <span className="mono stream-summary">{summary(message)}</span>
              </button>
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
