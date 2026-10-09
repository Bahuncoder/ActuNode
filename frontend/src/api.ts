export type Health = {
  status: string
  version: string
  mqtt: {
    host: string
    port: number
    connected: boolean
  }
}

export async function fetchHealth(): Promise<Health> {
  const response = await fetch('/api/health')
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return response.json()
}

export type Location = { x: number; y: number; zone: string }

export type MissionRequest = {
  robot_id: string
  destination: string
  source?: string
  load_id?: string
}

export type MissionResponse = { order_id: string; topic: string }

export async function fetchLocations(): Promise<Record<string, Location>> {
  const response = await fetch('/api/locations')
  if (!response.ok) {
    throw new Error(`Could not load locations: ${response.status}`)
  }
  return response.json()
}

export async function sendMission(mission: MissionRequest): Promise<MissionResponse> {
  const response = await fetch('/api/missions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(mission),
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(errorDetail(body) ?? `Request failed: ${response.status}`)
  }
  return body
}

// FastAPI returns `detail` as a string, or a list of validation errors.
function errorDetail(body: { detail?: unknown }): string | undefined {
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    return body.detail.map((item: { loc?: unknown[]; msg?: string }) => `${item.loc?.at(-1)}: ${item.msg}`).join('; ')
  }
  return undefined
}
