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

export async function injectFailure(robotId: string, action: 'inject' | 'clear'): Promise<void> {
  const response = await fetch('/api/failures', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId, failure: 'BLOCKED_PATH', action }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(errorDetail(body) ?? `Request failed: ${response.status}`)
  }
}

export type SessionSummary = {
  sessionId: string
  name: string | null
  startedAt: string | null
  endedAt?: string | null
  messageCount: number
  recording: boolean
  complete?: boolean
  sizeBytes: number
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const response = await fetch('/api/sessions')
  if (!response.ok) throw new Error(`Could not list sessions: ${response.status}`)
  return response.json()
}

export async function fetchRecordingCount(): Promise<number | null> {
  const response = await fetch('/api/recording')
  if (!response.ok) return null
  const body = await response.json()
  return body.recording?.messageCount ?? null
}

export async function startRecording(name: string): Promise<void> {
  await postJson('/api/recording/start', { name: name.trim() || null })
}

export async function stopRecording(): Promise<void> {
  await postJson('/api/recording/stop', {})
}

export async function startReplay(sessionId: string, speed: number, includeCommands: boolean): Promise<void> {
  await postJson(`/api/sessions/${encodeURIComponent(sessionId)}/replay`, { speed, include_commands: includeCommands })
}

export async function stopReplay(): Promise<void> {
  await postJson('/api/replay/stop', {})
}

async function postJson(url: string, body: unknown): Promise<unknown> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const result = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(errorDetail(result) ?? `Request failed: ${response.status}`)
  return result
}

// FastAPI returns `detail` as a string, or a list of validation errors.
function errorDetail(body: { detail?: unknown }): string | undefined {
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    return body.detail.map((item: { loc?: unknown[]; msg?: string }) => `${item.loc?.at(-1)}: ${item.msg}`).join('; ')
  }
  return undefined
}
