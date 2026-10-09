import { useEffect, useState } from 'react'
import { fetchHealth, type Health } from './api'

const POLL_MS = 3000

// Modules from the first-week build plan; each panel is filled in on its day.
const MODULES = [
  { title: 'Robots', text: 'Simulated AMRs with pose, battery and mission state.', day: 'Day 2' },
  { title: 'Mission sender', text: 'Send transport orders: IDLE → ACCEPTED → MOVING → COMPLETED.', day: 'Day 3' },
  { title: 'Map + message stream', text: 'Warehouse map and raw MQTT messages as they arrive.', day: 'Day 4' },
  { title: 'Failure injection', text: 'Force BLOCKED_PATH and watch the system react.', day: 'Day 5' },
  { title: 'Record', text: 'Capture every message to a JSONL session file.', day: 'Day 6' },
  { title: 'Replay', text: 'Replay a session to reproduce an incident.', day: 'Day 7' },
]

function StatusPill({ label, ok }: { label: string; ok: boolean | null }) {
  const state = ok === null ? '' : ok ? 'ok' : 'down'
  const text = ok === null ? 'checking…' : ok ? 'connected' : 'offline'
  return (
    <span className="pill">
      <span className={`dot ${state}`} />
      {label}: {text}
    </span>
  )
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [apiUp, setApiUp] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const result = await fetchHealth()
        if (!cancelled) {
          setHealth(result)
          setApiUp(true)
        }
      } catch {
        if (!cancelled) {
          setHealth(null)
          setApiUp(false)
        }
      }
    }

    poll()
    const timer = setInterval(poll, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  const mqttUp = apiUp === null ? null : (health?.mqtt.connected ?? false)

  return (
    <div className="app">
      <header className="header">
        <img src="/logo.png" alt="" />
        <div>
          <h1>ActuNode Lab</h1>
          <p>Simulate, test, debug and replay AMR integrations.</p>
        </div>
        <div className="status-bar">
          <StatusPill label="API" ok={apiUp} />
          <StatusPill label="MQTT" ok={mqttUp} />
          {health && <span className="pill mono">v{health.version}</span>}
        </div>
      </header>

      <main className="grid">
        {MODULES.map((module) => (
          <section className="panel" key={module.title}>
            <h2>{module.title}</h2>
            <p>{module.text}</p>
            <span className="tag mono">{module.day}</span>
          </section>
        ))}
      </main>
    </div>
  )
}
