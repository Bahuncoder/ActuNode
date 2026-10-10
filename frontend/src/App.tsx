import { useEffect, useState } from 'react'
import { fetchHealth, fetchLocations, type Health, type Location } from './api'
import FailurePanel from './FailurePanel'
import { useLiveFeed } from './live'
import MessageStream from './MessageStream'
import MissionSender from './MissionSender'
import PanelBoundary from './PanelBoundary'
import RecorderPanel from './RecorderPanel'
import ReplayBanner from './ReplayBanner'
import ValidationPanel from './ValidationPanel'
import RobotTable from './RobotTable'
import WarehouseMap from './WarehouseMap'

const POLL_MS = 3000

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
  const [locations, setLocations] = useState<Record<string, Location>>({})
  const feed = useLiveFeed()

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

  useEffect(() => {
    // Retry until the API is up; the map and mission form both need locations.
    if (Object.keys(locations).length > 0 || !apiUp) return
    fetchLocations().then(setLocations).catch(() => {})
  }, [apiUp, locations])

  const mqttUp = apiUp === null ? null : (health?.mqtt.connected ?? false)
  const robots = Object.values(feed.robots).sort((a, b) => a.robotId.localeCompare(b.robotId))

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
          <StatusPill label="Live" ok={apiUp === null ? null : feed.connected} />
          {health && <span className="pill mono">v{health.version}</span>}
        </div>
      </header>

      <ReplayBanner replay={feed.replay} />

      <main className="grid">
        <PanelBoundary title="Warehouse">
          <section className="panel panel-wide">
            <h2>Warehouse</h2>
            <WarehouseMap robots={robots} locations={locations} />
          </section>
        </PanelBoundary>

        <PanelBoundary title="Robots">
          <section className="panel panel-wide">
            <h2>Robots</h2>
            <RobotTable robots={robots} />
          </section>
        </PanelBoundary>

        <PanelBoundary title="Missions and failures">
          <div className="split">
            <MissionSender robots={robots.map((robot) => robot.robotId)} locations={locations} />
            <FailurePanel robots={robots} failures={feed.failures} />
          </div>
        </PanelBoundary>

        <PanelBoundary title="Sessions">
          <RecorderPanel recording={feed.recording} replay={feed.replay} />
        </PanelBoundary>

        <PanelBoundary title="Validation">
          <ValidationPanel validation={feed.validation} />
        </PanelBoundary>

        <PanelBoundary title="Message stream">
          <section className="panel panel-wide">
            <h2>Message stream</h2>
            <MessageStream messages={feed.messages} />
          </section>
        </PanelBoundary>

      </main>
    </div>
  )
}
