import { act, cleanup, render, screen } from '@testing-library/react'
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

function panel(recording: RecordingStatus | null) {
  return <RecorderPanel recording={recording} recordingStopped={null} replay={null} />
}

describe('recorder counters (Issue 22)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(api.fetchSessions).mockResolvedValue([])
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
