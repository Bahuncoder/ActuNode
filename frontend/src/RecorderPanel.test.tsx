import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import type { RecordingStatus } from './live'
import RecorderPanel from './RecorderPanel'

vi.mock('./api')

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

function status(sessionId: string, messageCount: number): RecordingStatus {
  return { sessionId, name: null, startedAt: '2026-10-10T12:00:00Z', messageCount, duration: 0, sizeBytes: messageCount * 100 }
}

const storage = { keepDays: 30, maxTotalMb: 2000, usedMb: 12.3, sessions: 1 }

function summary(sessionId: string, recording = false): api.SessionSummary {
  return { sessionId, name: null, startedAt: '2026-10-10T12:00:00Z', endedAt: '2026-10-10T12:01:00Z', messageCount: 5, recording, sizeBytes: 500 }
}

function panel(recording: RecordingStatus | null) {
  return <RecorderPanel recording={recording} recordingStopped={null} replay={null} />
}

describe('recorder counters (Issue 22)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(api.fetchSessions).mockResolvedValue([])
    vi.mocked(api.fetchSessionStorage).mockResolvedValue(storage)
  })

  it('starts from the new recording when it was started elsewhere', async () => {
    vi.mocked(api.fetchRecording).mockResolvedValue(status('old', 500))
    const { rerender } = render(panel(status('old', 0)))
    await act(() => vi.advanceTimersByTimeAsync(1000))
    expect(screen.getByText(/500 messages/)).toBeTruthy()

    // another tab starts a new recording; the next poll has not answered yet
    vi.mocked(api.fetchRecording).mockReturnValue(new Promise(() => {}))
    rerender(panel(status('new', 3)))
    expect(screen.getByText(/3 messages/)).toBeTruthy()
    expect(screen.queryByText(/500 messages/)).toBeNull()
  })

  it('ignores a late response for the old session', async () => {
    let resolveOld: (value: RecordingStatus) => void = () => {}
    vi.mocked(api.fetchRecording).mockReturnValueOnce(new Promise((resolve) => (resolveOld = resolve)))
    const { rerender } = render(panel(status('old', 0)))
    await act(() => vi.advanceTimersByTimeAsync(1000))

    vi.mocked(api.fetchRecording).mockReturnValue(new Promise(() => {}))
    rerender(panel(status('new', 3)))
    await act(async () => resolveOld(status('old', 999)))
    expect(screen.getByText(/3 messages/)).toBeTruthy()
    expect(screen.queryByText(/999 messages/)).toBeNull()
  })
})

const report = {
  sessionId: 's1',
  checked: 120,
  withIssues: 12,
  byRule: [{ rule: 'R1', description: 'bad', severity: 'error', count: 12 }],
  issues: Array.from({ length: 12 }, (_, i) => ({ line: i + 1, t: 1.5, topic: `topic/${i + 1}`, rule: 'R1', severity: 'error', message: `msg ${i + 1}` })),
  truncated: false,
}

