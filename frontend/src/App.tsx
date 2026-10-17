import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchHealth,
  fetchLocations,
  fetchMap,
  fetchSession,
  logout,
  type Health,
  type Location,
  type SessionStatus,
} from './api'
import ActivityPanel from './ActivityPanel'
import FailurePanel from './FailurePanel'
import Login from './Login'
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
const RETRY_MS = 3000
const NO_LOCATIONS: Record<string, Location> = {}

/** Fetches once the API is up; a failure is shown and retried on a timer until it works. */
function useRetryingFetch<T>(fetcher: () => Promise<T>, enabled: boolean): { data: T | undefined; error: string | null } {
  const [data, setData] = useState<T | undefined>()
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const loaded = data !== undefined
  useEffect(() => {
    if (loaded || !enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    fetcher()
      .then((result) => {
        if (cancelled) return
        setData(result)
        setError(null)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'request failed')
        timer = setTimeout(() => setAttempt((count) => count + 1), RETRY_MS)
      })
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
    // fetcher is a module-level function; only the flags and the retry counter restart the effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, loaded, attempt])
  return { data, error }
}

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

/** The lab itself; mounted only once the session allows it, so the live feed never opens without one. */
function Lab({
  onLogout,
  onSessionEnded,
  user,
  role,
}: {
  onLogout?: () => void
  onSessionEnded: () => void
  user?: string | null
  role?: string | null
}) {
  const readOnly = role === 'viewer'
  const [health, setHealth] = useState<Health | null>(null)
  const [apiUp, setApiUp] = useState<boolean | null>(null)
  const feed = useLiveFeed(onSessionEnded)

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

  // The map and mission form both need locations; until the map loads the map draws its built-in floor.
  const locationsFetch = useRetryingFetch(fetchLocations, apiUp === true)
  const mapFetch = useRetryingFetch(fetchMap, apiUp === true)
  const locations = locationsFetch.data ?? NO_LOCATIONS
  const map = mapFetch.data
  const loadError = locationsFetch.error ?? mapFetch.error

  const mqttUp = apiUp === null ? null : (health?.mqtt?.connected ?? false)
  const robots = useMemo(
    () => Object.values(feed.robots).sort((a, b) => a.robotId.localeCompare(b.robotId) || a.key.localeCompare(b.key)),
    [feed.robots],
  )

  return (
    <div className="app">
      <PanelBoundary title="Header" resetKey={health}>
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
          {health && typeof health.version === 'string' && <span className="pill mono">v{health.version}</span>}
          {onLogout && user && (
            <span className="pill" aria-label={`Logged in as ${user}, ${role ?? 'unknown role'}`}>
              {user} ({role ?? '?'})
            </span>
          )}
          {readOnly && <span className="pill" title="Viewers cannot change the lab">View only</span>}
          {onLogout && (
            <button type="button" className="pill logout" onClick={onLogout}>
              Log out
            </button>
          )}
        </div>
      </header>
      </PanelBoundary>

      {loadError && (
        <p className="result error" role="alert">
          Could not load the map or locations ({loadError}); retrying.
        </p>
      )}

      <PanelBoundary title="Replay" resetKey={feed.replay}>
        <ReplayBanner replay={feed.replay} readOnly={readOnly} />
      </PanelBoundary>

      <main className="grid">
        <PanelBoundary title="Warehouse" resetKey={feed.robots}>
          <section className="panel panel-wide">
            <h2>Warehouse</h2>
            <WarehouseMap robots={robots} locations={locations} proximity={feed.proximity} map={map} />
          </section>
        </PanelBoundary>

        <PanelBoundary title="Robots" resetKey={feed.robots}>
          <section className="panel panel-wide">
            <h2>Robots</h2>
            <RobotTable robots={robots} readOnly={readOnly} />
          </section>
        </PanelBoundary>

        <PanelBoundary title="Missions and failures" resetKey={feed.robots}>
          <div className="split">
            <MissionSender robots={robots} locations={locations} readOnly={readOnly} />
            <FailurePanel robots={robots} failures={feed.failures} readOnly={readOnly} />
          </div>
        </PanelBoundary>

        <PanelBoundary title="Sessions" resetKey={feed.recording}>
          <RecorderPanel recording={feed.recording} recordingStopped={feed.recordingStopped} replay={feed.replay} sessionsVersion={feed.sessionsVersion} readOnly={readOnly} />
        </PanelBoundary>

        <PanelBoundary title="Activity" resetKey={feed.sessionsVersion}>
          <ActivityPanel />
        </PanelBoundary>

        <PanelBoundary title="Validation" resetKey={feed.validation}>
          <ValidationPanel validation={feed.validation} readOnly={readOnly} />
        </PanelBoundary>

        <PanelBoundary title="Message stream" resetKey={feed.messages}>
          <section className="panel panel-wide">
            <h2>Message stream</h2>
            <MessageStream messages={feed.messages} />
          </section>
        </PanelBoundary>

      </main>
    </div>
  )
}

/** Shows the login screen when the backend requires one (sharing the lab, D-25), otherwise the lab. */
export default function App() {
  // 'checking' until the first answer: nothing that needs a session may start before it (issue 6).
  const [session, setSession] = useState<SessionStatus | 'checking' | 'unreachable'>('checking')
  const [logoutError, setLogoutError] = useState<string | null>(null)
  // Whether the backend ever said a login is required: while it is unreachable, stay where the person is.
  const [loginRequired, setLoginRequired] = useState(false)

  const latest = useRef(0) // an older answer must not overwrite a newer one
  const refresh = useCallback(() => {
    const sequence = ++latest.current
    const apply = (next: SessionStatus | 'unreachable') => {
      if (sequence < latest.current) return
      if (next !== 'unreachable') setLoginRequired(next.loginRequired)
      setSession(next)
    }
    fetchSession()
      .then(apply)
      .catch(() => apply('unreachable')) // the lab shows that itself
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, POLL_MS) // also notices an expired session
    return () => clearInterval(timer)
  }, [refresh])

  if (session === 'checking') {
    return <p className="muted connecting">Connecting to ActuNode…</p>
  }
  if (session === 'unreachable' ? loginRequired : session.loginRequired && !session.loggedIn) {
    return <Login onLoggedIn={refresh} />
  }
  const onLogout =
    session !== 'unreachable' && session.loginRequired
      ? () => {
          setLogoutError(null)
          logout()
            .catch((err: unknown) => setLogoutError(`Log out failed: ${err instanceof Error ? err.message : 'request failed'}`))
            .finally(refresh)
        }
      : undefined
  return (
    <>
      {logoutError && (
        <p className="result error" role="alert">
          {logoutError}
        </p>
      )}
      <Lab
        onLogout={onLogout}
        onSessionEnded={refresh}
        user={session !== 'unreachable' ? session.user : undefined}
        role={session !== 'unreachable' ? session.role : undefined}
      />
    </>
  )
}
