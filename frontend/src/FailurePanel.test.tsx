import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FailurePanel from './FailurePanel'
import type { FailureEntry, Robot } from './live'
import RobotTable from './RobotTable'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function robot(missionStatus: string, errors: unknown[] = [], injectedFailures?: string[]): Robot {
  return {
    key: 'v2/X/robot_01',
    robotId: 'robot_01',
    connection: 'ONLINE',
    lastSeen: null,
    state: { errors, nodeStates: [], actunode: { missionStatus, injectedFailures } } as unknown as Robot['state'],
  }
}

function stubFetch(response: { ok: boolean; status?: number; body?: unknown } = { ok: true }) {
  const fetchMock = vi.fn().mockResolvedValue({ ok: response.ok, status: response.status ?? 200, json: async () => response.body ?? {} })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sent(fetchMock: ReturnType<typeof vi.fn>) {
  return JSON.parse(fetchMock.mock.calls[0][1].body)
}

function choose(type: string) {
  fireEvent.change(screen.getByLabelText('Failure type'), { target: { value: type } })
}

function setValue(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

const inject = () => fireEvent.click(screen.getByRole('button', { name: 'Inject' }))

describe('FailurePanel', () => {
  it('offers the failure types', () => {
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    const labels = [...(screen.getByLabelText('Failure type') as HTMLSelectElement).options].map((o) => o.text)
    expect(labels).toEqual(['Blocked path', 'Low battery', 'Disconnect', 'Invalid payload', 'Unresponsive'])
  })

  it('sends BLOCKED_PATH with no params', async () => {
    const fetchMock = stubFetch()
    render(<FailurePanel robots={[robot('MOVING')]} failures={[]} />)
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    expect(sent(fetchMock)).toEqual({ robot_id: 'robot_01', failure: 'BLOCKED_PATH', action: 'inject', params: {} })
  })

  it('sends LOW_BATTERY with default and edited level, and clears', async () => {
    const fetchMock = stubFetch()
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    choose('LOW_BATTERY')
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(sent(fetchMock)).toEqual({ robot_id: 'robot_01', failure: 'LOW_BATTERY', action: 'inject', params: { level: 15 } })

    setValue('Battery level', '40')
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).params).toEqual({ level: 40 })

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(JSON.parse(fetchMock.mock.calls[2][1].body).action).toBe('clear')
  })

  it('sends DISCONNECT with defaults and edited params, and has no Clear', async () => {
    const fetchMock = stubFetch()
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    choose('DISCONNECT')
    expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull()
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(sent(fetchMock).params).toEqual({ duration_s: 10, mode: 'broken' })

    setValue('Duration (s)', '30')
    setValue('Mode', 'offline')
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).params).toEqual({ duration_s: 30, mode: 'offline' })
  })

  it('sends INVALID_PAYLOAD with defaults and edited params, and has no Clear', async () => {
    const fetchMock = stubFetch()
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    choose('INVALID_PAYLOAD')
    expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull()
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(sent(fetchMock).params).toEqual({ kind: 'schema', count: 1 })

    setValue('Kind', 'wrong-serial')
    setValue('Count', '3')
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).params).toEqual({ kind: 'wrong-serial', count: 3 })
  })

  it('disables BLOCKED_PATH off a route but not LOW_BATTERY', () => {
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    expect((screen.getByRole('button', { name: 'Inject' }) as HTMLButtonElement).disabled).toBe(true)
    choose('LOW_BATTERY')
    expect((screen.getByRole('button', { name: 'Inject' }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('shows the server detail on a 422', async () => {
    stubFetch({ ok: false, status: 422, body: { detail: 'level must be 1-99' } })
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    choose('LOW_BATTERY')
    setValue('Battery level', '50')
    inject()
    expect(await screen.findByText('level must be 1-99')).toBeTruthy()
  })

  const clearButton = () => screen.getByRole('button', { name: 'Clear' }) as HTMLButtonElement
  const injectButton = () => screen.getByRole('button', { name: 'Inject' }) as HTMLButtonElement

  it('enables low-battery Clear only when LOW_BATTERY is injected', () => {
    const { unmount } = render(<FailurePanel robots={[robot('IDLE', [], [])]} failures={[]} />)
    choose('LOW_BATTERY')
    expect(clearButton().disabled).toBe(true)
    unmount()
    render(<FailurePanel robots={[robot('IDLE', [], ['LOW_BATTERY'])]} failures={[]} />)
    choose('LOW_BATTERY')
    expect(clearButton().disabled).toBe(false)
    expect(screen.getByText('Injected: Low battery')).toBeTruthy()
  })

  it('keeps low-battery Clear enabled when the simulator reports no list', () => {
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    choose('LOW_BATTERY')
    expect(clearButton().disabled).toBe(false)
    expect(screen.queryByText(/^Injected:/)).toBeNull()
  })

  it('blocks Inject on empty or out-of-range numbers', () => {
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    choose('LOW_BATTERY')
    setValue('Battery level', '')
    expect(injectButton().disabled).toBe(true)
    expect(screen.getByText('Enter a number between 1 and 99')).toBeTruthy()
    setValue('Battery level', '150')
    expect(injectButton().disabled).toBe(true)
    setValue('Battery level', '50')
    expect(injectButton().disabled).toBe(false)
    expect(screen.queryByText(/Enter a number/)).toBeNull()
    choose('DISCONNECT')
    setValue('Duration (s)', '301')
    expect(injectButton().disabled).toBe(true)
    expect(screen.getByText('Enter a number between 1 and 300')).toBeTruthy()
    choose('INVALID_PAYLOAD')
    setValue('Count', '0')
    expect(screen.getByText('Enter a number between 1 and 10')).toBeTruthy()
  })

  it('sends UNRESPONSIVE with a duration only, and has no Clear', async () => {
    const fetchMock = stubFetch()
    render(<FailurePanel robots={[robot('IDLE')]} failures={[]} />)
    choose('UNRESPONSIVE')
    expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull()
    expect(screen.queryByLabelText('Mode')).toBeNull()
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    expect(sent(fetchMock).params).toEqual({ duration_s: 10 })

    setValue('Duration (s)', '301')
    expect(injectButton().disabled).toBe(true)
    setValue('Duration (s)', '20')
    inject()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).params).toEqual({ duration_s: 20 })
  })

  it('renders params in the log', () => {
    const failures: FailureEntry[] = [
      { injectionId: 'a', timestamp: '2026-10-12T10:00:00Z', robotId: 'robot_01', failure: 'DISCONNECT', action: 'inject', robotStatus: 'IDLE', params: { duration_s: 30, mode: 'offline' } },
      { injectionId: 'b', timestamp: '2026-10-12T10:00:01Z', robotId: 'robot_01', failure: 'BLOCKED_PATH', action: 'clear', robotStatus: 'BLOCKED' },
    ]
    render(<FailurePanel robots={[robot('IDLE')]} failures={failures} />)
    expect(screen.getByText(/duration_s=30/)).toBeTruthy()
    expect(screen.getByText(/mode=offline/)).toBeTruthy()
  })
})

describe('robot injected failures', () => {
  it('notes injected failures in the robot row', () => {
    render(<RobotTable robots={[robot('IDLE', [], ['LOW_BATTERY'])]} />)
    expect(screen.getByText('injected: Low battery')).toBeTruthy()
  })

  it('shows no note when none are injected', () => {
    render(<RobotTable robots={[robot('IDLE', [], [])]} />)
    expect(screen.queryByText(/injected:/)).toBeNull()
  })
})

describe('robot errors with levels', () => {
  it('shows URGENT and CRITICAL levels', () => {
    const errors = [
      { errorType: 'batteryLow', errorDescription: 'Battery low', errorLevel: 'URGENT' },
      { errorType: 'x', errorDescription: 'Bad thing', errorLevel: 'CRITICAL' },
    ]
    render(<RobotTable robots={[robot('IDLE', errors)]} />)
    expect(screen.getByText(/Battery low.*URGENT/)).toBeTruthy()
    expect(screen.getByText(/Bad thing.*CRITICAL/)).toBeTruthy()
  })
})
