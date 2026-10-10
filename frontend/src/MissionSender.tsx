import { useState, type FormEvent } from 'react'
import { sendMission, type Location } from './api'
import type { Robot } from './live'

// Used until the live feed has seen any robots.
const DEFAULT_ROBOTS = ['robot_01', 'robot_02', 'robot_03']

type Result = { ok: boolean; text: string; warning?: string }

// Value of the Target select: '' = server default, otherwise "<manufacturer>|<v2|v3>".
function identityKey(identity: { manufacturer: string; vdaMajor: string }): string {
  return `${identity.manufacturer}|${identity.vdaMajor}`
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
  const [chosenTarget, setChosenTarget] = useState<string | null>(null)
  const [source, setSource] = useState('RECEIVING_DOOR_2')
  const [destination, setDestination] = useState('STORAGE_A17')
  const [loadId, setLoadId] = useState('P-1042')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<Result | null>(null)

  // Observed identities are shown so a person picks where the order goes; the server never guesses (D-21).
  // Exactly one observed identity is preselected; with several, the person must choose.
  const identities = robots.find((robot) => robot.robotId === robotId)?.identities ?? []
  const preselected = identities.length === 1 ? identityKey(identities[0]) : ''
  const target = chosenTarget ?? preselected
  const ambiguous = identities.length > 1 && target === ''

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    try {
      const [manufacturer, major] = target ? target.split('|') : [undefined, undefined]
      const response = await sendMission({
        robot_id: robotId,
        destination,
        source: source || undefined,
        load_id: loadId.trim() || undefined,
        manufacturer,
        vda_version: major ? (major.slice(1) as '2' | '3') : undefined,
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
          <select value={target} onChange={(e) => setChosenTarget(e.target.value)}>
            <option value="">{identities.length > 1 ? '— choose —' : 'default (ActuNode v2)'}</option>
            {identities.map((identity) => (
              <option key={identityKey(identity)} value={identityKey(identity)}>
                {identity.manufacturer} · VDA {identity.vdaMajor.slice(1)}
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
        <button type="submit" disabled={sending || names.length === 0 || ambiguous}>
          {sending ? 'Sending…' : 'Send mission'}
        </button>
      </form>

      {ambiguous && (
        <p className="result mono error">{robotId} was seen under several identities; choose the target.</p>
      )}
      {result && <p className={`result mono ${result.ok ? 'ok' : 'error'}`}>{result.text}</p>}
      {result?.warning && <p className="result mono error">⚠ {result.warning}</p>}
    </section>
  )
}
