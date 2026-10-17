import type { RecordingStatus, Robot } from './live'

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

export type MapInfo = {
  size: { width: number; height: number }
  zones: { id: string; label: string; x: number; y: number; w: number; h: number }[]
  racks: { x: number; y: number; w: number; h: number }[]
  locations: Record<string, Location>
}

export async function fetchMap(): Promise<MapInfo> {
  const response = await fetch('/api/map')
  if (!response.ok) throw new Error(`Could not load map: ${response.status}`)
  return response.json()
}

export type MissionRequest = {
  robot_id: string
  destination: string
  source?: string
  load_id?: string
  // Where the order goes. Omitted: the server's configured default (ActuNode, VDA 5050 2).
  manufacturer?: string
  vda_version?: '2' | '3'
}

// `warning`: the robot has been seen, but never under the identity the order was sent to.
export type MissionResponse = { order_id: string; topic: string; warning?: string }

export const VIEWER_NOTE = 'Viewers cannot change the lab'

export type SessionStatus = {
  loginRequired: boolean
  loggedIn: boolean
  user?: string | null
  role?: 'operator' | 'viewer' | null
}

export async function fetchSession(): Promise<SessionStatus> {
  const response = await fetch('/api/session')
  if (!response.ok) throw new Error(`Session check failed: ${response.status}`)
  return response.json()
}

export async function login(token: string): Promise<void> {
  await postJson('/api/login', { token })
}

export async function logout(): Promise<void> {
  await postJson('/api/logout', {})
}

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
  const body = await readBody(response)
  if (!response.ok) {
    throw new Error(errorDetail(body) ?? `Request failed: ${response.status}`)
  }
  return body as MissionResponse
}

// Serial only: failure injection targets the simulator's control topic actunode/v1/sim/<serial>/inject, no VDA identity involved.
export async function injectFailure(
  robotId: string,
  failure: string,
  action: 'inject' | 'clear',
  params: Record<string, unknown> = {},
): Promise<void> {
  const response = await fetch('/api/failures', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ robot_id: robotId, failure, action, params }),
  })
  if (!response.ok) {
    const body = await readBody(response)
    throw new Error(errorDetail(body) ?? `Request failed: ${response.status}`)
  }
}

// The person clicked this row, so its identity is the explicit target (D-21).
export async function cancelMission(robot: Robot): Promise<void> {
  await postJson(`/api/missions/${encodeURIComponent(robot.robotId)}/cancel`, {
    manufacturer: robot.manufacturer,
    vda_version: robot.vdaMajor?.replace(/^v/, ''),
  })
}

export type SessionSummary = {
  sessionId: string
  name: string | null
  startedAt: string | null
  endedAt?: string | null
  messageCount: number
  recording: boolean
  complete?: boolean
  // Why recording ended: 'stopped', 'sizeLimit' or 'writeError: ...' (older files: missing).
  reason?: string | null
  sizeBytes: number
}

export async function fetchSessions(): Promise<SessionSummary[]> {
  const response = await fetch('/api/sessions')
  if (!response.ok) throw new Error(`Could not list sessions: ${response.status}`)
  return response.json()
}

export async function fetchRecording(): Promise<RecordingStatus | null> {
  const response = await fetch('/api/recording')
  if (!response.ok) return null
  const body = await response.json()
  return body.recording ?? null
}

export async function deleteSession(sessionId: string): Promise<void> {
  const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  if (!response.ok) {
    const body = await readBody(response)
    throw new Error(errorDetail(body) ?? `Delete failed: ${response.status}`)
  }
}

export type ValidationReport = {
  sessionId: string
  checked: number
  withIssues: number
  byRule: { rule: string; description: string; severity: string; count: number }[]
  issues: { line: number; t: number; topic: string; rule: string; severity: string; message: string }[]
  truncated: boolean
}

export async function validateSession(sessionId: string): Promise<ValidationReport> {
  return (await postJson(`/api/sessions/${encodeURIComponent(sessionId)}/validate`, {})) as ValidationReport
}

export async function uploadSession(file: File, name?: string): Promise<SessionSummary> {
  const query = name?.trim() ? `?name=${encodeURIComponent(name.trim())}` : ''
  const response = await fetch(`/api/sessions/upload${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-ndjson' },
    body: file,
  })
  const body = await readBody(response)
  if (!response.ok) throw new Error(errorDetail(body) ?? `Upload failed: ${response.status}`)
  return body as SessionSummary
}

export type SessionStorage = { keepDays: number; maxTotalMb: number; usedMb: number; sessions: number }

export async function fetchSessionStorage(): Promise<SessionStorage> {
  const response = await fetch('/api/sessions/storage')
  if (!response.ok) throw new Error(`Could not read session storage: ${response.status}`)
  return response.json()
}

export async function startRecording(name: string): Promise<void> {
  await postJson('/api/recording/start', { name: name.trim() || null })
}

export async function stopRecording(): Promise<void> {
  await postJson('/api/recording/stop', {})
}

export async function startReplay(
  sessionId: string,
  speed: number,
  includeCommands: boolean,
  currentTime = false,
): Promise<void> {
  await postJson(`/api/sessions/${encodeURIComponent(sessionId)}/replay`, {
    speed,
    include_commands: includeCommands,
    current_time: currentTime,
  })
}

export async function stopReplay(): Promise<void> {
  await postJson('/api/replay/stop', {})
}

export async function resetValidation(): Promise<void> {
  await postJson('/api/validation/reset', {})
}

async function postJson(url: string, body: unknown): Promise<unknown> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const result = await readBody(response)
  if (!response.ok) throw new Error(errorDetail(result) ?? `Request failed: ${response.status}`)
  return result
}

export type AuditEntry = {
  at: string
  user: string | null
  role: string | null
  client: string
  action: string
  method: string
  path: string
  status: number
  robot?: string
  failure?: string
  destination?: string
  source?: string
  orderId?: string
  sessionId?: string
}

export async function fetchAudit({ limit, user, action }: { limit?: number; user?: string; action?: string } = {}): Promise<AuditEntry[]> {
  const query = new URLSearchParams()
  if (limit !== undefined) query.set('limit', String(limit))
  if (user) query.set('user', user)
  if (action) query.set('action', action)
  const suffix = query.size > 0 ? `?${query}` : ''
  const response = await fetch(`/api/audit${suffix}`)
  if (!response.ok) throw new Error(`Could not load activity: ${response.status}`)
  return (await response.json()).entries
}

// JSON body, or for a failed request with a plain-text body (the viewer 403) that text as `detail`.
async function readBody(response: Response): Promise<{ detail?: unknown }> {
  const copy = typeof response.clone === 'function' ? response.clone() : undefined
  try {
    return (await response.json()) ?? {}
  } catch {
    const plain = ((await copy?.text().catch(() => '')) ?? '').trim().slice(0, 200)
    return !response.ok && plain ? { detail: plain } : {}
  }
}

// FastAPI returns `detail` as a string, or a list of validation errors.
function errorDetail(body: { detail?: unknown }): string | undefined {
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) {
    return body.detail.map((item: { loc?: unknown[]; msg?: string }) => `${item.loc?.at(-1)}: ${item.msg}`).join('; ')
  }
  return undefined
}