describe('sessions: validate, upload, storage (D-40, D-41)', () => {
  beforeEach(() => {
    vi.mocked(api.fetchSessions).mockResolvedValue([summary('s1')])
    vi.mocked(api.fetchSessionStorage).mockResolvedValue(storage)
  })

  it('shows validation counts, rules and the first 10 issues', async () => {
    vi.mocked(api.validateSession).mockResolvedValue(report)
    render(panel(null))
    fireEvent.click(await screen.findByRole('button', { name: 'Validate session s1' }))
    expect(await screen.findByText('120 messages checked, 12 with issues')).toBeTruthy()
    expect(screen.getByText('R1')).toBeTruthy()
    expect(screen.getByText(/msg 10/)).toBeTruthy()
    expect(screen.queryByText(/msg 11/)).toBeNull()
    expect(screen.getByText('showing first 10 of 12 listed issues')).toBeTruthy()
    expect(screen.queryByText(/the report lists the first 100 issues/)).toBeNull()
    expect(screen.getByText('error', { selector: '.result li:nth-of-type(1) .badge' }).className).toContain('down')
  })

  it('notes truncation', async () => {
    vi.mocked(api.validateSession).mockResolvedValue({ ...report, truncated: true })
    render(panel(null))
    fireEvent.click(await screen.findByRole('button', { name: 'Validate session s1' }))
    expect(await screen.findByText(/the report lists the first 100 issues/)).toBeTruthy()
  })

  it('does not warn about duplicate keys when one message raises the same rule twice', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const twice = { ...report, issues: [report.issues[0], { ...report.issues[0] }], withIssues: 1 }
    vi.mocked(api.validateSession).mockResolvedValue(twice)
    render(panel(null))
    fireEvent.click(await screen.findByRole('button', { name: 'Validate session s1' }))
    await screen.findByText('120 messages checked, 1 with issues')
    expect(spy.mock.calls.some((call) => String(call[0]).includes('same key'))).toBe(false)
    spy.mockRestore()
  })

  it('uses the warn badge for warnings', async () => {
    const warn = { ...report, byRule: [{ rule: 'W1', description: 'd', severity: 'warning', count: 1 }] }
    vi.mocked(api.validateSession).mockResolvedValue(warn)
    render(panel(null))
    fireEvent.click(await screen.findByRole('button', { name: 'Validate session s1' }))
    expect((await screen.findByText('warning')).className).toContain('warn')
  })

  it('renders a session list with object-valued fields without throwing', async () => {
    const bad = { sessionId: 'evil', name: { a: 1 }, startedAt: { b: 2 }, endedAt: { c: 3 }, reason: { d: 4 }, messageCount: { e: 5 }, sizeBytes: { f: 6 }, recording: false, complete: false }
    vi.mocked(api.fetchSessions).mockResolvedValue([bad as unknown as api.SessionSummary, summary('s1')])
    render(panel(null))
    expect(await screen.findByText('evil')).toBeTruthy()
    expect(screen.getByText('s1')).toBeTruthy()
  })

  it('refetches the list and storage when the server says the sessions changed, and drops stale reports', async () => {
    vi.mocked(api.validateSession).mockResolvedValue(report)
    const view = (version: number) => <RecorderPanel recording={null} recordingStopped={null} replay={null} sessionsVersion={version} />
    const { rerender } = render(view(0))
    fireEvent.click(await screen.findByRole('button', { name: 'Validate session s1' }))
    await screen.findByText('120 messages checked, 12 with issues')
    const before = vi.mocked(api.fetchSessions).mock.calls.length
    vi.mocked(api.fetchSessions).mockResolvedValue([summary('s2')])
    rerender(view(1))
    expect(await screen.findByText('s2')).toBeTruthy()
    expect(vi.mocked(api.fetchSessions).mock.calls.length).toBeGreaterThan(before)
    expect(vi.mocked(api.fetchSessionStorage).mock.calls.length).toBeGreaterThan(1)
    expect(screen.queryByText('120 messages checked, 12 with issues')).toBeNull()
    vi.mocked(api.fetchSessions).mockResolvedValue([summary('s1')])
    rerender(view(2))
    await screen.findByText('s1')
    expect(screen.queryByText('120 messages checked, 12 with issues')).toBeNull()
  })

  it('shows the error when validation is refused', async () => {
    vi.mocked(api.validateSession).mockRejectedValue(new Error('Session is still recording'))
    render(panel(null))
    fireEvent.click(await screen.findByRole('button', { name: 'Validate session s1' }))
    expect(await screen.findByText('Session is still recording')).toBeTruthy()
  })

  it('disables validate while that session records', async () => {
    vi.mocked(api.fetchSessions).mockResolvedValue([summary('s1', true)])
    render(panel(status('s1', 1)))
    const button = (await screen.findByRole('button', { name: 'Validate session s1' })) as HTMLButtonElement
    expect(button.disabled).toBe(true)
  })

  it('uploads the file with the name and refreshes the list', async () => {
    vi.mocked(api.uploadSession).mockResolvedValue({ ...summary('up1'), name: 'mine' })
    render(panel(null))
    await screen.findByText('s1')
    const file = new File(['{}'], 'x.jsonl', { type: 'application/x-ndjson' })
    fireEvent.change(screen.getByLabelText('Upload name'), { target: { value: 'mine' } })
    fireEvent.change(screen.getByLabelText('Upload session file'), { target: { files: [file] } })
    expect(await screen.findByText('Uploaded mine')).toBeTruthy()
    expect(api.uploadSession).toHaveBeenCalledWith(file, 'mine')
    await waitFor(() => expect(vi.mocked(api.fetchSessions).mock.calls.length).toBeGreaterThan(1))
  })

  it('shows the server detail when the upload is rejected', async () => {
    vi.mocked(api.uploadSession).mockRejectedValue(new Error('line 3: not valid JSON'))
    render(panel(null))
    const file = new File(['x'], 'x.jsonl')
    fireEvent.change(await screen.findByLabelText('Upload session file'), { target: { files: [file] } })
    expect(await screen.findByText('line 3: not valid JSON')).toBeTruthy()
  })

  it('shows the storage line', async () => {
    render(panel(null))
    expect(await screen.findByText('Storage: 12.3 MB of 2000 MB · keeps 30 days')).toBeTruthy()
  })

  it('shows unlimited storage wording for 0/0', async () => {
    vi.mocked(api.fetchSessionStorage).mockResolvedValue({ keepDays: 0, maxTotalMb: 0, usedMb: 1, sessions: 1 })
    render(panel(null))
    expect(await screen.findByText('Storage: 1.0 MB · no size limit · kept forever')).toBeTruthy()
  })
})
