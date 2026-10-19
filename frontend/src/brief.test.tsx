// The design brief's interaction requirements and copy (docs/product/UI_UX_DESIGN_BRIEF.md), package I batch 2.
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import FailurePanel from './FailurePanel'
import type { RecordingStatus, ReplayStatus, Robot } from './live'
import MissionSender from './MissionSender'
import RecorderPanel from './RecorderPanel'
import ReplayBanner from './ReplayBanner'
import RobotTable from './RobotTable'

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof api>()),
  fetchSessions: vi.fn(),
  fetchSessionStorage: vi.fn(),
  fetchRecording: vi.fn(),
  stopReplay: vi.fn(),
}))

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const robot = {
  key: 'v2/ActuNode/r1', robotId: 'r1', vdaMajor: 'v2', manufacturer: 'ActuNode', connection: 'ONLINE', lastSeen: null,
  state: { errors: [], nodeStates: [], actunode: { missionStatus: 'MOVING' } },
} as unknown as Robot

function sessionsEmpty() {
  vi.mocked(api.fetchSessions).mockResolvedValue([])
  vi.mocked(api.fetchSessionStorage).mockResolvedValue({ keepDays: 0, maxTotalMb: 0, usedMb: 0, sessions: 0 })
}

describe('copy', () => {
  it('says no robot traffic was received, not that there are no robots', () => {
    render(<RobotTable robots={[]} />)
    expect(screen.getByText(/No robot traffic received\. Start the simulator or connect a robot\./)).toBeTruthy()
  })

  it('gives positions in metres', () => {
    render(<RobotTable robots={[robot]} />)
    expect(screen.getByRole('columnheader', { name: 'Position (m)' })).toBeTruthy()
  })

  it('says an order was published and the robot state is awaited, not that the robot accepted it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 202, json: async () => ({ order_id: 'order-7', topic: 'uagv/v2/ActuNode/r1/order' }) }))
    render(<MissionSender robots={[robot]} locations={{ A: { x: 0, y: 0 }, B: { x: 1, y: 1 } } as never} />)
    fireEvent.click(screen.getByRole('button', { name: 'Send mission' }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/^Order published: order-7\. Waiting for robot state\./))
  })

  it('says validation is not a safety verdict', () => {
    expect(readFileSync(`${process.cwd()}/src/ValidationPanel.tsx`, 'utf8')).toMatch(/is not a safety verdict/)
  })

  it('says when the live feed is lost after it was up', () => {
    expect(readFileSync(`${process.cwd()}/src/App.tsx`, 'utf8')).toMatch(/liveSeen && !feed\.connected[\s\S]{0,80}Live feed disconnected\. Reconnecting…/)
  })
})

describe('failure injection', () => {
  it('names the identity it reaches and how each failure ends', () => {
    render(<FailurePanel robots={[robot]} failures={[]} />)
    expect(screen.getByRole('option', { name: 'r1 · ActuNode · MOVING' })).toBeTruthy()
    const type = screen.getByLabelText('Failure type')
    const ends = {
      BLOCKED_PATH: /Stays until you clear it\./,
      LOW_BATTERY: /charging does not end it/,
      DISCONNECT: /Ends by itself after the duration/,
      UNRESPONSIVE: /Ends by itself after the duration/,
      INVALID_PAYLOAD: /once; normal traffic goes on/,
    }
    for (const [failure, text] of Object.entries(ends)) {
      fireEvent.change(type, { target: { value: failure } })
      expect(screen.getByText(text)).toBeTruthy()
    }
  })

  it('shows that an injection is being sent and cannot be sent twice', () => {
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise(() => {})))
    render(<FailurePanel robots={[robot]} failures={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Inject' }))
    const busy = screen.getByRole('button', { name: 'Sending…' }) as HTMLButtonElement
    expect(busy.disabled).toBe(true)
  })
})

describe('sessions and replay', () => {
  const recording = (sizeBytes?: number): RecordingStatus =>
    ({ sessionId: 's1', name: null, startedAt: '2026-10-10T12:00:00Z', messageCount: 0, duration: 0, ...(sizeBytes === undefined ? {} : { sizeBytes }) }) as RecordingStatus

  it('shows an unknown recording size as unknown, not 0 B', () => {
    sessionsEmpty()
    const { container } = render(<RecorderPanel recording={recording()} recordingStopped={null as never} replay={null} />)
    expect(container.textContent).not.toMatch(/\b0 B\b/)
    expect(container.textContent).toMatch(/—/)
  })

  it('explains the replay options next to them, without changing their labels', () => {
    sessionsEmpty()
    render(<RecorderPanel recording={null} recordingStopped={null as never} replay={null} />)
    expect(screen.getByLabelText('Current time')).toBeTruthy()
    expect(screen.getByLabelText('Include commands (orders, failure injections)')).toBeTruthy()
    expect(screen.getByText(/each message gets the time it is sent again/)).toBeTruthy()
    expect(screen.getByText(/robots that are listening would carry them out/)).toBeTruthy()
    expect(screen.getByText(/as downloaded here or made by/)).toBeTruthy()
  })

  it('shows that a replay is being stopped and cannot be stopped twice', () => {
    vi.mocked(api.stopReplay).mockReturnValue(new Promise(() => {}))
    const replay = { sessionId: 's', state: 'running', speed: 1, includeCommands: false, sent: 1, total: 9, position: 1, duration: 9 } as ReplayStatus
    render(<ReplayBanner replay={replay} />)
    fireEvent.click(screen.getByRole('button', { name: '■ Stop replay' }))
    const busy = screen.getByRole('button', { name: 'Stopping…' }) as HTMLButtonElement
    expect(busy.disabled).toBe(true)
    expect(api.stopReplay).toHaveBeenCalledTimes(1)
  })
})
