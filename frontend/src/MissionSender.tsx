import { useEffect, useState, type FormEvent } from 'react'
import { fetchLocations, sendMission, type Location } from './api'

const ROBOTS = ['robot_01', 'robot_02', 'robot_03']

type Result = { ok: true; text: string } | { ok: false; text: string }

// Defaults are the demo scenario: pallet P-1042, Receiving Door 2 -> Storage A17.
export default function MissionSender() {
  const [locations, setLocations] = useState<Record<string, Location>>({})
  const [robotId, setRobotId] = useState(ROBOTS[0])
  const [source, setSource] = useState('RECEIVING_DOOR_2')
  const [destination, setDestination] = useState('STORAGE_A17')
  const [loadId, setLoadId] = useState('P-1042')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<Result | null>(null)

  useEffect(() => {
    fetchLocations()
      .then(setLocations)
      .catch((error: Error) => setResult({ ok: false, text: error.message }))
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSending(true)
    try {
      const response = await sendMission({
        robot_id: robotId,
        destination,
        source: source || undefined,
        load_id: loadId.trim() || undefined,
      })
      setResult({ ok: true, text: `Sent ${response.order_id} → ${response.topic}` })
    } catch (error) {
      setResult({ ok: false, text: (error as Error).message })
    } finally {
      setSending(false)
    }
  }

  const names = Object.keys(locations)

  return (
    <section className="panel panel-wide">
      <h2>Mission sender</h2>
      <p>Send a VDA 5050 order. The robot goes IDLE → ACCEPTED → MOVING → COMPLETED.</p>

      <form className="mission-form" onSubmit={submit}>
        <label>
          Robot
          <select value={robotId} onChange={(e) => setRobotId(e.target.value)}>
            {ROBOTS.map((robot) => (
              <option key={robot}>{robot}</option>
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

      {result && <p className={`result mono ${result.ok ? 'ok' : 'error'}`}>{result.text}</p>}
    </section>
  )
}
