import { useState, type FormEvent } from 'react'
import { sendMission, type Location } from './api'
import type { Robot } from './live'

// Used until the live feed has seen any robots.
const DEFAULT_ROBOTS = ['robot_01', 'robot_02', 'robot_03']

type Result = { ok: boolean; text: string; warning?: string }
type Identity = { manufacturer: string; vdaMajor: string }

// What the server accepts (missions.py). Observed names come from anyone on the broker, so anything
// else is shown but cannot be chosen: it could not be sent as displayed.
const SENDABLE_MANUFACTURER = /^[A-Za-z0-9_.-]{1,64}$/

function sendable(identity: Identity): boolean {
  return SENDABLE_MANUFACTURER.test(identity.manufacturer) && ['v2', 'v3'].includes(identity.vdaMajor)
}

function describe(identity: Identity): string {
  return `${identity.manufacturer} · VDA ${identity.vdaMajor.slice(1)}`
}

// Defaults are the demo scenario: pallet P-1042, Receiving Door 2 -> Storage A17.
export default function MissionSender({
  robots,
  locations,
}: {
  robots: Robot[]
  locations: Record<string, Location>
}) {
  const robotChoices = robots.length > 0 ? robots.map((robot) => robot.robotId) : DEFAULT_ROBOTS
  const [chosenRobot, setChosenRobot] = useState(DEFAULT_ROBOTS[0])
  // What the select shows is what gets sent: fall back to the first listed robot if the chosen one is gone.
  const robotId = robotChoices.includes(chosenRobot) ? chosenRobot : robotChoices[0]
  // The identity itself is kept, not a list position: the list is ordered by recency and can change
  // between choosing and sending. null = server default.
  const [chosenTarget, setChosenTarget] = useState<Identity | null>(null)
  const [source, setSource] = useState('RECEIVING_DOOR_2')
  const [destination, setDestination] = useState('STORAGE_A17')
  const [loadId, setLoadId] = useState('P-1042')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<Result | null>(null)

  // Observed identities are offered so a person picks where the order goes. Nothing is preselected:
  // they come from anonymous traffic and may be spoofed (D-21).
  const identities = robots.find((robot) => robot.robotId === robotId)?.identities ?? []
  const targetIndex = chosenTarget
    ? identities.findIndex((i) => i.manufacturer === chosenTarget.manufacturer && i.vdaMajor === chosenTarget.vdaMajor)
    : -1
  const target = targetIndex >= 0 ? identities[targetIndex] : null
  const defaultSeen = identities.some((i) => i.manufacturer === 'ActuNode' && i.vdaMajor === 'v2')
  const hint =
    identities.length > 0 && !target && !defaultSeen
      ? `${robotId} was seen as ${identities.map(describe).join(', ')}; choose a target to send there`
      : null

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    try {
      const response = await sendMission({
        robot_id: robotId,
        destination,
        source: source || undefined,
        load_id: loadId.trim() || undefined,
        manufacturer: target?.manufacturer,
        vda_version: target ? (target.vdaMajor.slice(1) as '2' | '3') : undefined,
      })
      setResult({ ok: true, text: `Sent ${response.order_id} → ${response.topic}`, warning: response.warning })
    } catch (error) {
      setResult({ ok: false, text: (error as Error).message })
    } finally {
      setSending(false)
    }
  }

  const names = Object.keys(locations)

  return (
    <section className="panel">
      <h2>Mission sender</h2>
      <p>Send a VDA 5050 order. The robot goes IDLE → ACCEPTED → MOVING → COMPLETED.</p>

      <form className="mission-form" onSubmit={submit}>
        <label>
          Robot
          <select
            value={robotId}
            onChange={(e) => {
              setChosenRobot(e.target.value)
              setChosenTarget(null)
            }}
          >
            {robotChoices.map((robot) => (
              <option key={robot}>{robot}</option>
            ))}
          </select>
        </label>
        <label title="Where the order is published. Observed from traffic, so check it: anyone can publish as a robot.">
          Target
          <select
            value={targetIndex >= 0 ? String(targetIndex) : ''}
            onChange={(e) => setChosenTarget(e.target.value === '' ? null : identities[Number(e.target.value)])}
          >
            <option value="">default (ActuNode · VDA 2)</option>
            {identities.map((identity, index) => (
              <option key={index} value={String(index)} disabled={!sendable(identity)}>
                {describe(identity)}
                {sendable(identity) ? '' : ' (invalid name, cannot send)'}
              </option>
            ))}
          </select>
        </label>
        <label>
          From (pick)
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">— none —</option>
            {names.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <label>
          To (drop)
          <select value={destination} onChange={(e) => setDestination(e.target.value)}>
            {names.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <label>
          Load
          <input value={loadId} onChange={(e) => setLoadId(e.target.value)} placeholder="P-1042" />
        </label>
        <button type="submit" disabled={sending || names.length === 0}>
          {sending ? 'Sending…' : 'Send mission'}
        </button>
      </form>

      {hint && <p className="result mono error">{hint}</p>}
      {result && <p className={`result mono ${result.ok ? 'ok' : 'error'}`}>{result.text}</p>}
      {result?.warning && <p className="result mono error">⚠ {result.warning}</p>}
    </section>
  )
}
