// Plain words for the audit trail's action names and HTTP status codes (names come from backend/app/audit.py, auth.py, sso.py, failures.py).
const LABELS: Record<string, string> = {
  login: 'Signed in',
  'login.failed': 'Sign-in failed',
  'login.refused': 'Sign-in blocked (too many attempts)',
  'login.sso': 'Signed in (workspace sign-on)',
  'login.sso_failed': 'Sign-on refused',
  logout: 'Signed out',
  'sso.revoke': 'Access removed',
  'mission.send': 'Mission sent',
  'mission.cancel': 'Mission cancelled',
  'mission.extend': 'Mission extended',
  'failure.inject': 'Failure injected',
  'failure.clear': 'Failure cleared',
  failure: 'Failure changed',
  'validation.reset': 'Validation reset',
  'session.upload': 'Session uploaded',
  'session.validate': 'Session validated',
  'session.delete': 'Session deleted',
  'replay.start': 'Replay started',
  'replay.stop': 'Replay stopped',
  'recording.start': 'Recording started',
  'recording.stop': 'Recording stopped',
}

export function actionLabel(action: string): string {
  if (LABELS[action]) return LABELS[action]
  if (/^[a-z]+ \//.test(action)) return action // unmapped route, "post /api/..."
  const text = action.replace(/[._]/g, ' ').trim()
  return text ? text[0].toUpperCase() + text.slice(1) : action
}

export type StatusKind = 'ok' | 'refused' | 'error'

export function statusKind(code: number): StatusKind {
  return code >= 500 ? 'error' : code >= 400 ? 'refused' : 'ok'
}

export function statusLabel(code: number): string {
  return { ok: 'OK', refused: 'Refused', error: 'Error' }[statusKind(code)]
}

export const STATUS_BADGE: Record<StatusKind, string> = { ok: 'ok', refused: 'warn', error: 'down' }
